from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from pixiv_yuri.acquisition.first_request_slot import (
    FirstRequestAlreadyClaimedError,
    FirstRequestSlotBindingError,
    FirstRequestSlotService,
)
from pixiv_yuri.acquisition.persistence_models import (
    AcquisitionFirstRequestSlot,
    AcquisitionRunBudget,
)
from pixiv_yuri.ingest.models import CrawlRun
from pixiv_yuri.shared.database import Base

NOW = datetime(2026, 8, 23, tzinfo=UTC)
FINGERPRINT = "a" * 64
REQUEST_KEY = "work:42:metadata"


def build_factory(*, run_count: int = 1) -> tuple[sessionmaker[Session], tuple[int, ...]]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        execution_options={"schema_translate_map": {"ingest": None}},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    run_ids: list[int] = []
    with factory.begin() as session:
        for sequence in range(run_count):
            run = CrawlRun(
                run_type="first_request_slot_test",
                provider="host_pinned_external",
                status="running",
                config_snapshot={"sequence": sequence},
                requested_by="test",
            )
            session.add(run)
            session.flush()
            session.add(
                AcquisitionRunBudget(
                    run_id=run.id,
                    approval_fingerprint=FINGERPRINT,
                )
            )
            run_ids.append(run.id)
    return factory, tuple(run_ids)


def test_claim_is_hashed_bound_and_completes_once() -> None:
    factory, (run_id,) = build_factory()
    service = FirstRequestSlotService(factory)

    claim = service.claim(
        approval_fingerprint=FINGERPRINT,
        run_id=run_id,
        request_key=REQUEST_KEY,
        now=NOW,
    )
    service.complete(claim, now=NOW + timedelta(seconds=1))

    with factory() as session:
        row = session.scalar(select(AcquisitionFirstRequestSlot))
        assert row is not None
        assert row.approval_fingerprint == FINGERPRINT
        assert row.run_id == run_id
        assert row.request_key_hash == claim.request_key_hash
        assert len(row.request_key_hash) == 64
        assert REQUEST_KEY not in row.request_key_hash
        assert row.status == "completed"
        assert row.resolved_at is not None

    with pytest.raises(FirstRequestSlotBindingError, match="terminal"):
        service.complete(claim, now=NOW + timedelta(seconds=2))


def test_failed_slot_is_permanent_across_runs_and_service_restarts() -> None:
    factory, (first_run, second_run) = build_factory(run_count=2)
    service = FirstRequestSlotService(factory)
    claim = service.claim(
        approval_fingerprint=FINGERPRINT,
        run_id=first_run,
        request_key=REQUEST_KEY,
        now=NOW,
    )
    service.fail(claim, now=NOW + timedelta(seconds=1))

    restarted = FirstRequestSlotService(factory)
    with pytest.raises(FirstRequestAlreadyClaimedError, match="already spent"):
        restarted.claim(
            approval_fingerprint=FINGERPRINT,
            run_id=second_run,
            request_key="work:other:metadata",
            now=NOW + timedelta(seconds=2),
        )

    with factory() as session:
        rows = session.scalars(select(AcquisitionFirstRequestSlot)).all()
        assert len(rows) == 1
        assert rows[0].status == "failed"


def test_claim_requires_run_initialized_for_same_approval() -> None:
    factory, (run_id,) = build_factory()
    service = FirstRequestSlotService(factory)

    with pytest.raises(FirstRequestSlotBindingError, match="not initialized"):
        service.claim(
            approval_fingerprint="b" * 64,
            run_id=run_id,
            request_key=REQUEST_KEY,
            now=NOW,
        )

    with factory() as session:
        assert session.scalar(select(AcquisitionFirstRequestSlot)) is None


def test_terminal_transition_rejects_forged_claim_binding() -> None:
    factory, (run_id,) = build_factory()
    service = FirstRequestSlotService(factory)
    claim = service.claim(
        approval_fingerprint=FINGERPRINT,
        run_id=run_id,
        request_key=REQUEST_KEY,
        now=NOW,
    )

    with pytest.raises(FirstRequestSlotBindingError, match="does not match"):
        service.fail(replace(claim, request_key_hash="b" * 64), now=NOW)

    with factory() as session:
        row = session.scalar(select(AcquisitionFirstRequestSlot))
        assert row is not None and row.status == "claimed"


@pytest.mark.parametrize("fingerprint", ["short", "z" * 64])
def test_invalid_approval_fingerprint_is_rejected(fingerprint: str) -> None:
    factory, (run_id,) = build_factory()

    with pytest.raises(ValueError, match="fingerprint"):
        FirstRequestSlotService(factory).claim(
            approval_fingerprint=fingerprint,
            run_id=run_id,
            request_key=REQUEST_KEY,
            now=NOW,
        )
