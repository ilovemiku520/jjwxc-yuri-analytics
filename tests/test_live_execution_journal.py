from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from pixiv_yuri.acquisition.live_execution_journal import (
    LiveExecutionAlreadyClaimedError,
    LiveExecutionBindingError,
    LiveExecutionJournalRecord,
    LiveExecutionJournalService,
    LiveExecutionState,
    LiveExecutionTransitionError,
)
from pixiv_yuri.acquisition.persistence_models import (
    AcquisitionFirstRequestSlot,
    AcquisitionLiveExecutionJournal,
    AcquisitionRequestPermit,
    AcquisitionRunBudget,
)
from pixiv_yuri.ingest.models import CrawlRun
from pixiv_yuri.shared.database import Base

NOW = datetime(2026, 8, 23, tzinfo=UTC)
FINGERPRINT = "a" * 64
BINDING_HASH = "b" * 64
PERMIT_ID = "11111111-1111-1111-1111-111111111111"


def build_state() -> tuple[sessionmaker[Session], LiveExecutionJournalService, int, int]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        execution_options={"schema_translate_map": {"ingest": None}},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory.begin() as session:
        run = CrawlRun(
            run_type="live_journal_test",
            provider="synthetic",
            status="running",
            config_snapshot={"external_network": False},
            requested_by="test",
        )
        session.add(run)
        session.flush()
        budget = AcquisitionRunBudget(
            run_id=run.id,
            approval_fingerprint=FINGERPRINT,
            request_count=1,
            in_flight_count=1,
        )
        session.add(budget)
        session.flush()
        slot = AcquisitionFirstRequestSlot(
            approval_fingerprint=FINGERPRINT,
            run_id=run.id,
            request_key_hash=BINDING_HASH,
            status="claimed",
            claimed_at=NOW,
        )
        session.add(slot)
        session.flush()
        session.add(
            AcquisitionRequestPermit(
                permit_id=PERMIT_ID,
                run_budget_id=budget.id,
                sequence=1,
                request_key_hash=BINDING_HASH,
                approval_fingerprint=FINGERPRINT,
                estimated_cost=Decimal("0"),
                status="authorized",
                authorized_at=NOW,
            )
        )
        run_id = run.id
        slot_id = slot.id
    assert run_id is not None and slot_id is not None
    return factory, LiveExecutionJournalService(factory), run_id, slot_id


def claim_journal(
    service: LiveExecutionJournalService, run_id: int, slot_id: int
) -> LiveExecutionJournalRecord:
    return service.claim(
        approval_fingerprint=FINGERPRINT,
        run_id=run_id,
        slot_id=slot_id,
        request_binding_hash=BINDING_HASH,
        now=NOW,
    )


def consume_permit(factory: sessionmaker[Session]) -> None:
    with factory.begin() as session:
        permit = session.scalar(
            select(AcquisitionRequestPermit).where(
                AcquisitionRequestPermit.permit_id == PERMIT_ID
            )
        )
        assert permit is not None
        permit.status = "consumed"
        permit.response_status = 200
        permit.consumed_at = NOW + timedelta(seconds=2)


def test_success_path_is_claimed_send_started_settled_completed() -> None:
    factory, service, run_id, slot_id = build_state()

    claimed = claim_journal(service, run_id, slot_id)
    started = service.start_send(
        claimed.journal_id,
        permit_id=PERMIT_ID,
        now=NOW + timedelta(seconds=1),
    )
    consume_permit(factory)
    settled = service.settle(
        claimed.journal_id,
        permit_id=PERMIT_ID,
        now=NOW + timedelta(seconds=2),
    )
    completed = service.complete(claimed.journal_id, now=NOW + timedelta(seconds=3))

    assert claimed.state == LiveExecutionState.CLAIMED
    assert started.state == LiveExecutionState.SEND_STARTED
    assert settled.state == LiveExecutionState.SETTLED
    assert completed.state == LiveExecutionState.COMPLETED
    assert completed.permit_id == PERMIT_ID
    assert completed.version == 3
    with pytest.raises(LiveExecutionTransitionError):
        service.start_send(completed.journal_id, permit_id=PERMIT_ID, now=NOW)


def test_pre_send_failure_is_terminal_and_cannot_recover_to_send() -> None:
    _, service, run_id, slot_id = build_state()
    claimed = claim_journal(service, run_id, slot_id)

    failed = service.fail(
        claimed.journal_id,
        failure_code="pre_send_validation_failed",
        now=NOW + timedelta(seconds=1),
    )
    recovered = service.recover_without_resend(
        claimed.journal_id, now=NOW + timedelta(seconds=2)
    )

    assert failed.state == LiveExecutionState.FAILED
    assert recovered.state == LiveExecutionState.FAILED
    assert recovered.version == failed.version
    with pytest.raises(LiveExecutionTransitionError):
        service.start_send(claimed.journal_id, permit_id=PERMIT_ID, now=NOW)


def test_unknown_effect_after_send_start_becomes_indeterminate() -> None:
    _, service, run_id, slot_id = build_state()
    claimed = claim_journal(service, run_id, slot_id)
    service.start_send(claimed.journal_id, permit_id=PERMIT_ID, now=NOW)

    unknown = service.mark_indeterminate(
        claimed.journal_id,
        failure_code="transport_result_unknown",
        now=NOW + timedelta(seconds=1),
    )

    assert unknown.state == LiveExecutionState.INDETERMINATE
    assert unknown.failure_code == "transport_result_unknown"
    with pytest.raises(LiveExecutionTransitionError):
        service.fail(
            claimed.journal_id,
            failure_code="retry_forbidden",
            now=NOW + timedelta(seconds=2),
        )
    with pytest.raises(LiveExecutionTransitionError):
        service.start_send(claimed.journal_id, permit_id=PERMIT_ID, now=NOW)


def test_send_started_recovery_is_indeterminate_and_never_resends() -> None:
    _, service, run_id, slot_id = build_state()
    claimed = claim_journal(service, run_id, slot_id)
    service.start_send(claimed.journal_id, permit_id=PERMIT_ID, now=NOW)

    recovered = service.recover_without_resend(
        claimed.journal_id, now=NOW + timedelta(seconds=1)
    )
    repeated_recovery = service.recover_without_resend(
        claimed.journal_id, now=NOW + timedelta(seconds=2)
    )

    assert recovered.state == LiveExecutionState.INDETERMINATE
    assert recovered.failure_code == "recovery_unknown_external_effect"
    assert repeated_recovery.version == recovered.version
    with pytest.raises(LiveExecutionTransitionError):
        service.start_send(claimed.journal_id, permit_id=PERMIT_ID, now=NOW)


def test_claimed_and_settled_recovery_terminalize_without_resend() -> None:
    factory, service, run_id, slot_id = build_state()
    claimed = claim_journal(service, run_id, slot_id)
    before_send = service.recover_without_resend(claimed.journal_id, now=NOW)
    assert before_send.state == LiveExecutionState.FAILED
    assert before_send.failure_code == "recovery_before_send"

    other_factory, other_service, other_run, other_slot = build_state()
    other = claim_journal(other_service, other_run, other_slot)
    other_service.start_send(other.journal_id, permit_id=PERMIT_ID, now=NOW)
    consume_permit(other_factory)
    other_service.settle(other.journal_id, permit_id=PERMIT_ID, now=NOW)
    after_settlement = other_service.recover_without_resend(other.journal_id, now=NOW)
    assert after_settlement.state == LiveExecutionState.FAILED
    assert after_settlement.failure_code == "recovery_after_settlement"
    del factory


def test_slot_and_request_binding_must_match_authoritative_row() -> None:
    factory, service, run_id, slot_id = build_state()

    with pytest.raises(LiveExecutionBindingError):
        service.claim(
            approval_fingerprint=FINGERPRINT,
            run_id=run_id,
            slot_id=slot_id,
            request_binding_hash="d" * 64,
            now=NOW,
        )

    with factory() as session:
        assert session.scalar(select(AcquisitionLiveExecutionJournal)) is None


def test_one_slot_cannot_create_two_journals() -> None:
    _, service, run_id, slot_id = build_state()
    first = claim_journal(service, run_id, slot_id)

    with pytest.raises(LiveExecutionAlreadyClaimedError):
        claim_journal(service, run_id, slot_id)

    assert service.get(first.journal_id).state == LiveExecutionState.CLAIMED


def test_settle_rejects_authorized_or_transport_failed_permit() -> None:
    factory, service, run_id, slot_id = build_state()
    claimed = claim_journal(service, run_id, slot_id)
    service.start_send(claimed.journal_id, permit_id=PERMIT_ID, now=NOW)

    with pytest.raises(LiveExecutionTransitionError, match="known response"):
        service.settle(claimed.journal_id, permit_id=PERMIT_ID, now=NOW)

    with factory.begin() as session:
        permit = session.scalar(
            select(AcquisitionRequestPermit).where(
                AcquisitionRequestPermit.permit_id == PERMIT_ID
            )
        )
        assert permit is not None
        permit.status = "transport_failed"
        permit.consumed_at = NOW
    with pytest.raises(LiveExecutionTransitionError, match="known response"):
        service.settle(claimed.journal_id, permit_id=PERMIT_ID, now=NOW)

    unknown = service.mark_indeterminate(claimed.journal_id, now=NOW)
    assert unknown.state == LiveExecutionState.INDETERMINATE


def test_permit_must_match_the_journal_request_binding_hash() -> None:
    factory, service, run_id, slot_id = build_state()
    claimed = claim_journal(service, run_id, slot_id)
    with factory.begin() as session:
        permit = session.scalar(
            select(AcquisitionRequestPermit).where(
                AcquisitionRequestPermit.permit_id == PERMIT_ID
            )
        )
        assert permit is not None
        permit.request_key_hash = "d" * 64

    with pytest.raises(LiveExecutionBindingError, match="binding"):
        service.start_send(claimed.journal_id, permit_id=PERMIT_ID, now=NOW)

    assert service.get(claimed.journal_id).state == LiveExecutionState.CLAIMED


@pytest.mark.parametrize("bad_code", ["", "UPPER", "has space", "x" * 65])
def test_failure_codes_are_bounded_safe_identifiers(bad_code: str) -> None:
    _, service, run_id, slot_id = build_state()
    claimed = claim_journal(service, run_id, slot_id)

    with pytest.raises(ValueError, match="Failure code"):
        service.fail(claimed.journal_id, failure_code=bad_code, now=NOW)

    assert service.get(claimed.journal_id).state == LiveExecutionState.CLAIMED
