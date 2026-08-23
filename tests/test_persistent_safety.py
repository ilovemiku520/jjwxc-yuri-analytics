from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from pixiv_yuri.acquisition.persistence_models import (
    AcquisitionDailyBudget,
    AcquisitionRequestPermit,
    AcquisitionRunBudget,
    AcquisitionStopEvent,
)
from pixiv_yuri.acquisition.persistent_safety import PersistentAcquisitionSafety
from pixiv_yuri.acquisition.safety import (
    AcquisitionDeferredError,
    AcquisitionStoppedError,
    DuplicateRequestPermitError,
)
from pixiv_yuri.governance.g0 import G0Approval
from pixiv_yuri.ingest.models import CrawlRun
from pixiv_yuri.shared.database import Base
from tests.test_g0_governance import valid_approval_payload

NOW = datetime(2026, 8, 23, tzinfo=UTC)


def load_approval() -> G0Approval:
    return G0Approval.model_validate(valid_approval_payload())


def build_factory() -> tuple[sessionmaker[Session], int]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        execution_options={"schema_translate_map": {"ingest": None}},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory.begin() as session:
        run = CrawlRun(
            run_type="authenticated_fixture",
            provider="authenticated_fixture:synthetic_fixture",
            status="running",
            config_snapshot={},
            requested_by="test",
        )
        session.add(run)
        session.flush()
        run_id = run.id
    return factory, run_id


def test_permit_reservation_survives_controller_restart_and_is_one_use() -> None:
    factory, run_id = build_factory()
    controller = PersistentAcquisitionSafety(factory, load_approval(), run_id)
    controller.initialize(now=NOW)
    permit = controller.authorize_request(
        request_key="work:restart", now=NOW, estimated_cost=Decimal("0.25")
    )

    restarted = PersistentAcquisitionSafety(factory, load_approval(), run_id)
    restarted.record_response(permit.permit_id, 200, now=NOW + timedelta(seconds=1))
    with pytest.raises(ValueError, match="already consumed"):
        restarted.record_response(permit.permit_id, 200, now=NOW + timedelta(seconds=2))

    with factory() as session:
        daily = session.scalar(select(AcquisitionDailyBudget))
        run_budget = session.scalar(select(AcquisitionRunBudget))
        saved_permit = session.scalar(select(AcquisitionRequestPermit))
        assert daily is not None and daily.request_count == 1
        assert daily.estimated_cost == Decimal("0.250000")
        assert run_budget is not None and run_budget.in_flight_count == 0
        assert saved_permit is not None and saved_permit.status == "consumed"


def test_concurrency_is_reserved_before_transport() -> None:
    factory, run_id = build_factory()
    controller = PersistentAcquisitionSafety(factory, load_approval(), run_id)
    controller.initialize(now=NOW)
    first = controller.authorize_request(request_key="work:first", now=NOW)

    with pytest.raises(AcquisitionDeferredError, match="concurrency"):
        controller.authorize_request(request_key="work:second", now=NOW)
    controller.record_transport_failure(first.permit_id, now=NOW + timedelta(seconds=1))
    second = controller.authorize_request(
        request_key="work:second", now=NOW + timedelta(seconds=2)
    )

    assert second.sequence == 2


def test_two_consecutive_403_responses_persist_stop_event() -> None:
    factory, run_id = build_factory()
    controller = PersistentAcquisitionSafety(factory, load_approval(), run_id)
    controller.initialize(now=NOW)
    first = controller.authorize_request(request_key="work:forbidden-1", now=NOW)
    controller.record_response(first.permit_id, 403, now=NOW + timedelta(seconds=1))
    second = controller.authorize_request(
        request_key="work:forbidden-2", now=NOW + timedelta(seconds=2)
    )
    controller.record_response(second.permit_id, 403, now=NOW + timedelta(seconds=3))

    with pytest.raises(AcquisitionStoppedError, match="repeated_403"):
        controller.authorize_request(
            request_key="work:after-stop", now=NOW + timedelta(seconds=4)
        )
    with factory() as session:
        events = session.scalars(select(AcquisitionStopEvent)).all()
        assert [(event.reason, event.trigger_source) for event in events] == [
            ("repeated_403", "response")
        ]


def test_rate_limit_defers_without_consuming_budget() -> None:
    factory, run_id = build_factory()
    approval = load_approval()
    traffic = approval.traffic_limits.model_copy(update={"requests_per_minute": 1})
    approval = approval.model_copy(update={"traffic_limits": traffic})
    controller = PersistentAcquisitionSafety(factory, approval, run_id)
    controller.initialize(now=NOW)
    first = controller.authorize_request(request_key="work:rate-1", now=NOW)
    controller.record_response(first.permit_id, 200, now=NOW + timedelta(seconds=1))

    with pytest.raises(AcquisitionDeferredError, match="requests-per-minute"):
        controller.authorize_request(
            request_key="work:rate-2", now=NOW + timedelta(seconds=2)
        )
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(AcquisitionRequestPermit)) == 1


def test_daily_cost_cap_commits_stop_before_raising() -> None:
    factory, run_id = build_factory()
    controller = PersistentAcquisitionSafety(factory, load_approval(), run_id)
    controller.initialize(now=NOW)

    with pytest.raises(AcquisitionStoppedError, match="daily_cost_cap"):
        controller.authorize_request(
            request_key="work:too-expensive",
            now=NOW,
            estimated_cost=Decimal("10.01"),
        )
    with factory() as session:
        run_budget = session.scalar(select(AcquisitionRunBudget))
        event = session.scalar(select(AcquisitionStopEvent))
        assert run_budget is not None and run_budget.stop_reason == "daily_cost_cap"
        assert event is not None and event.trigger_source == "budget"


def test_duplicate_logical_request_is_rejected_without_new_budget() -> None:
    factory, run_id = build_factory()
    controller = PersistentAcquisitionSafety(factory, load_approval(), run_id)
    controller.initialize(now=NOW)
    first = controller.authorize_request(request_key="work:same", now=NOW)
    controller.record_response(first.permit_id, 200, now=NOW + timedelta(seconds=1))

    restarted = PersistentAcquisitionSafety(factory, load_approval(), run_id)
    with pytest.raises(DuplicateRequestPermitError, match="already has"):
        restarted.authorize_request(
            request_key="work:same", now=NOW + timedelta(seconds=2)
        )

    with factory() as session:
        daily = session.scalar(select(AcquisitionDailyBudget))
        permits = session.scalars(select(AcquisitionRequestPermit)).all()
        assert daily is not None and daily.request_count == 1
        assert len(permits) == 1
        assert len(permits[0].request_key_hash) == 64
        assert "work:same" not in permits[0].request_key_hash


@pytest.mark.parametrize("request_key", ["", "x" * 2049])
def test_request_key_is_bounded_before_database_access(request_key: str) -> None:
    factory, run_id = build_factory()
    controller = PersistentAcquisitionSafety(factory, load_approval(), run_id)
    controller.initialize(now=NOW)

    with pytest.raises(ValueError, match="between 1 and 2048"):
        controller.authorize_request(request_key=request_key, now=NOW)
