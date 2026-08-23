"""Offline-only orchestration for one confirmed, durably claimed sample."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from pixiv_yuri.acquisition.base import AcquisitionProvider
from pixiv_yuri.acquisition.first_request_slot import (
    FirstRequestAlreadyClaimedError,
    FirstRequestSlotError,
    FirstRequestSlotService,
)
from pixiv_yuri.governance.g0 import G0Approval, approval_fingerprint
from pixiv_yuri.governance.one_request_executor import (
    confirm_one_request_capability,
    execute_exactly_one_provider_request,
)


@dataclass(frozen=True, slots=True)
class FirstSampleDryRunResult:
    """Payload-free evidence for a fake-transport first-sample rehearsal."""

    status: str
    confirmation_status: str
    execution_status: str
    slot_status: str
    planned_requests: int
    attempted_requests: int
    completed_requests: int
    external_network_used: bool
    violations: tuple[str, ...]


def run_first_sample_dry_run(
    provider: AcquisitionProvider,
    approval: G0Approval,
    slot_service: FirstRequestSlotService,
    *,
    run_id: int,
    ttl_seconds: int,
    reader: Callable[[str], str],
    phrase_factory: Callable[[], str] | None = None,
    now: Callable[[], datetime] | None = None,
) -> FirstSampleDryRunResult:
    """Confirm, claim, execute once, and permanently resolve the offline slot."""
    clock = now or (lambda: datetime.now(UTC))
    requests = provider.list_requests()
    fingerprint = approval_fingerprint(approval)
    if provider.external_network_enabled:
        return _blocked(len(requests), "external_network_not_allowed")
    if provider.approval_fingerprint != fingerprint:
        return _blocked(len(requests), "provider_approval_binding_mismatch")
    if len(requests) != 1:
        return _blocked(len(requests), "planned_requests_must_equal_one")

    confirmation, capability = confirm_one_request_capability(
        provider,
        requests,
        ttl_seconds=ttl_seconds,
        reader=reader,
        phrase_factory=phrase_factory,
        now=clock,
    )
    if capability is None:
        return _blocked(
            1,
            "confirmation_not_eligible",
            confirmation_status=confirmation.status,
        )

    request = requests[0]
    request_key = (
        f"first-sample:{provider.name}:{request.entity_type.value}:{request.source_id}"
    )
    try:
        claim = slot_service.claim(
            approval_fingerprint=fingerprint,
            run_id=run_id,
            request_key=request_key,
            now=clock(),
        )
    except FirstRequestAlreadyClaimedError:
        return _blocked(1, "first_request_slot_already_spent", confirmation_status="passed")
    except FirstRequestSlotError:
        return _blocked(1, "first_request_slot_unavailable", confirmation_status="passed")

    execution = execute_exactly_one_provider_request(
        capability,
        provider,
        requests,
        now=clock(),
    )
    try:
        if execution.status == "passed":
            slot_service.complete(claim, now=clock())
            slot_status = "completed"
        else:
            slot_service.fail(claim, now=clock())
            slot_status = "failed"
    except FirstRequestSlotError:
        return FirstSampleDryRunResult(
            status="blocked",
            confirmation_status="passed",
            execution_status=execution.status,
            slot_status="claimed",
            planned_requests=1,
            attempted_requests=execution.attempted_requests,
            completed_requests=0,
            external_network_used=False,
            violations=("first_request_slot_resolution_failed",),
        )

    return FirstSampleDryRunResult(
        status=execution.status,
        confirmation_status="passed",
        execution_status=execution.status,
        slot_status=slot_status,
        planned_requests=1,
        attempted_requests=execution.attempted_requests,
        completed_requests=execution.completed_requests,
        external_network_used=False,
        violations=execution.violations,
    )


def _blocked(
    planned_requests: int,
    violation: str,
    *,
    confirmation_status: str = "not_started",
) -> FirstSampleDryRunResult:
    return FirstSampleDryRunResult(
        status="blocked",
        confirmation_status=confirmation_status,
        execution_status="not_started",
        slot_status="not_claimed",
        planned_requests=planned_requests,
        attempted_requests=0,
        completed_requests=0,
        external_network_used=False,
        violations=(violation,),
    )
