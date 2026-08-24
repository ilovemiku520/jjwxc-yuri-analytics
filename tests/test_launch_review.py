from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from pixiv_yuri.acquisition.persistence_models import (
    AcquisitionFirstRequestSlot,
    AcquisitionRequestPermit,
    AcquisitionRunBudget,
)
from pixiv_yuri.governance.g0 import G0Approval, approval_fingerprint
from pixiv_yuri.governance.launch_review import review_launch
from pixiv_yuri.ingest.models import CrawlRun
from pixiv_yuri.shared.database import Base
from tests.test_g0_governance import valid_approval_payload

NOW = datetime(2026, 8, 23, tzinfo=UTC)


def build_engine_with_version(version: str = "20260824_0012") -> Engine:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        execution_options={"schema_translate_map": {"ingest": None}},
    )
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32))"))
        connection.execute(
            text("INSERT INTO alembic_version (version_num) VALUES (:version)"),
            {"version": version},
        )
    return engine


def approval() -> G0Approval:
    return G0Approval.model_validate(valid_approval_payload())


def test_launch_review_passes_all_read_only_gates() -> None:
    result = review_launch(
        build_engine_with_version(),
        approval(),
        planned_request_cap=25,
        now=NOW,
        allow_sqlite_for_tests=True,
    )

    assert result.status == "passed"
    assert result.violations == ()
    assert result.postgres_ready is True
    assert result.external_network_used is False


def test_expired_approval_blocks_launch() -> None:
    result = review_launch(
        build_engine_with_version(),
        approval(),
        planned_request_cap=25,
        now=datetime(2026, 10, 1, tzinfo=UTC),
        allow_sqlite_for_tests=True,
    )

    assert result.status == "blocked"
    assert "approval_inactive" in result.violations


def test_planned_cap_cannot_exceed_g0() -> None:
    result = review_launch(
        build_engine_with_version(),
        approval(),
        planned_request_cap=26,
        now=NOW,
        allow_sqlite_for_tests=True,
    )

    assert result.status == "blocked"
    assert "planned_cap_exceeds_approval" in result.violations


def test_old_migration_blocks_launch() -> None:
    result = review_launch(
        build_engine_with_version("20260822_0001"),
        approval(),
        planned_request_cap=25,
        now=NOW,
        allow_sqlite_for_tests=True,
    )

    assert result.status == "blocked"
    assert "migration_not_current" in result.violations


def test_active_permit_blocks_launch() -> None:
    engine = build_engine_with_version()
    approved = approval()
    fingerprint = approval_fingerprint(approved)
    with Session(engine) as session:
        run = CrawlRun(
            run_type="test",
            provider="none",
            status="running",
            config_snapshot={},
            requested_by="test",
        )
        session.add(run)
        session.flush()
        run_budget = AcquisitionRunBudget(
            run_id=run.id,
            approval_fingerprint=fingerprint,
            request_count=1,
            in_flight_count=1,
        )
        session.add(run_budget)
        session.flush()
        session.add(
            AcquisitionRequestPermit(
                permit_id="11111111-1111-1111-1111-111111111111",
                run_budget_id=run_budget.id,
                sequence=1,
                request_key_hash="a" * 64,
                approval_fingerprint=fingerprint,
                estimated_cost=0,
                status="authorized",
                authorized_at=NOW,
            )
        )
        session.commit()

    result = review_launch(
        engine,
        approved,
        planned_request_cap=25,
        now=NOW,
        allow_sqlite_for_tests=True,
    )
    assert "active_permits_exist" in result.violations


def test_stopped_run_blocks_launch() -> None:
    engine = build_engine_with_version()
    approved = approval()
    with Session(engine) as session:
        run = CrawlRun(
            run_type="test",
            provider="none",
            status="cancelled",
            config_snapshot={},
            requested_by="test",
        )
        session.add(run)
        session.flush()
        session.add(
            AcquisitionRunBudget(
                run_id=run.id,
                approval_fingerprint=approval_fingerprint(approved),
                stop_reason="manual",
            )
        )
        session.commit()

    result = review_launch(
        engine,
        approved,
        planned_request_cap=25,
        now=NOW,
        allow_sqlite_for_tests=True,
    )
    assert "stopped_runs_exist" in result.violations


def test_existing_first_request_slot_blocks_launch() -> None:
    engine = build_engine_with_version()
    approved = approval()
    fingerprint = approval_fingerprint(approved)
    with Session(engine) as session:
        run = CrawlRun(
            run_type="test",
            provider="none",
            status="running",
            config_snapshot={},
            requested_by="test",
        )
        session.add(run)
        session.flush()
        session.add(
            AcquisitionRunBudget(
                run_id=run.id,
                approval_fingerprint=fingerprint,
            )
        )
        session.add(
            AcquisitionFirstRequestSlot(
                approval_fingerprint=fingerprint,
                run_id=run.id,
                request_key_hash="b" * 64,
                status="claimed",
                claimed_at=NOW,
            )
        )
        session.commit()

    result = review_launch(
        engine,
        approved,
        planned_request_cap=25,
        now=NOW,
        allow_sqlite_for_tests=True,
    )

    assert "first_request_slot_already_spent" in result.violations
