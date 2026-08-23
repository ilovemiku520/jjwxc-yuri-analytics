"""Deterministic local gate for one anonymous-public request plan.

This module deliberately has no HTTP client, opener, credential supplier, or
response sender.  It reserves a reviewed path-only plan and enforces the
contract's initial budget and delay boundary before a future executor exists.
"""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from pixiv_yuri.governance.anonymous_public_contract import (
    AnonymousPublicSourceContract,
    render_anonymous_public_url,
)

AnonymousPublicStopReason = Literal[
    "forbidden_403",
    "rate_limited_429",
    "challenge_or_login",
    "schema_drift",
]


@dataclass(frozen=True, slots=True)
class AnonymousPublicRequestPlan:
    """A non-authorizing request description with fixed safe headers."""

    source_id: str
    url: str
    method: Literal["GET"]
    headers: tuple[tuple[str, str], ...]
    reserved_at: datetime


class AnonymousPublicGateError(RuntimeError):
    """Fixed, payload-free rejection from the local request gate."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"Anonymous public request gate rejected: {reason}")


class AnonymousPublicRequestGate:
    """Reserve one reviewed public request without performing I/O."""

    def __init__(
        self,
        contract: AnonymousPublicSourceContract,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._contract = contract
        self._clock = clock or (lambda: datetime.now(UTC))
        self._lock = threading.Lock()
        self._reservation_times: deque[datetime] = deque()
        self._reservation_count = 0
        self._active_plan: AnonymousPublicRequestPlan | None = None
        self._stopped_reason: AnonymousPublicStopReason | None = None

    @property
    def reservation_count(self) -> int:
        """Return the number of committed request reservations."""
        with self._lock:
            return self._reservation_count

    @property
    def active(self) -> bool:
        """Return whether a plan still needs a local completion/abort mark."""
        with self._lock:
            return self._active_plan is not None

    @property
    def stopped_reason(self) -> AnonymousPublicStopReason | None:
        """Return a terminal source stop, if one has been signalled."""
        with self._lock:
            return self._stopped_reason

    def reserve(
        self,
        source_id: str,
        *,
        now: datetime | None = None,
    ) -> AnonymousPublicRequestPlan:
        """Reserve one path-only plan; this method never sends it."""
        checked_at = _aware_utc(now or self._clock())
        with self._lock:
            if self._stopped_reason is not None:
                raise AnonymousPublicGateError(self._stopped_reason)
            if self._active_plan is not None:
                raise AnonymousPublicGateError("concurrency_limit")
            if self._reservation_times and checked_at - self._reservation_times[-1] < timedelta(
                seconds=self._contract.min_request_interval_seconds
            ):
                raise AnonymousPublicGateError("minimum_interval")
            while self._reservation_times and checked_at - self._reservation_times[0] >= timedelta(
                minutes=1
            ):
                self._reservation_times.popleft()
            if len(self._reservation_times) >= self._contract.requests_per_minute:
                raise AnonymousPublicGateError("requests_per_minute")
            if self._reservation_count >= self._contract.initial_request_cap:
                raise AnonymousPublicGateError("initial_request_cap")
            plan = AnonymousPublicRequestPlan(
                source_id=source_id,
                url=render_anonymous_public_url(self._contract, source_id),
                method="GET",
                headers=(
                    ("Accept", self._contract.accept_content_type),
                    ("User-Agent", "pyuri-anonymous-public-metadata/1"),
                ),
                reserved_at=checked_at,
            )
            self._reservation_count += 1
            self._reservation_times.append(checked_at)
            self._active_plan = plan
            return plan

    def complete(self, plan: AnonymousPublicRequestPlan) -> None:
        """Mark one local plan complete without changing its consumed budget."""
        with self._lock:
            if self._active_plan is not plan:
                raise AnonymousPublicGateError("plan_mismatch")
            self._active_plan = None

    def abort(self, plan: AnonymousPublicRequestPlan) -> None:
        """Release an unexecuted plan; the one-use budget remains consumed."""
        self.complete(plan)

    def signal_stop(self, reason: AnonymousPublicStopReason) -> None:
        """Permanently stop subsequent plans on 403/429/challenge/schema drift."""
        with self._lock:
            if self._stopped_reason is None:
                self._stopped_reason = reason


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise AnonymousPublicGateError("invalid_clock")
    return value.astimezone(UTC)

