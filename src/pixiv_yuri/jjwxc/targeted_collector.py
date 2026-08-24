"""CLI worker for user-imported JJWXC cohort IDs."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
from pathlib import Path

from pixiv_yuri.jjwxc.catalog_collector import collect_targeted_cohort_queue
from pixiv_yuri.shared.database import build_engine, build_session_factory


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Hydrate a bounded batch from the uploaded JJWXC cohort queue."
    )
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--request-interval-seconds", type=float, default=2.0)
    parser.add_argument("--cache-ttl-hours", type=int, default=24)
    parser.add_argument("--cache-dir", default=os.getenv("JJYURI_CACHE_DIR", "var/cache/jjwxc"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.dry_run:
        print(
            json.dumps(
                {
                    "status": "dry_run",
                    "limit": args.limit,
                    "maximum_planned_requests": args.limit * 2,
                    "request_interval_seconds": args.request_interval_seconds,
                    "cache_dir": args.cache_dir,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0
    database_url = os.getenv("PYURI_DATABASE_URL")
    if not database_url:
        raise RuntimeError("database_url_missing")
    session_factory = build_session_factory(build_engine(database_url))
    try:
        with session_factory() as session:
            result = collect_targeted_cohort_queue(
                session,
                limit=args.limit,
                request_interval_seconds=args.request_interval_seconds,
                cache_dir=Path(args.cache_dir),
                cache_ttl_seconds=args.cache_ttl_hours * 60 * 60,
            )
    except (RuntimeError, ValueError, urllib.error.URLError, TimeoutError):
        print(json.dumps({"status": "blocked", "error": "targeted_collection_failed"}))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
