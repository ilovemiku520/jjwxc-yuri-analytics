from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from pixiv_yuri.acquisition.first_request_slot import (
    FirstRequestClaim,
    FirstRequestSlotService,
)
from pixiv_yuri.acquisition.live_attempt_coordinator import (
    InjectedTransportResponse,
    JournalBoundAttemptError,
    JournalBoundLiveAttemptCoordinator,
    JournalBoundSendContext,
)
from pixiv_yuri.acquisition.live_execution_journal import (
    LiveExecutionJournalService,
    LiveExecutionState,
)
from pixiv_yuri.acquisition.live_request_binding import CanonicalLiveRequestBinding
from pixiv_yuri.acquisition.models import AcquisitionRequest, EntityType
from pixiv_yuri.acquisition.persistence_models import (
    AcquisitionDailyBudget,
    AcquisitionLiveExecutionJournal,
    AcquisitionRequestPermit,
    AcquisitionRunBudget,
)
from pixiv_yuri.acquisition.persistent_safety import PersistentAcquisitionSafety
from pixiv_yuri.governance.g0 import G0Approval, approval_fingerprint
from pixiv_yuri.ingest.models import CrawlRun
from pixiv_yuri.shared.database import Base
from tests.test_g0_governance import valid_approval_payload

NOW = datetime(2026, 8, 23, tzinfo=UTC)
REQUEST_KEY = "live-one-request:synthetic:work:42"


class InspectingFakeSender:
    def __init__(
        self,
        factory: sessionmaker[Session],
        *,
        status_code: int = 200,
        failure: Exception | None = None,
    ) -> None:
        self._factory = factory
        self._status_code = status_code
        self._failure = failure
        self.calls: list[JournalBoundSendContext] = []

    def send(self, context: JournalBoundSendContext) -> InjectedTransportResponse:
        self.calls.append(context)
        with self._factory() as session:
            journal = session.get(AcquisitionLiveExecutionJournal, context.journal_id)
            permit = session.scalar(
                select(AcquisitionRequestPermit).where(
                    AcquisitionRequestPermit.permit_id == context.permit_id
                )
            )
            assert journal is not None and journal.status == "send_started"
            assert journal.permit_id == context.permit_id
            assert permit is not None and permit.status == "authorized"
            assert permit.request_key_hash == context.request_binding_hash
        if self._failure is not None:
            raise self._failure
        return InjectedTransportResponse(status_code=self._status_code)


class InspectingSettledProcessor:
    def __init__(
        self,
        factory: sessionmaker[Session],
        *,
        failure: Exception | None = None,
    ) -> None:
        self._factory = factory
        self._failure = failure
        self.calls = 0

    def process(self, response: InjectedTransportResponse) -> None:
        self.calls += 1
        with self._factory() as session:
            journal = session.scalar(select(AcquisitionLiveExecutionJournal))
            permit = session.scalar(select(AcquisitionRequestPermit))
            assert journal is not None and journal.status == "settled"
            assert permit is not None and permit.status == "consumed"
            assert permit.response_status == response.status_code
        if self._failure is not None:
            raise self._failure


def build_state(
    *,
    status_code: int = 200,
    failure: Exception | None = None,
    request_key: str = REQUEST_KEY,
) -> tuple[
    JournalBoundLiveAttemptCoordinator,
    FirstRequestClaim,
    sessionmaker[Session],
    InspectingFakeSender,
    PersistentAcquisitionSafety,
]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        execution_options={"schema_translate_map": {"ingest": None}},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    approval = G0Approval.model_validate(valid_approval_payload())
    fingerprint = approval_fingerprint(approval)
    with factory.begin() as session:
        run = CrawlRun(
            run_type="journal_bound_attempt_test",
            provider="synthetic",
            status="running",
            config_snapshot={"transport": "fake"},
            requested_by="test",
        )
        session.add(run)
        session.flush()
        run_id = run.id
    safety = PersistentAcquisitionSafety(factory, approval, run_id)
    safety.initialize(now=NOW)
    claim = FirstRequestSlotService(factory).claim(
        approval_fingerprint=fingerprint,
        run_id=run_id,
        request_key=request_key,
        now=NOW,
    )
    sender = InspectingFakeSender(
        factory,
        status_code=status_code,
        failure=failure,
    )
    coordinator = JournalBoundLiveAttemptCoordinator(
        safety,
        LiveExecutionJournalService(factory),
        sender,
        clock=lambda: NOW,
    )
    return coordinator, claim, factory, sender, safety


def test_canonical_binding_unifies_slot_permit_and_journal_hash() -> None:
    approval = G0Approval.model_validate(valid_approval_payload())
    binding = CanonicalLiveRequestBinding.from_request(
        approval_fingerprint=approval_fingerprint(approval),
        provider_id="pinned_metadata_local_contract",
        request=AcquisitionRequest(entity_type=EntityType.WORK, source_id="42"),
        exact_url="https://metadata.pixiv.test/works/42",
    )
    coordinator, claim, factory, sender, _safety = build_state(
        request_key=binding.request_key
    )

    result = coordinator.execute_binding(claim, binding=binding)

    assert result.state == LiveExecutionState.COMPLETED
    assert len(sender.calls) == 1
    with factory() as session:
        permit = session.scalar(select(AcquisitionRequestPermit))
        journal = session.scalar(select(AcquisitionLiveExecutionJournal))
        assert permit is not None and permit.request_key_hash == binding.binding_hash
        assert journal is not None
        assert journal.request_binding_hash == binding.binding_hash
        assert claim.request_key_hash == binding.binding_hash


def test_success_binds_claim_permit_send_settle_and_completion() -> None:
    coordinator, claim, factory, sender, _safety = build_state()

    result = coordinator.execute(claim, request_key=REQUEST_KEY)

    assert result.state == LiveExecutionState.COMPLETED
    assert result.response_status == 200
    assert result.source_transport_attempted is True
    assert result.network_send_confirmed is None
    assert result.failure_code is None
    assert len(sender.calls) == 1
    with factory() as session:
        permit = session.scalar(select(AcquisitionRequestPermit))
        journal = session.scalar(select(AcquisitionLiveExecutionJournal))
        assert permit is not None and permit.status == "consumed"
        assert permit.response_status == 200
        assert journal is not None and journal.status == "completed"
        assert journal.permit_id == permit.permit_id


def test_response_processor_runs_only_after_settlement_then_completes() -> None:
    coordinator, claim, factory, sender, _safety = build_state()
    processor = InspectingSettledProcessor(factory)

    result = coordinator.execute(
        claim,
        request_key=REQUEST_KEY,
        response_processor=processor,
    )

    assert result.state == LiveExecutionState.COMPLETED
    assert processor.calls == 1
    assert len(sender.calls) == 1


def test_response_processor_failure_is_known_failed_not_indeterminate() -> None:
    coordinator, claim, factory, sender, _safety = build_state()
    processor = InspectingSettledProcessor(
        factory,
        failure=ValueError("synthetic parse detail"),
    )

    result = coordinator.execute(
        claim,
        request_key=REQUEST_KEY,
        response_processor=processor,
    )

    assert result.state == LiveExecutionState.FAILED
    assert result.failure_code == "response_processing_failed"
    assert result.source_transport_attempted is True
    assert processor.calls == 1
    assert len(sender.calls) == 1


def test_non_success_response_consumes_permit_but_fails_journal() -> None:
    coordinator, claim, factory, sender, _safety = build_state(status_code=403)

    result = coordinator.execute(claim, request_key=REQUEST_KEY)

    assert result.state == LiveExecutionState.FAILED
    assert result.response_status == 403
    assert result.failure_code == "non_success_response"
    assert result.source_transport_attempted is True
    assert len(sender.calls) == 1
    with factory() as session:
        permit = session.scalar(select(AcquisitionRequestPermit))
        assert permit is not None and permit.status == "consumed"
        assert permit.response_status == 403


def test_transport_exception_is_indeterminate_and_never_resends() -> None:
    coordinator, claim, factory, sender, _safety = build_state(
        failure=RuntimeError("synthetic transport detail")
    )

    result = coordinator.execute(claim, request_key=REQUEST_KEY)

    assert result.state == LiveExecutionState.INDETERMINATE
    assert result.failure_code == "transport_result_unknown"
    assert result.response_status is None
    assert result.source_transport_attempted is True
    assert len(sender.calls) == 1
    with factory() as session:
        permit = session.scalar(select(AcquisitionRequestPermit))
        assert permit is not None and permit.status == "transport_failed"

    with pytest.raises(JournalBoundAttemptError, match="resend is forbidden"):
        coordinator.execute(claim, request_key=REQUEST_KEY)
    assert len(sender.calls) == 1


def test_invalid_injected_status_is_unknown_effect_and_not_retried() -> None:
    coordinator, claim, factory, sender, _safety = build_state(status_code=700)

    result = coordinator.execute(claim, request_key=REQUEST_KEY)

    assert result.state == LiveExecutionState.INDETERMINATE
    assert result.failure_code == "transport_result_unknown"
    assert len(sender.calls) == 1
    with factory() as session:
        permit = session.scalar(select(AcquisitionRequestPermit))
        assert permit is not None and permit.status == "transport_failed"


def test_request_binding_mismatch_rejects_before_journal_permit_or_sender() -> None:
    coordinator, claim, factory, sender, _safety = build_state()

    with pytest.raises(JournalBoundAttemptError, match="binding"):
        coordinator.execute(claim, request_key="different")

    assert sender.calls == []
    with factory() as session:
        assert session.scalar(select(AcquisitionRequestPermit)) is None
        assert session.scalar(select(AcquisitionLiveExecutionJournal)) is None


def test_permit_authorization_failure_terminalizes_journal_before_send() -> None:
    coordinator, claim, factory, sender, safety = build_state()
    existing = safety.authorize_request(request_key=REQUEST_KEY, now=NOW)

    result = coordinator.execute(claim, request_key=REQUEST_KEY)

    assert result.state == LiveExecutionState.FAILED
    assert result.failure_code == "permit_authorization_failed"
    assert result.permit_id is None
    assert result.source_transport_attempted is False
    assert sender.calls == []
    with factory() as session:
        journal = session.scalar(select(AcquisitionLiveExecutionJournal))
        permit = session.scalar(
            select(AcquisitionRequestPermit).where(
                AcquisitionRequestPermit.permit_id == existing.permit_id
            )
        )
        assert journal is not None and journal.status == "failed"
        assert permit is not None and permit.status == "authorized"


def test_atomic_prepare_rolls_back_permit_and_budgets_when_marker_cannot_bind() -> None:
    _coordinator, claim, factory, sender, safety = build_state()
    journals = LiveExecutionJournalService(factory)
    journal = journals.claim(
        approval_fingerprint=claim.approval_fingerprint,
        run_id=claim.run_id,
        slot_id=claim.slot_id,
        request_binding_hash=claim.request_key_hash,
        now=NOW,
    )

    with pytest.raises(ValueError, match="journal binding"):
        safety.authorize_and_start_live_send(
            journal_id=journal.journal_id + 1000,
            request_key=REQUEST_KEY,
            now=NOW,
        )

    assert sender.calls == []
    assert journals.get(journal.journal_id).state == LiveExecutionState.CLAIMED
    with factory() as session:
        run_budget = session.scalar(select(AcquisitionRunBudget))
        daily = session.scalar(select(AcquisitionDailyBudget))
        assert session.scalar(select(AcquisitionRequestPermit)) is None
        assert run_budget is not None and run_budget.request_count == 0
        assert run_budget.in_flight_count == 0
        assert daily is not None and daily.request_count == 0
