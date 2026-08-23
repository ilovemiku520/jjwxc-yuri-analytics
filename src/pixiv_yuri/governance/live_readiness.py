"""Pure readiness binding for one already-claimed live request."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256

from pixiv_yuri.acquisition.auth import SessionCapability, SessionCapabilityError
from pixiv_yuri.acquisition.base import AcquisitionProvider
from pixiv_yuri.acquisition.first_request_slot import FirstRequestClaim
from pixiv_yuri.acquisition.live_request_binding import CanonicalLiveRequestBinding
from pixiv_yuri.acquisition.models import AcquisitionRequest
from pixiv_yuri.governance.g0 import G0Approval, approval_fingerprint
from pixiv_yuri.governance.launch_review import (
    EXPECTED_MIGRATION_VERSION,
    LaunchReviewResult,
)
from pixiv_yuri.governance.real_request_enablement import (
    EXPLICIT_ACKNOWLEDGEMENT,
    ExplicitRealRequestEnablement,
    RealRequestDeniedError,
    RealRequestEnablementConfig,
    RealRequestEnablementState,
)

MAX_REVIEW_AGE = timedelta(minutes=5)
MIN_ENABLEMENT_TTL_SECONDS = 5
MAX_ENABLEMENT_TTL_SECONDS = 120


class LiveReadinessError(RuntimeError):
    """Safe readiness rejection whose codes disclose no request identity."""

    def __init__(self, violations: tuple[str, ...]) -> None:
        self.violations = violations
        super().__init__("Live one-request readiness rejected.")


@dataclass(frozen=True, slots=True)
class LiveReadinessEvidence:
    """Non-authorizing audit evidence; it cannot initiate a request.

    This value and the enablement receipt are deliberately not accepted by any
    transport. A same-stack opaque confirmation capability remains mandatory.
    """

    status: str
    planned_requests: int
    approval_fingerprint: str
    run_id: int
    request_key_hash: str
    enablement_state: RealRequestEnablementState
    checked_at: datetime
    external_network_used: bool


def derive_live_claim_key(provider_name: str, request: AcquisitionRequest) -> str:
    """Return the transient canonical key that FirstRequestSlotService must hash."""
    if not provider_name or len(provider_name) > 100:
        raise ValueError("Provider name must contain between 1 and 100 characters.")
    return (
        f"live-one-request:{provider_name}:"
        f"{request.entity_type.value}:{request.source_id}"
    )


def derive_live_claim_key_hash(
    provider_name: str, request: AcquisitionRequest
) -> str:
    """Return the durable non-secret SHA-256 binding for one provider request."""
    logical_key = derive_live_claim_key(provider_name, request)
    return sha256(logical_key.encode("utf-8")).hexdigest()


def arm_live_one_request_enablement(
    claim: FirstRequestClaim,
    *,
    enabled_at: datetime,
    ttl_seconds: int = 60,
) -> ExplicitRealRequestEnablement:
    """Create a short-lived in-memory state bound to an existing claim only."""
    if not MIN_ENABLEMENT_TTL_SECONDS <= ttl_seconds <= MAX_ENABLEMENT_TTL_SECONDS:
        raise ValueError("Live enablement TTL must be between 5 and 120 seconds.")
    checked_at = _aware_utc(enabled_at)
    return ExplicitRealRequestEnablement(
        RealRequestEnablementConfig(
            mode="first_real_request",
            planned_requests=1,
            approval_fingerprint=claim.approval_fingerprint,
            run_id=claim.run_id,
            request_key_hash=claim.request_key_hash,
            enabled_at=checked_at,
            expires_at=checked_at + timedelta(seconds=ttl_seconds),
            acknowledgement=EXPLICIT_ACKNOWLEDGEMENT,
        )
    )


def bind_live_one_request_readiness(
    *,
    approval: G0Approval,
    launch_review: LaunchReviewResult,
    session_capability: SessionCapability,
    claim: FirstRequestClaim,
    provider: AcquisitionProvider,
    request: AcquisitionRequest,
    enablement: ExplicitRealRequestEnablement,
    request_binding: CanonicalLiveRequestBinding | None = None,
    now: datetime,
) -> LiveReadinessEvidence:
    """Validate all non-secret bindings and atomically consume enablement.

    This function never lists or fetches Provider requests, never reads a
    credential, and never creates or updates a persistent first-request claim.
    """
    checked_at = _aware_utc(now)
    fingerprint = approval_fingerprint(approval)
    violations: list[str] = []
    try:
        request_key_hash = (
            request_binding.binding_hash
            if request_binding is not None
            else derive_live_claim_key_hash(provider.name, request)
        )
    except (UnicodeError, ValueError):
        request_key_hash = "0" * 64
        violations.append("provider_request_identity_invalid")
    if request_binding is not None and (
        request_binding.approval_fingerprint != fingerprint
        or request_binding.provider_id != provider.name
        or request_binding.entity_type != request.entity_type
        or request_binding.source_id != request.source_id
    ):
        violations.append("canonical_request_binding_mismatch")

    if not approval.approved_at <= checked_at < approval.expires_at:
        violations.append("approval_inactive")
    if approval.traffic_limits.concurrency != 1:
        violations.append("approval_concurrency_not_one")
    if (
        approval.source_scope.authentication_mode != "user_managed_session"
        or approval.source_scope.content_visibility != "authenticated_public"
    ):
        violations.append("approval_session_scope_mismatch")

    review_checked_at = _try_parse_aware(launch_review.checked_at)
    review_expires_at = _try_parse_aware(launch_review.approval_expires_at)
    if review_checked_at is None or review_expires_at is None:
        violations.append("launch_review_time_invalid")
    if (
        launch_review.status != "passed"
        or launch_review.violations
        or not launch_review.postgres_ready
        or launch_review.migration_version != EXPECTED_MIGRATION_VERSION
        or launch_review.planned_request_cap != 1
        or launch_review.active_permit_count != 0
        or launch_review.first_request_slot_count != 0
        or launch_review.stopped_run_count != 0
        or launch_review.external_network_used
    ):
        violations.append("launch_review_not_eligible")
    if launch_review.approval_fingerprint != fingerprint:
        violations.append("launch_review_approval_mismatch")
    if review_expires_at != approval.expires_at.astimezone(UTC):
        violations.append("launch_review_expiry_mismatch")
    if review_checked_at is None or not (
        review_checked_at <= checked_at <= review_checked_at + MAX_REVIEW_AGE
    ):
        violations.append("launch_review_stale")

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
        claim_time = _aware_utc(claim.claimed_at)
    except ValueError:
        violations.append("claim_time_invalid")
    else:
        if review_checked_at is None or not review_checked_at <= claim_time <= checked_at:
            violations.append("claim_time_mismatch")
    if (
        claim.slot_id < 1
        or claim.run_id < 1
        or claim.approval_fingerprint != fingerprint
        or claim.request_key_hash != request_key_hash
    ):
        violations.append("claim_binding_mismatch")

    if not provider.external_network_enabled:
        violations.append("provider_not_live")
    if provider.approval_fingerprint != fingerprint:
        violations.append("provider_approval_mismatch")

    if violations:
        _burn_enablement(
            enablement,
            approval_fingerprint=fingerprint,
            run_id=claim.run_id,
            request_key_hash=request_key_hash,
            now=checked_at,
        )
        raise LiveReadinessError(tuple(dict.fromkeys(violations)))

    try:
        enablement.consume(
            approval_fingerprint=fingerprint,
            run_id=claim.run_id,
            request_key_hash=request_key_hash,
            now=checked_at,
        )
    except (RealRequestDeniedError, ValueError):
        raise LiveReadinessError(("enablement_unavailable",)) from None

    return LiveReadinessEvidence(
        status="ready",
        planned_requests=1,
        approval_fingerprint=fingerprint,
        run_id=claim.run_id,
        request_key_hash=request_key_hash,
        enablement_state=RealRequestEnablementState.CONSUMED,
        checked_at=checked_at,
        external_network_used=False,
    )


def _burn_enablement(
    enablement: ExplicitRealRequestEnablement,
    *,
    approval_fingerprint: str,
    run_id: int,
    request_key_hash: str,
    now: datetime,
) -> None:
    """Make every armed mismatch terminal without returning authorization."""
    try:
        enablement.consume(
            approval_fingerprint=approval_fingerprint,
            run_id=run_id,
            request_key_hash=request_key_hash,
            now=now,
        )
    except (RealRequestDeniedError, ValueError):
        return


def _try_parse_aware(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
        return _aware_utc(parsed)
    except (TypeError, ValueError):
        return None


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Live readiness timestamps must include a timezone.")
    return value.astimezone(UTC)
