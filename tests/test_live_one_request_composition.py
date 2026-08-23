from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from pixiv_yuri.acquisition.auth import SessionCapability
from pixiv_yuri.acquisition.base import AcquisitionProvider
from pixiv_yuri.acquisition.first_request_slot import (
    FirstRequestClaim,
    FirstRequestSlotService,
)
from pixiv_yuri.acquisition.live_request_binding import CanonicalLiveRequestBinding
from pixiv_yuri.acquisition.models import AcquisitionRequest, EntityType, RawResponse
from pixiv_yuri.acquisition.persistence_models import (
    AcquisitionFirstRequestSlot,
    AcquisitionRunBudget,
)
from pixiv_yuri.acquisition.runtime_session_lease import AgeRating, RuntimeSessionLease
from pixiv_yuri.governance.g0 import G0Approval, approval_fingerprint
from pixiv_yuri.governance.launch_review import (
    EXPECTED_MIGRATION_VERSION,
    LaunchReviewResult,
)
from pixiv_yuri.governance.live_one_request_composition import (
    JournalBoundRequestExecutor,
    LiveOneRequestCompositionResult,
    run_live_one_request_composition,
)
from pixiv_yuri.governance.source_endpoint_contract import SourceEndpointContract
from pixiv_yuri.ingest.models import CrawlRun
from pixiv_yuri.shared.database import Base
from tests.test_g0_governance import valid_approval_payload
from tests.test_source_endpoint_contract import build_contract

NOW = datetime(2026, 8, 23, tzinfo=UTC)
PHRASE = "CONFIRM-LIVE-ONE-001122AABBCC"
REQUEST = AcquisitionRequest(entity_type=EntityType.WORK, source_id="42")


class SyntheticLiveProvider(AcquisitionProvider):
    def __init__(
        self,
        fingerprint: str,
        trace: list[str],
        runtime_session_lease: RuntimeSessionLease,
        *,
        fail: bool = False,
        status_code: int = 200,
    ) -> None:
        self._fingerprint = fingerprint
        self._trace = trace
        self._fail = fail
        self._status_code = status_code
        self._runtime_session_lease = runtime_session_lease
        self.fetch_count = 0

    @property
    def name(self) -> str:
        return "synthetic_live_provider"

    @property
    def approval_fingerprint(self) -> str:
        return self._fingerprint

    @property
    def external_network_enabled(self) -> bool:
        return True

    @property
    def runtime_session_lease(self) -> RuntimeSessionLease:
        return self._runtime_session_lease

    def list_requests(
        self, entity_type: EntityType | None = None
    ) -> tuple[AcquisitionRequest, ...]:
        self._trace.append("precheck")
        return (REQUEST,) if entity_type in {None, EntityType.WORK} else ()

    def plan_live_request_binding(
        self, request: AcquisitionRequest
    ) -> CanonicalLiveRequestBinding:
        return CanonicalLiveRequestBinding.from_request(
            approval_fingerprint=self._fingerprint,
            provider_id=self.name,
            request=request,
            exact_url=f"https://metadata.pixiv.test/works/{request.source_id}",
        )

    def fetch(self, request: AcquisitionRequest) -> RawResponse:
        self._trace.append("execute")
        self.fetch_count += 1
        if self._fail:
            raise RuntimeError("synthetic provider failure must not escape")
        return RawResponse(
            provider=self.name,
            entity_type=request.entity_type,
            source_id=request.source_id,
            observed_at=NOW,
            status_code=self._status_code,
            content_type="application/json",
            body=b'{"work_id":"42"}',
        )


class RecordingSlotService:
    def __init__(self, delegate: FirstRequestSlotService, trace: list[str]) -> None:
        self._delegate = delegate
        self._trace = trace

    def claim(
        self,
        *,
        approval_fingerprint: str,
        run_id: int,
        request_key: str,
        now: datetime | None = None,
    ) -> FirstRequestClaim:
        self._trace.append("claim")
        return self._delegate.claim(
            approval_fingerprint=approval_fingerprint,
            run_id=run_id,
            request_key=request_key,
            now=now,
        )

    def complete(
        self, claim: FirstRequestClaim, *, now: datetime | None = None
    ) -> None:
        self._trace.append("complete")
        self._delegate.complete(claim, now=now)

    def fail(self, claim: FirstRequestClaim, *, now: datetime | None = None) -> None:
        self._trace.append("fail")
        self._delegate.fail(claim, now=now)


class SyntheticJournalBoundExecutor(JournalBoundRequestExecutor):
    """Offline test double; production uses the durable journal-bound executor."""

    def execute(
        self,
        *,
        provider: AcquisitionProvider,
        request: AcquisitionRequest,
        claim: FirstRequestClaim,
        binding: CanonicalLiveRequestBinding,
    ) -> RawResponse:
        assert claim.request_key_hash == binding.binding_hash
        return provider.fetch(request)


def build_values(
    *,
    provider_failure: bool = False,
    status_code: int = 200,
    allowed_ratings: frozenset[AgeRating] | None = None,
) -> tuple[
    SyntheticLiveProvider,
    G0Approval,
    LaunchReviewResult,
    SessionCapability,
    RuntimeSessionLease,
    SourceEndpointContract,
    RecordingSlotService,
    sessionmaker[Session],
    int,
    list[str],
]:
    trace: list[str] = []
    approval = G0Approval.model_validate(valid_approval_payload())
    fingerprint = approval_fingerprint(approval)
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        execution_options={"schema_translate_map": {"ingest": None}},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory.begin() as session:
        run = CrawlRun(
            run_type="live_one_request_composition_test",
            provider="synthetic_live_provider",
            status="running",
            config_snapshot={"network": "injected_synthetic_only"},
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
        run_id = run.id

    review = LaunchReviewResult(
        status="passed",
        checked_at=(NOW - timedelta(seconds=1)).isoformat(),
        approval_fingerprint=fingerprint,
        approval_expires_at=approval.expires_at.isoformat(),
        migration_version=EXPECTED_MIGRATION_VERSION,
        postgres_ready=True,
        planned_request_cap=1,
        approved_request_cap=approval.traffic_limits.per_run_request_cap,
        active_permit_count=0,
        first_request_slot_count=0,
        stopped_run_count=0,
        external_network_used=False,
        violations=(),
    )
    ratings = allowed_ratings or frozenset({"all_ages", "r18", "r18g"})
    session_capability = SessionCapability(
        established_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=5),
        allowed_age_ratings=ratings,
    )
    runtime_session_lease = RuntimeSessionLease(
        established_at=session_capability.established_at,
        expires_at=session_capability.expires_at,
        allowed_age_ratings=ratings,
    )
    endpoint_contract = build_contract(
        approval,
        origin="https://metadata.pixiv.test",
    )
    provider = SyntheticLiveProvider(
        fingerprint,
        trace,
        runtime_session_lease,
        fail=provider_failure,
        status_code=status_code,
    )
    slots = RecordingSlotService(FirstRequestSlotService(factory), trace)
    return (
        provider,
        approval,
        review,
        session_capability,
        runtime_session_lease,
        endpoint_contract,
        slots,
        factory,
        run_id,
        trace,
    )


def run_composition(
    *,
    provider_failure: bool = False,
    status_code: int = 200,
    allowed_ratings: frozenset[AgeRating] | None = None,
    answer: str = PHRASE,
) -> tuple[
    LiveOneRequestCompositionResult,
    SyntheticLiveProvider,
    sessionmaker[Session],
    list[str],
    list[str],
]:
    (
        provider,
        approval,
        review,
        capability,
        runtime_session_lease,
        endpoint_contract,
        slots,
        factory,
        run_id,
        trace,
    ) = build_values(
        provider_failure=provider_failure,
        status_code=status_code,
        allowed_ratings=allowed_ratings,
    )
    prompts: list[str] = []

    def reader(prompt: str) -> str:
        trace.append("confirm")
        prompts.append(prompt)
        return answer

    result = run_live_one_request_composition(
        provider=provider,
        approval=approval,
        launch_review=review,
        session_capability=capability,
        runtime_session_lease=runtime_session_lease,
        endpoint_contract=endpoint_contract,
        journal_bound_executor=SyntheticJournalBoundExecutor(),
        slot_service=slots,
        run_id=run_id,
        reader=reader,
        phrase_factory=lambda: PHRASE,
        now=lambda: NOW,
    )
    return result, provider, factory, trace, prompts


def test_success_uses_live_prompt_dual_guard_and_permanent_completion() -> None:
    result, provider, factory, trace, prompts = run_composition()

    assert result.status == "passed"
    assert result.slot_status == "completed"
    assert result.attempted_requests == result.completed_requests == 1
    assert result.source_transport_attempted is True
    assert result.network_send_confirmed is None
    assert provider.fetch_count == 1
    assert trace == ["precheck", "confirm", "claim", "execute", "complete"]
    assert len(prompts) == 1
    prompt = prompts[0].lower()
    assert "live request" in prompt
    assert "contact the reviewed source exactly once" in prompt
    assert "dry-run" not in prompt
    with factory() as session:
        slot = session.scalar(select(AcquisitionFirstRequestSlot))
        assert slot is not None and slot.status == "completed"
        binding = provider.plan_live_request_binding(REQUEST)
        assert slot.request_key_hash == binding.binding_hash

    for forbidden in ("readiness", "enablement", "receipt", "capability"):
        assert not hasattr(result, forbidden)


def test_failed_live_confirmation_never_claims_or_executes() -> None:
    result, provider, factory, trace, _prompts = run_composition(answer="wrong")

    assert result.violations == ("confirmation_failed",)
    assert trace == ["precheck", "confirm"]
    assert provider.fetch_count == 0
    with factory() as session:
        assert session.scalar(select(AcquisitionFirstRequestSlot)) is None


def test_detectable_readiness_failure_blocks_before_confirmation_or_claim() -> None:
    result, provider, factory, trace, _prompts = run_composition(
        allowed_ratings=frozenset({"all_ages"})
    )

    assert result.violations == ("session_rating_scope_mismatch",)
    assert result.slot_status == "not_claimed"
    assert trace == ["precheck"]
    assert provider.fetch_count == 0
    with factory() as session:
        slot = session.scalar(select(AcquisitionFirstRequestSlot))
        assert slot is None


def test_equal_scope_different_runtime_lease_is_rejected_before_confirmation() -> None:
    (
        provider,
        approval,
        review,
        capability,
        _provider_lease,
        endpoint_contract,
        slots,
        factory,
        run_id,
        trace,
    ) = build_values()
    substituted_lease = RuntimeSessionLease(
        established_at=capability.established_at,
        expires_at=capability.expires_at,
        allowed_age_ratings=capability.allowed_age_ratings,
    )

    result = run_live_one_request_composition(
        provider=provider,
        approval=approval,
        launch_review=review,
        session_capability=capability,
        runtime_session_lease=substituted_lease,
        endpoint_contract=endpoint_contract,
        journal_bound_executor=SyntheticJournalBoundExecutor(),
        slot_service=slots,
        run_id=run_id,
        reader=lambda _: PHRASE,
        phrase_factory=lambda: PHRASE,
        now=lambda: NOW,
    )

    assert result.violations == ("runtime_session_lease_mismatch",)
    assert trace == ["precheck"]
    assert provider.fetch_count == 0
    with factory() as session:
        assert session.scalar(select(AcquisitionFirstRequestSlot)) is None


def test_provider_failure_executes_once_and_permanently_fails_claim() -> None:
    result, provider, factory, trace, _prompts = run_composition(provider_failure=True)

    assert result.status == "blocked"
    assert result.violations == ("provider_request_failed",)
    assert result.slot_status == "failed"
    assert result.attempted_requests == 1
    assert result.source_transport_attempted is True
    assert result.network_send_confirmed is None
    assert provider.fetch_count == 1
    assert trace == ["precheck", "confirm", "claim", "execute", "fail"]
    with factory() as session:
        slot = session.scalar(select(AcquisitionFirstRequestSlot))
        assert slot is not None and slot.status == "failed"


def test_non_success_response_is_attempted_once_and_fails_slot() -> None:
    result, provider, factory, trace, _prompts = run_composition(status_code=403)

    assert result.status == "blocked"
    assert result.violations == ("provider_non_success_response",)
    assert result.slot_status == "failed"
    assert result.attempted_requests == 1
    assert result.completed_requests == 0
    assert result.source_transport_attempted is True
    assert result.network_send_confirmed is None
    assert provider.fetch_count == 1
    assert trace == ["precheck", "confirm", "claim", "execute", "fail"]
    with factory() as session:
        slot = session.scalar(select(AcquisitionFirstRequestSlot))
        assert slot is not None and slot.status == "failed"
