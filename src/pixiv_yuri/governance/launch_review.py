"""Read-only first-sample launch review over existing G0 and safety state."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import Engine, func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from pixiv_yuri.acquisition.persistence_models import (
    AcquisitionFirstRequestSlot,
    AcquisitionRequestPermit,
    AcquisitionRunBudget,
)
from pixiv_yuri.governance.g0 import (
    G0Approval,
    approval_fingerprint,
    load_active_g0_approval,
)
from pixiv_yuri.shared.config import Settings
from pixiv_yuri.shared.database import build_engine

EXPECTED_MIGRATION_VERSION = "20260823_0011"


@dataclass(frozen=True, slots=True)
class LaunchReviewResult:
    """Non-secret, machine-readable launch decision."""

    status: str
    checked_at: str
    approval_fingerprint: str
    approval_expires_at: str
    migration_version: str
    postgres_ready: bool
    planned_request_cap: int
    approved_request_cap: int
    active_permit_count: int
    first_request_slot_count: int
    stopped_run_count: int
    external_network_used: bool
    violations: tuple[str, ...]


def review_launch(
    engine: Engine,
    approval: G0Approval,
    *,
    planned_request_cap: int,
    now: datetime | None = None,
    allow_sqlite_for_tests: bool = False,
) -> LaunchReviewResult:
    """Check launch prerequisites with SELECT statements only."""
    checked_at = now or datetime.now(UTC)
    if checked_at.tzinfo is None or checked_at.utcoffset() is None:
        raise ValueError("Launch review time must include a timezone.")
    if planned_request_cap < 1:
        raise ValueError("Planned request cap must be positive.")
    if engine.dialect.name != "postgresql" and not allow_sqlite_for_tests:
        raise ValueError("Launch review requires PostgreSQL.")

    fingerprint = approval_fingerprint(approval)
    violations: list[str] = []
    if not (approval.approved_at <= checked_at < approval.expires_at):
        violations.append("approval_inactive")
    if planned_request_cap > approval.traffic_limits.per_run_request_cap:
        violations.append("planned_cap_exceeds_approval")

    with Session(engine) as session:
        ready = session.scalar(text("SELECT 1")) == 1
        migration_version = str(
            session.scalar(text("SELECT version_num FROM alembic_version")) or "missing"
        )
        active_permits = int(
            session.scalar(
                select(func.count())
                .select_from(AcquisitionRequestPermit)
                .where(
                    AcquisitionRequestPermit.approval_fingerprint == fingerprint,
                    AcquisitionRequestPermit.status == "authorized",
                )
            )
            or 0
        )
        first_request_slots = int(
            session.scalar(
                select(func.count())
                .select_from(AcquisitionFirstRequestSlot)
                .where(AcquisitionFirstRequestSlot.approval_fingerprint == fingerprint)
            )
            or 0
        )
        stopped_runs = int(
            session.scalar(
                select(func.count())
                .select_from(AcquisitionRunBudget)
                .where(
                    AcquisitionRunBudget.approval_fingerprint == fingerprint,
                    AcquisitionRunBudget.stop_reason.is_not(None),
                )
            )
            or 0
        )

    if not ready:
        violations.append("database_not_ready")
    if migration_version != EXPECTED_MIGRATION_VERSION:
        violations.append("migration_not_current")
    if active_permits:
        violations.append("active_permits_exist")
    if first_request_slots:
        violations.append("first_request_slot_already_spent")
    if stopped_runs:
        violations.append("stopped_runs_exist")
    return LaunchReviewResult(
        status="passed" if not violations else "blocked",
        checked_at=checked_at.astimezone(UTC).isoformat(),
        approval_fingerprint=fingerprint,
        approval_expires_at=approval.expires_at.isoformat(),
        migration_version=migration_version,
        postgres_ready=ready,
        planned_request_cap=planned_request_cap,
        approved_request_cap=approval.traffic_limits.per_run_request_cap,
        active_permit_count=active_permits,
        first_request_slot_count=first_request_slots,
        stopped_run_count=stopped_runs,
        external_network_used=False,
        violations=tuple(violations),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pyuri-launch-review")
    parser.add_argument("--approval", type=Path, required=True)
    parser.add_argument("--database-url")
    parser.add_argument("--planned-request-cap", type=int, default=25)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run a non-transport launch review and write only safe decision fields."""
    args = build_parser().parse_args(argv)
    Settings.from_env()
    database_url = args.database_url or os.getenv("PYURI_DATABASE_URL")
    if not database_url:
        return _write_rejection(args.output, "database_url_missing")
    try:
        approval = load_active_g0_approval(args.approval.resolve())
        engine = build_engine(database_url)
        result = review_launch(
            engine,
            approval,
            planned_request_cap=args.planned_request_cap,
        )
    except (OSError, ValueError, ValidationError, SQLAlchemyError):
        return _write_rejection(args.output, "launch_review_failed")

    payload = asdict(result)
    _write_payload(args.output, payload)
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0 if result.status == "passed" else 2


def _write_rejection(output: Path | None, error_code: str) -> int:
    payload = {
        "status": "rejected",
        "error_code": error_code,
        "external_network_used": False,
    }
    _write_payload(output, payload)
    print(json.dumps(payload, sort_keys=True), file=sys.stderr)
    return 2


def _write_payload(output: Path | None, payload: dict[str, object]) -> None:
    if output is None:
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
