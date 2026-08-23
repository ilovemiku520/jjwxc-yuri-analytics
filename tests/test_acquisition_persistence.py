from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from pixiv_yuri.acquisition.persistence_models import (
    AcquisitionDailyBudget,
    AcquisitionRequestPermit,
    AcquisitionRunBudget,
    AcquisitionStopEvent,
)
from pixiv_yuri.ingest.models import CrawlRun
from pixiv_yuri.shared.database import Base


def build_test_engine() -> Engine:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        execution_options={"schema_translate_map": {"ingest": None}},
    )
    Base.metadata.create_all(engine)
    return engine


def test_non_secret_safety_state_survives_commit_and_reload() -> None:
    engine = build_test_engine()
    fingerprint = "a" * 64
    now = datetime(2026, 8, 23, tzinfo=UTC)
    with Session(engine) as session:
        run = CrawlRun(
            run_type="authenticated_fixture",
            provider="authenticated_fixture:synthetic_fixture",
            status="running",
            config_snapshot={"approval_fingerprint": fingerprint},
            requested_by="test",
        )
        session.add(run)
        session.flush()
        daily = AcquisitionDailyBudget(
            approval_fingerprint=fingerprint,
            budget_day=date(2026, 8, 23),
            request_count=1,
            estimated_cost=Decimal("0.25"),
        )
        run_budget = AcquisitionRunBudget(
            run_id=run.id,
            approval_fingerprint=fingerprint,
            request_count=1,
            in_flight_count=1,
        )
        session.add_all([daily, run_budget])
        session.flush()
        session.add_all(
            [
                AcquisitionRequestPermit(
                    permit_id="11111111-1111-1111-1111-111111111111",
                    run_budget_id=run_budget.id,
                    sequence=1,
                    request_key_hash="a" * 64,
                    approval_fingerprint=fingerprint,
                    estimated_cost=Decimal("0.25"),
                    status="authorized",
                    authorized_at=now,
                ),
                AcquisitionStopEvent(
                    approval_fingerprint=fingerprint,
                    run_id=run.id,
                    reason="manual",
                    trigger_source="operator",
                    occurred_at=now,
                ),
            ]
        )
        session.commit()

    with Session(engine) as session:
        saved_daily = session.scalar(select(AcquisitionDailyBudget))
        saved_run = session.scalar(select(AcquisitionRunBudget))
        saved_permit = session.scalar(select(AcquisitionRequestPermit))
        saved_stop = session.scalar(select(AcquisitionStopEvent))

        assert saved_daily is not None and saved_daily.request_count == 1
        assert saved_run is not None and saved_run.in_flight_count == 1
        assert saved_permit is not None and saved_permit.status == "authorized"
        assert saved_stop is not None and saved_stop.reason == "manual"
