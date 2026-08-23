"""Database migration and offline fixture-ingestion commands."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy.orm import Session, sessionmaker

from pixiv_yuri.acquisition.first_request_slot import (
    FirstRequestAlreadyClaimedError,
    FirstRequestClaim,
    FirstRequestSlotService,
)
from pixiv_yuri.acquisition.live_attempt_report import build_live_attempt_operator_report
from pixiv_yuri.acquisition.live_execution_journal import (
    LiveExecutionJournalService,
    LiveExecutionState,
)
from pixiv_yuri.acquisition.live_slot_reconciler import LiveSlotReconciliationService
from pixiv_yuri.acquisition.parsers.registry import build_offline_fixture_registry
from pixiv_yuri.acquisition.persistent_safety import PersistentAcquisitionSafety
from pixiv_yuri.acquisition.providers.fixture import FixtureProvider
from pixiv_yuri.acquisition.safety import (
    AcquisitionDeferredError,
    DuplicateRequestPermitError,
)
from pixiv_yuri.analytics.projection import project_fixture_catalog
from pixiv_yuri.data_quality.validation import load_schema_policy
from pixiv_yuri.governance.g0 import (
    G0Approval,
    approval_fingerprint,
    load_active_g0_approval,
)
from pixiv_yuri.ingest.models import CrawlRun
from pixiv_yuri.ingest.service import ingest_fixture_provider
from pixiv_yuri.shared.config import Settings
from pixiv_yuri.shared.database import build_engine, build_session_factory, session_scope
from pixiv_yuri.shared.logging import configure_logging


def build_parser() -> argparse.ArgumentParser:
    """Build the database CLI without exposing credentials in defaults."""
    parser = argparse.ArgumentParser(prog="pyuri-db")
    subparsers = parser.add_subparsers(dest="command", required=True)

    migrate = subparsers.add_parser("migrate", help="Upgrade PostgreSQL to Alembic head.")
    migrate.add_argument("--database-url")
    migrate.add_argument("--alembic-config", type=Path, default=Path("alembic.ini"))

    ingest = subparsers.add_parser(
        "ingest-fixtures", help="Persist an approved offline fixture manifest."
    )
    ingest.add_argument("--database-url")
    ingest.add_argument("--manifest", type=Path)
    ingest.add_argument(
        "--schema-policy",
        type=Path,
        help="Optional exact fixture policy; approved routes are parsed and status is recorded.",
    )
    ingest.add_argument("--requested-by", default="offline-cli")
    ingest.add_argument(
        "--allow-sqlite-for-tests",
        action="store_true",
        help="Permit SQLite only for automated tests; PostgreSQL is the real target.",
    )

    safety_smoke = subparsers.add_parser(
        "safety-smoke",
        help="Verify PostgreSQL row-lock serialization with no external transport.",
    )
    safety_smoke.add_argument("--database-url")
    safety_smoke.add_argument("--approval", type=Path, required=True)

    live_report = subparsers.add_parser(
        "live-attempt-report",
        help="Write a read-only payload-free report of unresolved live attempts.",
    )
    live_report.add_argument("--database-url")
    live_report.add_argument("--output", type=Path)
    live_report.add_argument("--limit", type=int, default=100)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run a migration or fixture ledger ingestion."""
    args = build_parser().parse_args(argv)
    settings = Settings.from_env()
    configure_logging(settings.log_level)
    database_url = args.database_url or os.getenv("PYURI_DATABASE_URL")
    if not database_url:
        raise SystemExit("Database URL is required via --database-url or PYURI_DATABASE_URL.")

    if args.command == "migrate":
        if database_url.startswith("sqlite"):
            raise SystemExit("Alembic migrations target PostgreSQL, not SQLite.")
        config = Config(str(args.alembic_config.resolve()))
        config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
        command.upgrade(config, "head")
        return 0

    if args.command == "safety-smoke":
        if database_url.startswith("sqlite"):
            raise SystemExit("The safety smoke test requires PostgreSQL row locks.")
        safety_result = _run_safety_smoke(database_url, args.approval.resolve())
        print(json.dumps(safety_result, sort_keys=True))
        return 0

    if args.command == "live-attempt-report":
        factory = build_session_factory(build_engine(database_url))
        report = build_live_attempt_operator_report(factory, limit=args.limit)
        rendered = json.dumps(asdict(report), ensure_ascii=False, sort_keys=True)
        if args.output is None:
            print(rendered)
        else:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered + "\n", encoding="utf-8")
        return 0

    if database_url.startswith("sqlite") and not args.allow_sqlite_for_tests:
        raise SystemExit("SQLite is test-only; pass --allow-sqlite-for-tests explicitly.")
    manifest = (args.manifest or settings.fixture_manifest).resolve()
    engine = build_engine(database_url)
    factory = build_session_factory(engine)
    with session_scope(factory) as session:
        schema_policy = (
            load_schema_policy(args.schema_policy.resolve()) if args.schema_policy else None
        )
        provider = FixtureProvider(manifest)
        ingest_result = ingest_fixture_provider(
            session,
            provider,
            requested_by=args.requested_by,
            schema_policy=schema_policy,
            parser_registry=build_offline_fixture_registry() if schema_policy else None,
        )
        projection_result = (
            project_fixture_catalog(session, provider) if schema_policy is not None else None
        )
    output: dict[str, object] = asdict(ingest_result)
    if projection_result is not None:
        output["catalog_projection"] = asdict(projection_result)
    print(json.dumps(output, sort_keys=True))
    return 0


def _run_safety_smoke(database_url: str, approval_path: Path) -> dict[str, object]:
    """Race cross-day permits and verify persistent logical-key idempotency."""
    approval = load_active_g0_approval(approval_path)
    smoke_approval = approval.model_copy(
        update={"purpose": f"{approval.purpose} [postgres-safety-smoke:{uuid4()}]"}
    )
    fingerprint = approval_fingerprint(smoke_approval)
    engine = build_engine(database_url)
    factory = build_session_factory(engine)
    now = datetime.now(UTC)
    boundary = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    reservation_times = (boundary - timedelta(microseconds=1), boundary)
    run_ids: list[int] = []
    with factory.begin() as session:
        for started_at in reservation_times:
            run = CrawlRun(
                run_type="postgres_safety_smoke",
                provider="none",
                status="running",
                config_snapshot={"approval_fingerprint": fingerprint, "network": False},
                requested_by="docker-integration",
                started_at=started_at,
            )
            session.add(run)
            session.flush()
            run_ids.append(run.id)

    controllers = tuple(
        PersistentAcquisitionSafety(factory, smoke_approval, run_id) for run_id in run_ids
    )
    for controller, reservation_time in zip(controllers, reservation_times, strict=True):
        controller.initialize(now=reservation_time)
    barrier = Barrier(2)

    def reserve(index: int) -> tuple[str, int, str | None]:
        barrier.wait()
        try:
            permit = controllers[index].authorize_request(
                request_key=f"smoke:cross-day:{index}",
                now=reservation_times[index],
            )
        except AcquisitionDeferredError:
            return "deferred", index, None
        return "authorized", index, permit.permit_id

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(reserve, index) for index in range(2)]
        outcomes = [future.result() for future in futures]

    authorized = [
        (index, permit_id)
        for status, index, permit_id in outcomes
        if status == "authorized"
    ]
    deferred = [status for status, _, _ in outcomes if status == "deferred"]
    if len(authorized) != 1 or len(deferred) != 1 or authorized[0] is None:
        raise RuntimeError("PostgreSQL safety contention did not serialize to one permit.")
    authorized_index, authorized_permit_id = authorized[0]
    assert authorized_permit_id is not None
    controllers[authorized_index].record_response(
        authorized_permit_id,
        200,
        now=reservation_times[authorized_index],
    )
    try:
        controllers[authorized_index].authorize_request(
            request_key=f"smoke:cross-day:{authorized_index}",
            now=reservation_times[authorized_index] + timedelta(seconds=1),
        )
    except DuplicateRequestPermitError:
        idempotency_rejected = True
    else:
        raise RuntimeError("PostgreSQL safety accepted a duplicate logical request.")

    slot_service = FirstRequestSlotService(factory)
    slot_barrier = Barrier(2)

    def claim_first_slot(index: int) -> tuple[str, FirstRequestClaim | None]:
        slot_barrier.wait()
        try:
            claim = slot_service.claim(
                approval_fingerprint=fingerprint,
                run_id=run_ids[index],
                request_key=f"smoke:first-request:{index}",
                now=reservation_times[index],
            )
        except FirstRequestAlreadyClaimedError:
            return "rejected", None
        return "claimed", claim

    with ThreadPoolExecutor(max_workers=2) as executor:
        slot_outcomes = [
            future.result()
            for future in (
                executor.submit(claim_first_slot, 0),
                executor.submit(claim_first_slot, 1),
            )
        ]
    claims = [claim for status, claim in slot_outcomes if status == "claimed"]
    rejected_slots = [status for status, _ in slot_outcomes if status == "rejected"]
    if len(claims) != 1 or len(rejected_slots) != 1 or claims[0] is None:
        raise RuntimeError("PostgreSQL first-request slot contention was not unique.")
    claim = claims[0]
    claim_index = run_ids.index(claim.run_id)
    claim_request_key = f"smoke:first-request:{claim_index}"
    journal_service = LiveExecutionJournalService(factory)
    journal = journal_service.claim(
        approval_fingerprint=fingerprint,
        run_id=claim.run_id,
        slot_id=claim.slot_id,
        request_binding_hash=claim.request_key_hash,
        now=max(reservation_times) + timedelta(seconds=1),
    )
    atomic_permit = controllers[claim_index].authorize_and_start_live_send(
        journal_id=journal.journal_id,
        request_key=claim_request_key,
        now=max(reservation_times) + timedelta(seconds=2),
    )
    started = journal_service.get(journal.journal_id)
    if (
        started.state != LiveExecutionState.SEND_STARTED
        or started.permit_id != atomic_permit.permit_id
    ):
        raise RuntimeError("PostgreSQL atomic live-send prepare did not commit together.")
    recovered = journal_service.mark_indeterminate(
        journal.journal_id,
        failure_code="postgres_smoke_no_send",
        now=max(reservation_times) + timedelta(seconds=3),
    )
    reconciliation = LiveSlotReconciliationService(factory).reconcile(
        journal.journal_id,
        now=max(reservation_times) + timedelta(seconds=3),
    )
    if reconciliation.slot_status != "failed" or reconciliation.resent:
        raise RuntimeError("PostgreSQL no-resend slot reconciliation failed.")

    crash_matrix = _run_postgres_reconciliation_matrix(
        factory,
        approval,
        now=max(reservation_times) + timedelta(seconds=10),
    )

    with factory.begin() as session:
        for run_id in run_ids:
            saved_run = session.get(CrawlRun, run_id)
            assert saved_run is not None
            saved_run.status = "completed"
            saved_run.finished_at = datetime.now(UTC)

    return {
        "status": "passed",
        "authorized": 1,
        "deferred": 1,
        "cross_utc_day_lock": True,
        "idempotency_rejected": idempotency_rejected,
        "first_request_slot_claimed": 1,
        "first_request_slot_rejected": 1,
        "atomic_live_send_prepare": started.state.value,
        "no_send_recovery": recovered.state.value,
        "journal_to_slot_reconciliation": reconciliation.slot_status,
        "reconciliation_resent": reconciliation.resent,
        "crash_reconciliation_matrix": crash_matrix,
        "network_used": False,
        "approval_fingerprint": fingerprint,
        "run_ids": run_ids,
    }


def _run_postgres_reconciliation_matrix(
    factory: sessionmaker[Session],
    approval: G0Approval,
    *,
    now: datetime,
) -> dict[str, str]:
    """Exercise restart boundaries using only durable state and no sender."""
    results: dict[str, str] = {}
    for offset, initial_state in enumerate(("claimed", "settled", "completed"), start=1):
        scenario_approval = approval.model_copy(
            update={
                "purpose": (
                    f"{approval.purpose} "
                    f"[postgres-reconcile-{initial_state}:{uuid4()}]"
                )
            }
        )
        fingerprint = approval_fingerprint(scenario_approval)
        scenario_now = now + timedelta(seconds=offset)
        with factory.begin() as session:
            run = CrawlRun(
                run_type=f"postgres_reconcile_{initial_state}",
                provider="none",
                status="running",
                config_snapshot={"network": False, "initial_state": initial_state},
                requested_by="docker-integration",
                started_at=scenario_now,
            )
            session.add(run)
            session.flush()
            run_id = run.id
        safety = PersistentAcquisitionSafety(factory, scenario_approval, run_id)
        safety.initialize(now=scenario_now)
        request_key = f"smoke:reconcile:{initial_state}"
        claim = FirstRequestSlotService(factory).claim(
            approval_fingerprint=fingerprint,
            run_id=run_id,
            request_key=request_key,
            now=scenario_now,
        )
        journals = LiveExecutionJournalService(factory)
        journal = journals.claim(
            approval_fingerprint=fingerprint,
            run_id=run_id,
            slot_id=claim.slot_id,
            request_binding_hash=claim.request_key_hash,
            now=scenario_now,
        )
        if initial_state in {"settled", "completed"}:
            permit = safety.authorize_and_start_live_send(
                journal_id=journal.journal_id,
                request_key=request_key,
                now=scenario_now,
            )
            safety.record_response(permit.permit_id, 200, now=scenario_now)
            settled = journals.settle(
                journal.journal_id,
                permit_id=permit.permit_id,
                now=scenario_now,
            )
            if initial_state == "completed":
                journals.complete(settled.journal_id, now=scenario_now)
        result = LiveSlotReconciliationService(factory).reconcile(
            journal.journal_id,
            now=scenario_now,
        )
        expected = "completed" if initial_state == "completed" else "failed"
        if result.slot_status != expected or result.resent:
            raise RuntimeError("PostgreSQL crash reconciliation matrix failed.")
        results[initial_state] = result.journal_state.value
        with factory.begin() as session:
            saved_run = session.get(CrawlRun, run_id)
            assert saved_run is not None
            saved_run.status = "completed"
            saved_run.finished_at = scenario_now
    return results


if __name__ == "__main__":
    raise SystemExit(main())
