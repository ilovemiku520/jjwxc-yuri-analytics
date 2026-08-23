from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from pixiv_yuri.api.operations import (
    ConsumerAccessEvent,
    ConsumerRateLimitCapacityError,
)
from pixiv_yuri.api.persistence_models import (
    ApiConsumerAccessAudit,
    ApiConsumerRateLimitWindow,
)
from pixiv_yuri.api.postgres_operations import (
    PostgresConsumerAccessAuditor,
    PostgresFixedWindowConsumerRateLimiter,
)
from pixiv_yuri.shared.database import Base


class _Clock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


def _factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        execution_options={"schema_translate_map": {"ingest": None}},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def test_shared_limiter_enforces_window_rollover_and_consumer_capacity() -> None:
    factory = _factory()
    clock = _Clock(datetime(2026, 8, 23, 0, 0, 10, tzinfo=UTC))
    limiter = PostgresFixedWindowConsumerRateLimiter(
        factory,
        max_requests=2,
        window_seconds=60,
        max_consumers=1,
        utc_clock=clock,
    )
    key = "a" * 64

    assert limiter.check(consumer_key=key, now=1).allowed
    assert limiter.check(consumer_key=key, now=2).allowed
    denied = limiter.check(consumer_key=key, now=3)
    assert not denied.allowed
    assert denied.retry_after_seconds == 50
    with pytest.raises(ConsumerRateLimitCapacityError):
        limiter.check(consumer_key="b" * 64, now=4)

    clock.value += timedelta(seconds=60)
    assert limiter.check(consumer_key=key, now=5).allowed
    with factory() as session:
        row = session.get(ApiConsumerRateLimitWindow, key)
        assert row is not None
        assert row.request_count == 1


def test_shared_limiter_serializes_threads_and_rejects_invalid_digest() -> None:
    factory = _factory()
    limiter = PostgresFixedWindowConsumerRateLimiter(
        factory,
        max_requests=4,
        utc_clock=lambda: datetime(2026, 8, 23, tzinfo=UTC),
    )
    key = "c" * 64
    with ThreadPoolExecutor(max_workers=8) as pool:
        decisions = list(
            pool.map(lambda index: limiter.check(consumer_key=key, now=float(index)), range(8))
        )

    assert sum(decision.allowed for decision in decisions) == 4
    with factory() as session:
        row = session.get(ApiConsumerRateLimitWindow, key)
        assert row is not None
        assert row.request_count == 4
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        limiter.check(consumer_key="not-a-digest", now=0)


def test_durable_auditor_persists_only_minimized_retention_bounded_fields() -> None:
    factory = _factory()
    auditor = PostgresConsumerAccessAuditor(factory, retention_days=30)
    occurred_at = datetime(2026, 8, 23, tzinfo=UTC)
    event = ConsumerAccessEvent(
        occurred_at=occurred_at.isoformat(),
        request_id="request-1",
        consumer_key="d" * 64,
        method="GET",
        route_template="/api/v1/works/{work_id}",
        status_code=200,
        auth_outcome="authenticated",
    )

    auditor.record(event)

    assert auditor.purge_expired(now=occurred_at + timedelta(days=29)) == 0

    with factory() as session:
        row = session.scalar(select(ApiConsumerAccessAudit))
        assert row is not None
        assert row.retention_until.replace(tzinfo=UTC) == occurred_at + timedelta(days=30)
        columns = {column.name for column in ApiConsumerAccessAudit.__table__.columns}
        for forbidden in (
            "subject",
            "query",
            "path_value",
            "header",
            "cookie",
            "token",
            "authorization",
        ):
            assert forbidden not in columns

    assert auditor.purge_expired(now=occurred_at + timedelta(days=31)) == 1
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(ApiConsumerAccessAudit)) == 0


def test_durable_auditor_rejects_unminimized_or_invalid_events_without_write() -> None:
    factory = _factory()
    auditor = PostgresConsumerAccessAuditor(factory)
    invalid = ConsumerAccessEvent(
        occurred_at=datetime(2026, 8, 23, tzinfo=UTC).isoformat(),
        request_id="request-2",
        consumer_key=None,
        method="GET",
        route_template="/api/v1/works/secret-value?token=secret",
        status_code=200,
        auth_outcome="private_boundary",
    )

    with pytest.raises(ValueError, match="route_template"):
        auditor.record(invalid)
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(ApiConsumerAccessAudit)) == 0
