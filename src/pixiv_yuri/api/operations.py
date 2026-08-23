"""Operational boundaries for bounded read-API access and observability."""

from __future__ import annotations

import hashlib
import logging
import math
import threading
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal, Protocol

AuthOutcome = Literal[
    "not_applicable",
    "private_boundary",
    "authenticated",
    "authentication_failed",
    "scope_denied",
    "authorization_unavailable",
    "rate_limited",
    "rate_limit_unavailable",
]


def consumer_subject_digest(subject: str) -> str:
    """Reduce a verified subject to a domain-separated, log-safe stable digest."""
    return hashlib.sha256(f"pyuri-consumer-v1\0{subject}".encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class ApiPerformancePolicy:
    """Advisory request-duration budgets; overruns are observed, not retried."""

    default_budget_ms: int = 750
    health_budget_ms: int = 250
    route_budgets_ms: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        values = (self.default_budget_ms, self.health_budget_ms, *self.route_budgets_ms.values())
        if any(value < 1 or value > 60_000 for value in values):
            raise ValueError("API performance budgets must be between 1 and 60000 ms")
        if any(not route.startswith("/") for route in self.route_budgets_ms):
            raise ValueError("route performance budgets require absolute route templates")

    def budget_for(self, route_template: str) -> int:
        """Return the narrowest configured duration budget for one route template."""
        configured = self.route_budgets_ms.get(route_template)
        if configured is not None:
            return configured
        if route_template.startswith("/health/"):
            return self.health_budget_ms
        return self.default_budget_ms


@dataclass(frozen=True, slots=True)
class ApiRequestObservation:
    """Payload-free performance observation safe for metrics or structured logs."""

    request_id: str
    method: str
    route_template: str
    status_code: int
    duration_ms: float
    budget_ms: int
    budget_exceeded: bool
    auth_outcome: AuthOutcome


class ApiRequestObserver(Protocol):
    """Adapter for metrics backends without coupling the API to one vendor."""

    def observe(self, observation: ApiRequestObservation) -> None:
        """Record one minimized request-duration observation."""
        ...


class StructuredLogRequestObserver:
    """Default payload-free observer using the project's redacting JSON logger."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger("pixiv_yuri.api.performance")

    def observe(self, observation: ApiRequestObservation) -> None:
        self._logger.info(
            "api_request_completed",
            extra={
                "context": {
                    "method": observation.method,
                    "route_template": observation.route_template,
                    "status_code": observation.status_code,
                    "duration_ms": round(observation.duration_ms, 3),
                    "budget_ms": observation.budget_ms,
                    "budget_exceeded": observation.budget_exceeded,
                    "auth_outcome": observation.auth_outcome,
                }
            },
        )


@dataclass(frozen=True, slots=True)
class ConsumerRateLimitDecision:
    """One fixed-window authorization decision without consumer material."""

    allowed: bool
    retry_after_seconds: int = 0


class ConsumerRateLimiter(Protocol):
    """Provider-neutral per-consumer rate-limit backend."""

    def check(self, *, consumer_key: str, now: float) -> ConsumerRateLimitDecision:
        """Consume one request slot or return a bounded retry delay."""
        ...


class ConsumerRateLimitCapacityError(RuntimeError):
    """Raised when a process-local limiter cannot safely track another subject."""


class FixedWindowConsumerRateLimiter:
    """Thread-safe bounded limiter for one-process or offline deployments.

    Multi-worker/public deployments must inject a reviewed shared-store adapter instead.
    """

    def __init__(
        self,
        *,
        max_requests: int = 120,
        window_seconds: int = 60,
        max_consumers: int = 10_000,
    ) -> None:
        if max_requests < 1 or max_requests > 100_000:
            raise ValueError("max_requests must be between 1 and 100000")
        if window_seconds < 1 or window_seconds > 86_400:
            raise ValueError("window_seconds must be between 1 and 86400")
        if max_consumers < 1 or max_consumers > 1_000_000:
            raise ValueError("max_consumers must be between 1 and 1000000")
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._max_consumers = max_consumers
        self._requests: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, *, consumer_key: str, now: float) -> ConsumerRateLimitDecision:
        if len(consumer_key) != 64:
            raise ValueError("consumer_key must be a SHA-256 digest")
        cutoff = now - self._window_seconds
        with self._lock:
            bucket = self._requests.get(consumer_key)
            if bucket is None:
                self._prune_empty(cutoff)
                if len(self._requests) >= self._max_consumers:
                    raise ConsumerRateLimitCapacityError("consumer rate-limit capacity reached")
                bucket = deque()
                self._requests[consumer_key] = bucket
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= self._max_requests:
                retry_after = max(1, math.ceil(bucket[0] + self._window_seconds - now))
                return ConsumerRateLimitDecision(False, retry_after)
            bucket.append(now)
            return ConsumerRateLimitDecision(True)

    def _prune_empty(self, cutoff: float) -> None:
        expired: list[str] = []
        for consumer_key, bucket in self._requests.items():
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if not bucket:
                expired.append(consumer_key)
        for consumer_key in expired:
            del self._requests[consumer_key]


@dataclass(frozen=True, slots=True)
class ConsumerAccessEvent:
    """Minimized access evidence; raw subjects and request targets are excluded."""

    occurred_at: str
    request_id: str
    consumer_key: str | None
    method: str
    route_template: str
    status_code: int
    auth_outcome: AuthOutcome


class ConsumerAccessAuditor(Protocol):
    """Adapter for a future durable, retention-governed access-audit sink."""

    def record(self, event: ConsumerAccessEvent) -> None:
        """Record one minimized access decision."""
        ...


class StructuredLogConsumerAccessAuditor:
    """Default private-deployment audit sink with no credential or query capture."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger("pixiv_yuri.api.access")

    def record(self, event: ConsumerAccessEvent) -> None:
        self._logger.info(
            "consumer_access_decision",
            extra={
                "context": {
                    "occurred_at": event.occurred_at,
                    "consumer_key": event.consumer_key,
                    "method": event.method,
                    "route_template": event.route_template,
                    "status_code": event.status_code,
                    "auth_outcome": event.auth_outcome,
                }
            },
        )


def utc_now() -> datetime:
    """Return a timezone-aware wall-clock value for access evidence."""
    return datetime.now(UTC)


MonotonicClock = Callable[[], float]
UtcClock = Callable[[], datetime]
