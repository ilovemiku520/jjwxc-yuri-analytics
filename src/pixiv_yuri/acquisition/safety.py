"""Fail-closed request budget and circuit breaker with no network implementation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from threading import Lock

from pixiv_yuri.governance.g0 import G0Approval, approval_fingerprint


class StopReason(StrEnum):
    """Auditable reasons that prevent further acquisition requests."""

    APPROVAL_INACTIVE = "approval_inactive"
    PER_RUN_REQUEST_CAP = "per_run_request_cap"
    DAILY_REQUEST_CAP = "daily_request_cap"
    DAILY_COST_CAP = "daily_cost_cap"
    MONTHLY_COST_CAP = "monthly_cost_cap"
    REPEATED_403 = "repeated_403"
    REPEATED_429 = "repeated_429"
    SCHEMA_DRIFT = "schema_drift"
    MANUAL = "manual"


class AcquisitionStoppedError(RuntimeError):
    """Raised before a request when the controller is stopped or a cap is reached."""

    def __init__(self, reason: StopReason) -> None:
        self.reason = reason
        super().__init__(f"Acquisition stopped: {reason.value}")


class AcquisitionDeferredError(RuntimeError):
    """Raised before transport when all approved concurrency slots are occupied."""


class DuplicateRequestPermitError(RuntimeError):
    """Raised before transport when a logical request was already authorized."""


@dataclass(frozen=True, slots=True)
class RequestPermit:
    """One bounded authorization that a future Provider must consume exactly once."""

    sequence: int
    approval_fingerprint: str
    authorized_at: datetime
    estimated_cost: Decimal


@dataclass(frozen=True, slots=True)
class SafetySnapshot:
    """Non-secret state suitable for logs and future persistence."""

    approval_fingerprint: str
    budget_day: date
    run_requests: int
    daily_requests: int
    daily_estimated_cost: Decimal
    in_flight_requests: int
    consecutive_403: int
    consecutive_429: int
    stopped: bool
    stop_reason: StopReason | None


class AcquisitionSafetyController:
    """Authorize requests atomically and stop closed on approved conditions."""

    def __init__(self, approval: G0Approval, *, now: datetime | None = None) -> None:
        created_at = _aware_utc(now or datetime.now(UTC))
        self._approval = approval
        self._approval_fingerprint = approval_fingerprint(approval)
        self._budget_day = created_at.date()
        self._run_requests = 0
        self._daily_requests = 0
        self._daily_estimated_cost = Decimal("0")
        self._in_flight: set[int] = set()
        self._consecutive_403 = 0
        self._consecutive_429 = 0
        self._stop_reason: StopReason | None = None
        self._lock = Lock()

    def authorize_request(
        self,
        *,
        now: datetime | None = None,
        estimated_cost: Decimal = Decimal("0"),
    ) -> RequestPermit:
        """Reserve request and estimated-cost budget before any transport call."""
        checked_at = _aware_utc(now or datetime.now(UTC))
        if estimated_cost < 0:
            raise ValueError("Estimated request cost cannot be negative.")

        with self._lock:
            self._roll_daily_window(checked_at.date())
            self._ensure_active_approval(checked_at)
            self._raise_if_stopped()

            traffic = self._approval.traffic_limits
            if len(self._in_flight) >= traffic.concurrency:
                raise AcquisitionDeferredError("Approved concurrency limit reached.")
            if self._run_requests >= traffic.per_run_request_cap:
                self._stop_and_raise(StopReason.PER_RUN_REQUEST_CAP)
            if self._daily_requests >= traffic.daily_request_cap:
                self._stop_and_raise(StopReason.DAILY_REQUEST_CAP)

            projected_cost = self._daily_estimated_cost + estimated_cost
            cost_cap = Decimal(str(self._approval.cost_limits.daily_cap))
            if projected_cost > cost_cap:
                self._stop_and_raise(StopReason.DAILY_COST_CAP)

            self._run_requests += 1
            self._daily_requests += 1
            self._daily_estimated_cost = projected_cost
            self._in_flight.add(self._run_requests)
            return RequestPermit(
                sequence=self._run_requests,
                approval_fingerprint=self._approval_fingerprint,
                authorized_at=checked_at,
                estimated_cost=estimated_cost,
            )

    def record_response(self, permit: RequestPermit, status_code: int) -> None:
        """Update consecutive denial/rate-limit breakers after a permitted request."""
        with self._lock:
            self._consume_permit(permit)
            if status_code == 403:
                self._consecutive_403 += 1
                self._consecutive_429 = 0
                if self._consecutive_403 >= 2:
                    self._stop_reason = StopReason.REPEATED_403
                return
            if status_code == 429:
                self._consecutive_429 += 1
                self._consecutive_403 = 0
                if self._consecutive_429 >= 2:
                    self._stop_reason = StopReason.REPEATED_429
                return
            self._consecutive_403 = 0
            self._consecutive_429 = 0

    def record_transport_failure(self, permit: RequestPermit) -> None:
        """Release one concurrency slot after a transport error without hiding it."""
        with self._lock:
            self._consume_permit(permit)

    def signal_schema_drift(self) -> None:
        """Stop before parsing any structure outside the approved schema policy."""
        with self._lock:
            self._stop_reason = StopReason.SCHEMA_DRIFT

    def stop_manually(self) -> None:
        """Apply the operator kill switch."""
        with self._lock:
            self._stop_reason = StopReason.MANUAL

    def snapshot(self) -> SafetySnapshot:
        """Return one immutable audit snapshot."""
        with self._lock:
            return SafetySnapshot(
                approval_fingerprint=self._approval_fingerprint,
                budget_day=self._budget_day,
                run_requests=self._run_requests,
                daily_requests=self._daily_requests,
                daily_estimated_cost=self._daily_estimated_cost,
                in_flight_requests=len(self._in_flight),
                consecutive_403=self._consecutive_403,
                consecutive_429=self._consecutive_429,
                stopped=self._stop_reason is not None,
                stop_reason=self._stop_reason,
            )

    def _ensure_active_approval(self, checked_at: datetime) -> None:
        if not (self._approval.approved_at <= checked_at < self._approval.expires_at):
            self._stop_and_raise(StopReason.APPROVAL_INACTIVE)

    def _raise_if_stopped(self) -> None:
        if self._stop_reason is not None:
            raise AcquisitionStoppedError(self._stop_reason)

    def _stop_and_raise(self, reason: StopReason) -> None:
        self._stop_reason = reason
        raise AcquisitionStoppedError(reason)

    def _roll_daily_window(self, checked_day: date) -> None:
        if checked_day == self._budget_day:
            return
        if checked_day < self._budget_day:
            self._stop_and_raise(StopReason.APPROVAL_INACTIVE)
        self._budget_day = checked_day
        self._daily_requests = 0
        self._daily_estimated_cost = Decimal("0")
        self._consecutive_403 = 0
        self._consecutive_429 = 0


    def _consume_permit(self, permit: RequestPermit) -> None:
        if permit.approval_fingerprint != self._approval_fingerprint:
            raise ValueError("Request permit belongs to a different G0 approval.")
        if permit.sequence not in self._in_flight:
            raise ValueError("Request permit is unknown or was already consumed.")
        self._in_flight.remove(permit.sequence)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Safety-controller timestamps must include a timezone.")
    return value.astimezone(UTC)
