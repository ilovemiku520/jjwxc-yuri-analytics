"""Dependency-injected composition root for one doubly-guarded live request."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import NoReturn, Protocol

from pixiv_yuri.acquisition.auth import SessionCapability, SessionCapabilityError
from pixiv_yuri.acquisition.base import AcquisitionProvider
from pixiv_yuri.acquisition.first_request_slot import (
    FirstRequestAlreadyClaimedError,
    FirstRequestClaim,
    FirstRequestSlotError,
)
from pixiv_yuri.acquisition.live_request_binding import CanonicalLiveRequestBinding
from pixiv_yuri.acquisition.models import AcquisitionRequest, EntityType, RawResponse
from pixiv_yuri.acquisition.runtime_session_lease import (
    RuntimeSessionLease,
    RuntimeSessionLeaseError,
    require_same_runtime_session_lease,
)
from pixiv_yuri.governance.g0 import G0Approval, approval_fingerprint
from pixiv_yuri.governance.launch_review import (
    EXPECTED_MIGRATION_VERSION,
    LaunchReviewResult,
)
from pixiv_yuri.governance.live_readiness import (
    MAX_REVIEW_AGE,
    arm_live_one_request_enablement,
    bind_live_one_request_readiness,
)
from pixiv_yuri.governance.one_request_executor import (
    confirm_live_one_request_capability,
    execute_exactly_one_provider_request,
)
from pixiv_yuri.governance.reviewed_endpoint_binding import (
    ReviewedEndpointRequestEvidence,
    bind_reviewed_endpoint_request,
)
from pixiv_yuri.governance.source_endpoint_contract import SourceEndpointContract

_LIVE_CAPABILITY_ISSUER = object()
_PROXY_BIND_ISSUER = object()


class SlotService(Protocol):
    """Persistent first-slot operations required by the composition root."""

    def claim(
        self,
        *,
        approval_fingerprint: str,
        run_id: int,
        request_key: str,
        now: datetime | None = None,
    ) -> FirstRequestClaim: ...

    def complete(
        self, claim: FirstRequestClaim, *, now: datetime | None = None
    ) -> None: ...

    def fail(self, claim: FirstRequestClaim, *, now: datetime | None = None) -> None: ...


class JournalBoundRequestExecutor(Protocol):
    """Only execution port accepted after both operator capabilities are consumed."""

    def execute(
        self,
        *,
        provider: AcquisitionProvider,
        request: AcquisitionRequest,
        claim: FirstRequestClaim,
        binding: CanonicalLiveRequestBinding,
    ) -> RawResponse: ...


class _LiveCapabilityUnavailableError(RuntimeError):
    """Safe internal error raised before delegation to a live Provider."""


class _LiveExecutionCapability:
    """Opaque second capability issued only after successful readiness binding."""

    __slots__ = (
        "_approval_fingerprint",
        "_binding_hash",
        "_consumed",
        "_expires_at",
        "_endpoint_contract_fingerprint",
        "_lock",
        "_provider",
        "_request_key",
        "_run_id",
        "_runtime_session_lease",
    )

    def __init__(
        self,
        *,
        provider: AcquisitionProvider,
        request: AcquisitionRequest,
        claim: FirstRequestClaim,
        runtime_session_lease: RuntimeSessionLease,
        request_binding: CanonicalLiveRequestBinding,
        endpoint_evidence: ReviewedEndpointRequestEvidence,
        expires_at: datetime,
        _issuer: object,
    ) -> None:
        if _issuer is not _LIVE_CAPABILITY_ISSUER:
            raise _LiveCapabilityUnavailableError(
                "Live capability must come from the composition root."
            )
        self._provider = provider
        self._request_key = request.key
        self._approval_fingerprint = claim.approval_fingerprint
        self._binding_hash = request_binding.binding_hash
        self._endpoint_contract_fingerprint = endpoint_evidence.contract_fingerprint
        self._run_id = claim.run_id
        self._runtime_session_lease = runtime_session_lease
        self._expires_at = _aware_utc(expires_at)
        self._consumed = False
        self._lock = threading.Lock()

    def consume(
        self,
        provider: AcquisitionProvider,
        request: AcquisitionRequest,
        claim: FirstRequestClaim,
        *,
        now: datetime,
    ) -> None:
        """Burn before checking time and exact provider/request/claim bindings."""
        checked_at = _aware_utc(now)
        with self._lock:
            if self._consumed:
                raise _LiveCapabilityUnavailableError("Live capability was already consumed.")
            self._consumed = True
        if checked_at >= self._expires_at:
            raise _LiveCapabilityUnavailableError("Live capability is inactive.")
        if (
            provider is not self._provider
            or request.key != self._request_key
            or claim.approval_fingerprint != self._approval_fingerprint
            or claim.run_id != self._run_id
            or claim.request_key_hash != self._binding_hash
        ):
            raise _LiveCapabilityUnavailableError("Live capability binding mismatch.")
        planned_binding = provider.plan_live_request_binding(request)
        if planned_binding is None or planned_binding.binding_hash != self._binding_hash:
            raise _LiveCapabilityUnavailableError("Live request binding mismatch.")
        try:
            provider_lease = provider.runtime_session_lease
            if provider_lease is None:
                raise RuntimeSessionLeaseError("Runtime session lease is unavailable.")
            require_same_runtime_session_lease(
                self._runtime_session_lease,
                provider_lease,
            )
        except (RuntimeSessionLeaseError, TypeError):
            raise _LiveCapabilityUnavailableError(
                "Live capability session binding mismatch."
            ) from None

    def __reduce__(self) -> NoReturn:
        raise TypeError("Live execution capabilities cannot be serialized.")


class _GuardedLiveProviderProxy(AcquisitionProvider):
    """Appear offline to the existing executor; delegate only with a live capability."""

    def __init__(
        self,
        provider: AcquisitionProvider,
        request: AcquisitionRequest,
        claim_getter: Callable[[], FirstRequestClaim],
        binding: CanonicalLiveRequestBinding,
        journal_bound_executor: JournalBoundRequestExecutor,
        clock: Callable[[], datetime],
    ) -> None:
        self._provider = provider
        self._request = request
        self._claim_getter = claim_getter
        self._binding = binding
        self._journal_bound_executor = journal_bound_executor
        self._clock = clock
        self._live_capability: _LiveExecutionCapability | None = None

    @property
    def name(self) -> str:
        return self._provider.name

    @property
    def approval_fingerprint(self) -> str | None:
        return self._provider.approval_fingerprint

    @property
    def external_network_enabled(self) -> bool:
        """The proxy itself has no unguarded network path."""
        return False

    def list_requests(
        self, entity_type: EntityType | None = None
    ) -> tuple[AcquisitionRequest, ...]:
        return (
            (self._request,)
            if entity_type is None or entity_type == self._request.entity_type
            else ()
        )

    def fetch(self, request: AcquisitionRequest) -> RawResponse:
        capability = self._live_capability
        if capability is None:
            raise _LiveCapabilityUnavailableError("Guarded live proxy is not armed.")
        capability.consume(
            self._provider,
            request,
            self._claim_getter(),
            now=self._clock(),
        )
        return self._journal_bound_executor.execute(
            provider=self._provider,
            request=request,
            claim=self._claim_getter(),
            binding=self._binding,
        )

    def bind_live_capability(
        self, capability: _LiveExecutionCapability, *, _issuer: object
    ) -> None:
        if _issuer is not _PROXY_BIND_ISSUER or self._live_capability is not None:
            raise _LiveCapabilityUnavailableError("Guarded live proxy cannot be armed.")
        self._live_capability = capability


@dataclass(frozen=True, slots=True)
class LiveOneRequestCompositionResult:
    """Payload-free terminal evidence; this result is never an authorization."""

    status: str
    confirmation_status: str
    slot_status: str
    execution_status: str
    planned_requests: int
    attempted_requests: int
    completed_requests: int
    source_transport_attempted: bool
    network_send_confirmed: None
    violations: tuple[str, ...]


def run_live_one_request_composition(
    *,
    provider: AcquisitionProvider,
    approval: G0Approval,
    launch_review: LaunchReviewResult,
    session_capability: SessionCapability,
    runtime_session_lease: RuntimeSessionLease,
    endpoint_contract: SourceEndpointContract,
    journal_bound_executor: JournalBoundRequestExecutor,
    slot_service: SlotService,
    run_id: int,
    reader: Callable[[str], str],
    confirmation_ttl_seconds: int = 60,
    enablement_ttl_seconds: int = 30,
    phrase_factory: Callable[[], str] | None = None,
    now: Callable[[], datetime] | None = None,
) -> LiveOneRequestCompositionResult:
    """Confirm, claim, bind readiness, execute once, and permanently resolve.

    The serializable launch review, enablement configuration/receipt, and
    readiness evidence never enter the executor. The existing opaque operator
    capability and a private live capability are both consumed before the
    injected Provider can fetch.
    """
    clock = now or (lambda: datetime.now(UTC))
    try:
        checked_at = _aware_utc(clock())
        requests = provider.list_requests()
        request_binding = (
            provider.plan_live_request_binding(requests[0])
            if len(requests) == 1
            else None
        )
    except Exception:
        return _blocked(0, "not_started", "not_claimed", ("precheck_failed",))
    precheck = _precheck(
        provider,
        approval,
        launch_review,
        session_capability,
        runtime_session_lease,
        request_binding,
        endpoint_contract,
        requests,
        run_id,
        checked_at,
    )
    if precheck:
        return _blocked(len(requests), "not_started", "not_claimed", precheck)

    request = requests[0]
    assert request_binding is not None
    claim_holder: list[FirstRequestClaim] = []
    proxy = _GuardedLiveProviderProxy(
        provider,
        request,
        lambda: claim_holder[0],
        request_binding,
        journal_bound_executor,
        clock,
    )
    try:
        confirmation, operator_capability = confirm_live_one_request_capability(
            proxy,
            (request,),
            ttl_seconds=confirmation_ttl_seconds,
            reader=reader,
            phrase_factory=phrase_factory,
            now=clock,
        )
    except Exception:
        return _blocked(
            1,
            "blocked",
            "not_claimed",
            ("confirmation_unavailable",),
        )
    if operator_capability is None:
        return _blocked(1, confirmation.status, "not_claimed", ("confirmation_failed",))

    fingerprint = approval_fingerprint(approval)
    try:
        claim = slot_service.claim(
            approval_fingerprint=fingerprint,
            run_id=run_id,
            request_key=request_binding.request_key,
            now=clock(),
        )
        claim_holder.append(claim)
    except FirstRequestAlreadyClaimedError:
        return _blocked(1, "passed", "not_claimed", ("first_request_slot_spent",))
    except FirstRequestSlotError:
        return _blocked(1, "passed", "not_claimed", ("first_request_slot_unavailable",))
    except Exception:
        return _blocked(1, "passed", "not_claimed", ("first_request_slot_unavailable",))

    try:
        enablement = arm_live_one_request_enablement(
            claim,
            enabled_at=clock(),
            ttl_seconds=enablement_ttl_seconds,
        )
        bind_live_one_request_readiness(
            approval=approval,
            launch_review=launch_review,
            session_capability=session_capability,
            claim=claim,
            provider=provider,
            request=request,
            enablement=enablement,
            request_binding=request_binding,
            now=clock(),
        )
        endpoint_evidence = bind_reviewed_endpoint_request(
            endpoint_contract,
            approval,
            request_binding,
            now=clock(),
        )
        live_capability = _LiveExecutionCapability(
            provider=provider,
            request=request,
            claim=claim,
            runtime_session_lease=runtime_session_lease,
            request_binding=request_binding,
            endpoint_evidence=endpoint_evidence,
            expires_at=min(
                operator_capability.expires_at,
                session_capability.expires_at,
                runtime_session_lease.expires_at,
                approval.expires_at,
            ),
            _issuer=_LIVE_CAPABILITY_ISSUER,
        )
        proxy.bind_live_capability(live_capability, _issuer=_PROXY_BIND_ISSUER)
    except Exception:
        return _fail_claim(
            slot_service,
            claim,
            clock,
            confirmation_status="passed",
            violation="readiness_failed",
        )

    try:
        execution = execute_exactly_one_provider_request(
            operator_capability,
            proxy,
            (request,),
            now=clock(),
        )
    except Exception:
        return _fail_claim(
            slot_service,
            claim,
            clock,
            confirmation_status="passed",
            violation="executor_failed",
        )

    terminal = "completed" if execution.status == "passed" else "failed"
    try:
        if terminal == "completed":
            slot_service.complete(claim, now=clock())
        else:
            slot_service.fail(claim, now=clock())
    except Exception:
        return LiveOneRequestCompositionResult(
            status="blocked",
            confirmation_status="passed",
            slot_status="claimed",
            execution_status=execution.status,
            planned_requests=1,
            attempted_requests=execution.attempted_requests,
            completed_requests=0,
            source_transport_attempted=execution.attempted_requests > 0,
            network_send_confirmed=None,
            violations=("first_request_slot_resolution_failed",),
        )

    return LiveOneRequestCompositionResult(
        status=execution.status,
        confirmation_status="passed",
        slot_status=terminal,
        execution_status=execution.status,
        planned_requests=1,
        attempted_requests=execution.attempted_requests,
        completed_requests=execution.completed_requests,
        source_transport_attempted=execution.attempted_requests > 0,
        network_send_confirmed=None,
        violations=execution.violations,
    )


def _precheck(
    provider: AcquisitionProvider,
    approval: G0Approval,
    launch_review: LaunchReviewResult,
    session_capability: SessionCapability,
    runtime_session_lease: RuntimeSessionLease,
    request_binding: CanonicalLiveRequestBinding | None,
    endpoint_contract: SourceEndpointContract,
    requests: tuple[AcquisitionRequest, ...],
    run_id: int,
    checked_at: datetime,
) -> tuple[str, ...]:
    violations: list[str] = []
    fingerprint = approval_fingerprint(approval)
    if len(requests) != 1:
        violations.append("planned_requests_must_equal_one")
    if not provider.external_network_enabled:
        violations.append("provider_not_live")
    if provider.approval_fingerprint != fingerprint:
        violations.append("provider_approval_mismatch")
    if request_binding is None:
        violations.append("canonical_request_binding_unavailable")
    elif (
        request_binding.approval_fingerprint != fingerprint
        or request_binding.provider_id != provider.name
        or len(requests) != 1
        or request_binding.entity_type != requests[0].entity_type
        or request_binding.source_id != requests[0].source_id
    ):
        violations.append("canonical_request_binding_mismatch")
    else:
        try:
            bind_reviewed_endpoint_request(
                endpoint_contract,
                approval,
                request_binding,
                now=checked_at,
            )
        except ValueError:
            violations.append("reviewed_endpoint_binding_mismatch")
    if run_id < 1:
        violations.append("run_id_invalid")
    if not approval.approved_at <= checked_at < approval.expires_at:
        violations.append("approval_inactive")
    if (
        launch_review.status != "passed"
        or launch_review.violations
        or launch_review.approval_fingerprint != fingerprint
        or not launch_review.postgres_ready
        or launch_review.migration_version != EXPECTED_MIGRATION_VERSION
        or launch_review.planned_request_cap != 1
        or launch_review.first_request_slot_count != 0
        or launch_review.active_permit_count != 0
        or launch_review.stopped_run_count != 0
        or launch_review.external_network_used
    ):
        violations.append("launch_review_not_eligible")
    try:
        review_checked_at = _aware_utc(datetime.fromisoformat(launch_review.checked_at))
        review_expires_at = _aware_utc(
            datetime.fromisoformat(launch_review.approval_expires_at)
        )
    except (TypeError, ValueError):
        violations.append("launch_review_time_invalid")
    else:
        if not review_checked_at <= checked_at <= review_checked_at + MAX_REVIEW_AGE:
            violations.append("launch_review_stale")
        if review_expires_at != approval.expires_at.astimezone(UTC):
            violations.append("launch_review_expiry_mismatch")
    try:
        session_capability.ensure_active(checked_at)
    except (SessionCapabilityError, ValueError):
        violations.append("session_inactive")
    if session_capability.content_visibility != approval.source_scope.content_visibility:
        violations.append("session_visibility_mismatch")
    if not approval.source_scope.allowed_age_ratings.issubset(
        session_capability.allowed_age_ratings
    ):
        violations.append("session_rating_scope_mismatch")
    try:
        runtime_session_lease.ensure_active(now=checked_at)
        provider_lease = provider.runtime_session_lease
        if provider_lease is None:
            raise RuntimeSessionLeaseError("Runtime session lease is unavailable.")
        require_same_runtime_session_lease(runtime_session_lease, provider_lease)
    except (RuntimeSessionLeaseError, ValueError):
        violations.append("runtime_session_lease_mismatch")
    if (
        runtime_session_lease.content_visibility
        != session_capability.content_visibility
        or runtime_session_lease.allowed_age_ratings
        != session_capability.allowed_age_ratings
    ):
        violations.append("runtime_session_scope_mismatch")
    return tuple(dict.fromkeys(violations))


def _fail_claim(
    slot_service: SlotService,
    claim: FirstRequestClaim,
    clock: Callable[[], datetime],
    *,
    confirmation_status: str,
    violation: str,
) -> LiveOneRequestCompositionResult:
    try:
        slot_service.fail(claim, now=clock())
    except Exception:
        slot_status = "claimed"
        violations: tuple[str, ...] = (
            violation,
            "first_request_slot_resolution_failed",
        )
    else:
        slot_status = "failed"
        violations = (violation,)
    return LiveOneRequestCompositionResult(
        status="blocked",
        confirmation_status=confirmation_status,
        slot_status=slot_status,
        execution_status="not_started",
        planned_requests=1,
        attempted_requests=0,
        completed_requests=0,
        source_transport_attempted=False,
        network_send_confirmed=None,
        violations=violations,
    )


def _blocked(
    planned_requests: int,
    confirmation_status: str,
    slot_status: str,
    violations: tuple[str, ...],
) -> LiveOneRequestCompositionResult:
    return LiveOneRequestCompositionResult(
        status="blocked",
        confirmation_status=confirmation_status,
        slot_status=slot_status,
        execution_status="not_started",
        planned_requests=planned_requests,
        attempted_requests=0,
        completed_requests=0,
        source_transport_attempted=False,
        network_send_confirmed=None,
        violations=violations,
    )


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Composition timestamps must include a timezone.")
    return value.astimezone(UTC)
