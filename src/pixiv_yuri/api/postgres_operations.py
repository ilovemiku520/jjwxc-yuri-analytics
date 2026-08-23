"""PostgreSQL-backed consumer controls with minimized durable state."""

from __future__ import annotations

import math
import re
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session, sessionmaker

from pixiv_yuri.api.operations import (
    AuthOutcome,
    ConsumerAccessEvent,
    ConsumerRateLimitCapacityError,
    ConsumerRateLimitDecision,
)
from pixiv_yuri.api.persistence_models import (
    ApiConsumerAccessAudit,
    ApiConsumerRateLimitWindow,
)

UtcClock = Callable[[], datetime]
_CONSUMER_KEY_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_METHOD_PATTERN = re.compile(r"^[A-Z]{1,16}$")
_AUTH_OUTCOMES: frozenset[AuthOutcome] = frozenset(
    {
        "not_applicable",
        "private_boundary",
        "authenticated",
        "authentication_failed",
        "scope_denied",
        "authorization_unavailable",
        "rate_limited",
        "rate_limit_unavailable",
    }
)
_NEW_CONSUMER_ADVISORY_LOCK = 0x50595552494C494D


class PostgresFixedWindowConsumerRateLimiter:
    """Cross-process fixed-window limiter using row and advisory transaction locks."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        max_requests: int = 120,
        window_seconds: int = 60,
        max_consumers: int = 100_000,
        utc_clock: UtcClock = lambda: datetime.now(UTC),
    ) -> None:
        if max_requests < 1 or max_requests > 100_000:
            raise ValueError("max_requests must be between 1 and 100000")
        if window_seconds < 1 or window_seconds > 86_400:
            raise ValueError("window_seconds must be between 1 and 86400")
        if max_consumers < 1 or max_consumers > 1_000_000:
            raise ValueError("max_consumers must be between 1 and 1000000")
        self._factory = session_factory
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._max_consumers = max_consumers
        self._utc_clock = utc_clock
        self._fallback_lock = threading.Lock()

    def check(self, *, consumer_key: str, now: float) -> ConsumerRateLimitDecision:
        """Atomically consume one shared slot; the protocol clock is intentionally ignored."""
        del now
        _validate_consumer_key(consumer_key)
        current = _aware_utc(self._utc_clock())
        window_start = _window_start(current, self._window_seconds)
        with self._factory() as session:
            if session.get_bind().dialect.name == "postgresql":
                decision = self._check_in_transaction(
                    session, consumer_key, current, window_start, use_advisory_lock=True
                )
                session.commit()
            else:
                with self._fallback_lock:
                    decision = self._check_in_transaction(
                        session, consumer_key, current, window_start, use_advisory_lock=False
                    )
                    session.commit()
            return decision

    def _check_in_transaction(
        self,
        session: Session,
        consumer_key: str,
        current: datetime,
        window_start: datetime,
        *,
        use_advisory_lock: bool,
    ) -> ConsumerRateLimitDecision:
        statement = select(ApiConsumerRateLimitWindow).where(
            ApiConsumerRateLimitWindow.consumer_key == consumer_key
        )
        if use_advisory_lock:
            statement = statement.with_for_update()
        row = session.scalar(statement)
        if row is None and use_advisory_lock:
            session.execute(select(func.pg_advisory_xact_lock(_NEW_CONSUMER_ADVISORY_LOCK)))
            row = session.scalar(statement)
        if row is None:
            count = session.scalar(select(func.count()).select_from(ApiConsumerRateLimitWindow))
            if int(count or 0) >= self._max_consumers:
                raise ConsumerRateLimitCapacityError("consumer rate-limit capacity reached")
            session.add(
                ApiConsumerRateLimitWindow(
                    consumer_key=consumer_key,
                    window_started_at=window_start,
                    request_count=1,
                    updated_at=current,
                )
            )
            return ConsumerRateLimitDecision(True)

        persisted_start = _persisted_utc(row.window_started_at)
        if persisted_start != window_start:
            row.window_started_at = window_start
            row.request_count = 1
            row.updated_at = current
            return ConsumerRateLimitDecision(True)
        if row.request_count >= self._max_requests:
            retry_at = persisted_start + timedelta(seconds=self._window_seconds)
            retry_after = max(1, math.ceil((retry_at - current).total_seconds()))
            return ConsumerRateLimitDecision(False, retry_after)
        row.request_count += 1
        row.updated_at = current
        return ConsumerRateLimitDecision(True)


class PostgresConsumerAccessAuditor:
    """Append one validated, minimized access decision with explicit retention."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        retention_days: int = 30,
    ) -> None:
        if retention_days < 1 or retention_days > 365:
            raise ValueError("retention_days must be between 1 and 365")
        self._factory = session_factory
        self._retention_days = retention_days

    def record(self, event: ConsumerAccessEvent) -> None:
        occurred_at = _parse_event_time(event.occurred_at)
        _validate_event(event)
        with self._factory.begin() as session:
            session.add(
                ApiConsumerAccessAudit(
                    occurred_at=occurred_at,
                    retention_until=occurred_at + timedelta(days=self._retention_days),
                    request_id=event.request_id,
                    consumer_key=event.consumer_key,
                    method=event.method,
                    route_template=event.route_template,
                    status_code=event.status_code,
                    auth_outcome=event.auth_outcome,
                )
            )

    def purge_expired(self, *, now: datetime | None = None) -> int:
        """Delete only audit decisions whose explicit retention deadline has elapsed."""
        cutoff = _aware_utc(now or datetime.now(UTC))
        with self._factory.begin() as session:
            result = session.execute(
                delete(ApiConsumerAccessAudit).where(
                    ApiConsumerAccessAudit.retention_until <= cutoff
                )
            )
            if not isinstance(result, CursorResult):
                raise RuntimeError("audit retention purge did not return a cursor result")
            return int(result.rowcount or 0)


def _validate_consumer_key(value: str) -> None:
    if _CONSUMER_KEY_PATTERN.fullmatch(value) is None:
        raise ValueError("consumer_key must be a lowercase SHA-256 digest")


def _validate_event(event: ConsumerAccessEvent) -> None:
    if _REQUEST_ID_PATTERN.fullmatch(event.request_id) is None:
        raise ValueError("request_id is invalid")
    if event.consumer_key is not None:
        _validate_consumer_key(event.consumer_key)
    if _METHOD_PATTERN.fullmatch(event.method) is None:
        raise ValueError("method is invalid")
    if (
        not event.route_template.startswith("/api/v1")
        or len(event.route_template) > 255
        or "?" in event.route_template
        or "#" in event.route_template
        or any(ord(character) < 32 or ord(character) == 127 for character in event.route_template)
    ):
        raise ValueError("route_template is invalid")
    if event.status_code < 100 or event.status_code > 599:
        raise ValueError("status_code is invalid")
    if event.auth_outcome not in _AUTH_OUTCOMES:
        raise ValueError("auth_outcome is invalid")


def _parse_event_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("occurred_at is invalid") from exc
    return _aware_utc(parsed)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC)


def _persisted_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _window_start(value: datetime, window_seconds: int) -> datetime:
    epoch = int(value.timestamp())
    return datetime.fromtimestamp(epoch - (epoch % window_seconds), tz=UTC)
