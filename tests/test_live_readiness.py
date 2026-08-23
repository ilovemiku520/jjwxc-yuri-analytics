from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from pixiv_yuri.acquisition.auth import SessionCapability
from pixiv_yuri.acquisition.base import AcquisitionProvider
from pixiv_yuri.acquisition.first_request_slot import FirstRequestClaim
from pixiv_yuri.acquisition.models import AcquisitionRequest, EntityType, RawResponse
from pixiv_yuri.governance.g0 import G0Approval, approval_fingerprint
from pixiv_yuri.governance.launch_review import (
    EXPECTED_MIGRATION_VERSION,
    LaunchReviewResult,
)
from pixiv_yuri.governance.live_readiness import (
    LiveReadinessError,
    LiveReadinessEvidence,
    arm_live_one_request_enablement,
    bind_live_one_request_readiness,
    derive_live_claim_key_hash,
)
from pixiv_yuri.governance.real_request_enablement import (
    ExplicitRealRequestEnablement,
    RealRequestEnablementState,
)
from tests.test_g0_governance import valid_approval_payload

NOW = datetime(2026, 8, 23, tzinfo=UTC)


class ReadinessOnlyProvider(AcquisitionProvider):
    def __init__(self, fingerprint: str, *, live: bool = True) -> None:
        self._fingerprint = fingerprint
        self._live = live
        self.fetch_count = 0

    @property
    def name(self) -> str:
        return "pinned_metadata_local_contract"

    @property
    def external_network_enabled(self) -> bool:
        return self._live

    @property
    def approval_fingerprint(self) -> str:
        return self._fingerprint

    def list_requests(
        self, entity_type: EntityType | None = None
    ) -> tuple[AcquisitionRequest, ...]:
        raise AssertionError("Readiness binder must not list Provider requests.")

    def fetch(self, request: AcquisitionRequest) -> RawResponse:
        self.fetch_count += 1
        raise AssertionError("Readiness binder must never fetch.")


def build_ready_values() -> tuple[
    G0Approval,
    LaunchReviewResult,
    SessionCapability,
    FirstRequestClaim,
    ReadinessOnlyProvider,
    AcquisitionRequest,
]:
    approval = G0Approval.model_validate(valid_approval_payload())
    fingerprint = approval_fingerprint(approval)
    request = AcquisitionRequest(entity_type=EntityType.WORK, source_id="42")
    provider = ReadinessOnlyProvider(fingerprint)
    request_hash = derive_live_claim_key_hash(provider.name, request)
    review = LaunchReviewResult(
        status="passed",
        checked_at=(NOW - timedelta(seconds=2)).isoformat(),
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
    session = SessionCapability(
        established_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=5),
        allowed_age_ratings=frozenset({"all_ages", "r18", "r18g"}),
    )
    claim = FirstRequestClaim(
        slot_id=1,
        approval_fingerprint=fingerprint,
        run_id=42,
        request_key_hash=request_hash,
        claimed_at=NOW - timedelta(seconds=1),
    )
    return approval, review, session, claim, provider, request


def bind_ready() -> tuple[
    LiveReadinessEvidence,
    ExplicitRealRequestEnablement,
    ReadinessOnlyProvider,
]:
    approval, review, session, claim, provider, request = build_ready_values()
    enablement = arm_live_one_request_enablement(
        claim,
        enabled_at=NOW - timedelta(milliseconds=100),
        ttl_seconds=30,
    )
    return (
        bind_live_one_request_readiness(
            approval=approval,
            launch_review=review,
            session_capability=session,
            claim=claim,
            provider=provider,
            request=request,
            enablement=enablement,
            now=NOW,
        ),
        enablement,
        provider,
    )


def test_ready_binding_consumes_enablement_without_listing_or_fetching() -> None:
    evidence, enablement, provider = bind_ready()

    assert evidence.status == "ready"
    assert evidence.planned_requests == 1
    assert evidence.external_network_used is False
    assert evidence.enablement_state == RealRequestEnablementState.CONSUMED
    assert enablement.snapshot(now=NOW).state == RealRequestEnablementState.CONSUMED
    assert provider.fetch_count == 0


def test_launch_review_mismatch_burns_enablement_without_fetch() -> None:
    approval, review, session, claim, provider, request = build_ready_values()
    enablement = arm_live_one_request_enablement(claim, enabled_at=NOW, ttl_seconds=30)

    with pytest.raises(LiveReadinessError) as caught:
        bind_live_one_request_readiness(
            approval=approval,
            launch_review=replace(review, status="blocked", violations=("synthetic",)),
            session_capability=session,
            claim=claim,
            provider=provider,
            request=request,
            enablement=enablement,
            now=NOW,
        )

    assert "launch_review_not_eligible" in caught.value.violations
    assert enablement.snapshot(now=NOW).state != RealRequestEnablementState.ARMED
    assert provider.fetch_count == 0


def test_request_identity_mismatch_rejects_and_burns_enablement() -> None:
    approval, review, session, claim, provider, _request = build_ready_values()
    enablement = arm_live_one_request_enablement(claim, enabled_at=NOW, ttl_seconds=30)
    different = AcquisitionRequest(entity_type=EntityType.WORK, source_id="different")

    with pytest.raises(LiveReadinessError) as caught:
        bind_live_one_request_readiness(
            approval=approval,
            launch_review=review,
            session_capability=session,
            claim=claim,
            provider=provider,
            request=different,
            enablement=enablement,
            now=NOW,
        )

    assert "claim_binding_mismatch" in caught.value.violations
    assert enablement.snapshot(now=NOW).state == RealRequestEnablementState.REJECTED
    assert provider.fetch_count == 0


def test_inactive_session_and_provider_approval_mismatch_burn_enablement() -> None:
    approval, review, session, claim, provider, request = build_ready_values()
    inactive = session.model_copy(update={"expires_at": NOW})
    mismatched_provider = ReadinessOnlyProvider("c" * 64)
    enablement = arm_live_one_request_enablement(claim, enabled_at=NOW, ttl_seconds=30)

    with pytest.raises(LiveReadinessError) as caught:
        bind_live_one_request_readiness(
            approval=approval,
            launch_review=review,
            session_capability=inactive,
            claim=claim,
            provider=mismatched_provider,
            request=request,
            enablement=enablement,
            now=NOW,
        )

    assert "session_inactive" in caught.value.violations
    assert "provider_approval_mismatch" in caught.value.violations
    assert enablement.snapshot(now=NOW).state != RealRequestEnablementState.ARMED
    assert provider.fetch_count == 0
    assert mismatched_provider.fetch_count == 0


def test_stale_review_is_rejected_and_default_disabled_state_stays_denied() -> None:
    approval, review, session, claim, provider, request = build_ready_values()
    disabled = ExplicitRealRequestEnablement()

    with pytest.raises(LiveReadinessError) as caught:
        bind_live_one_request_readiness(
            approval=approval,
            launch_review=replace(
                review, checked_at=(NOW - timedelta(minutes=6)).isoformat()
            ),
            session_capability=session,
            claim=claim,
            provider=provider,
            request=request,
            enablement=disabled,
            now=NOW,
        )

    assert "launch_review_stale" in caught.value.violations
    assert disabled.snapshot(now=NOW).state == RealRequestEnablementState.DISABLED
    assert provider.fetch_count == 0


def test_invalid_review_timestamp_still_burns_armed_enablement() -> None:
    approval, review, session, claim, provider, request = build_ready_values()
    enablement = arm_live_one_request_enablement(claim, enabled_at=NOW, ttl_seconds=30)

    with pytest.raises(LiveReadinessError) as caught:
        bind_live_one_request_readiness(
            approval=approval,
            launch_review=replace(review, checked_at="not-a-time"),
            session_capability=session,
            claim=claim,
            provider=provider,
            request=request,
            enablement=enablement,
            now=NOW,
        )

    assert "launch_review_time_invalid" in caught.value.violations
    assert enablement.snapshot(now=NOW).state != RealRequestEnablementState.ARMED
    assert provider.fetch_count == 0
