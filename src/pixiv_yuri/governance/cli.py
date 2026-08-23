"""CLI for validating an explicit G0 decision record without network access."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from pixiv_yuri.governance.g0 import approval_fingerprint, load_active_g0_approval


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pyuri-g0")
    parser.add_argument("approval", type=Path, help="G0 approval JSON file.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Validate one active G0 approval record and print a safe audit summary."""
    args = build_parser().parse_args(argv)
    try:
        approval = load_active_g0_approval(args.approval.resolve())
    except (OSError, ValueError, ValidationError) as exc:
        print(
            json.dumps(
                {"status": "rejected", "error": "invalid_g0_approval", "detail": str(exc)},
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2

    print(
        json.dumps(
            {
                "status": "approved",
                "fingerprint": approval_fingerprint(approval),
                "expires_at": approval.expires_at.isoformat(),
                "page_types": sorted(approval.source_scope.page_types),
                "authentication_mode": approval.source_scope.authentication_mode,
                "content_visibility": approval.source_scope.content_visibility,
                "allowed_age_ratings": sorted(approval.source_scope.allowed_age_ratings),
                "allowed_field_count": len(approval.source_scope.allowed_fields),
                "daily_request_cap": approval.traffic_limits.daily_request_cap,
                "per_run_request_cap": approval.traffic_limits.per_run_request_cap,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
