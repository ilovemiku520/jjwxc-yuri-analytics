"""Dry-run-only operator session preflight with no external transport."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Sequence

from pixiv_yuri.acquisition.operator_session import OperatorSessionFactory


def build_parser() -> argparse.ArgumentParser:
    """Expose TTL and dry-run only; session material has no CLI option."""
    parser = argparse.ArgumentParser(prog="pyuri-session-preflight")
    parser.add_argument("--dry-run", action="store_true", required=True)
    parser.add_argument("--session-ttl-minutes", type=int, default=15)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    reader: Callable[[str], str] | None = None,
) -> int:
    """Read, validate, summarize, and clear a runtime value without transport."""
    args = build_parser().parse_args(argv)
    with OperatorSessionFactory(reader).open(ttl_minutes=args.session_ttl_minutes) as session:
        print(
            json.dumps(
                {
                    "status": "passed",
                    "mode": "dry_run",
                    "expires_at": session.expires_at.isoformat(),
                    "external_network_used": False,
                    "session_persisted": False,
                    "session_logged": False,
                },
                sort_keys=True,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
