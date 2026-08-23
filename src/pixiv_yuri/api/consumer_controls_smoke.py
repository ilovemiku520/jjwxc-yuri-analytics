"""Container smoke test for shared consumer rate limiting and minimized audit state."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select

from pixiv_yuri.api.operations import ConsumerAccessEvent
from pixiv_yuri.api.persistence_models import (
    ApiConsumerAccessAudit,
    ApiConsumerRateLimitWindow,
)
from pixiv_yuri.api.postgres_operations import (
    PostgresConsumerAccessAuditor,
    PostgresFixedWindowConsumerRateLimiter,
)
from pixiv_yuri.shared.database import build_engine, build_session_factory

_WORKERS = 8
_MAX_REQUESTS = 3
_FORBIDDEN_AUDIT_COLUMNS = frozenset(
    {
        "authorization",
        "cookie",
        "email",
        "headers",
        "password",
        "query",
        "raw_path",
        "subject",
        "token",
    }
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def run_smoke(*, database_url: str) -> dict[str, object]:
    engine = build_engine(database_url)
    if engine.dialect.name != "postgresql":
        raise RuntimeError("consumer-control smoke requires PostgreSQL")
    factory = build_session_factory(engine)
    run_token = uuid.uuid4().hex
    request_prefix = f"security-smoke-{run_token[:12]}"
    consumer_key = hashlib.sha256(run_token.encode("ascii")).hexdigest()
    limiter = PostgresFixedWindowConsumerRateLimiter(
        factory,
        max_requests=_MAX_REQUESTS,
        window_seconds=60,
        max_consumers=100_000,
    )
    auditor = PostgresConsumerAccessAuditor(factory, retention_days=30)

    expired_time = datetime.now(UTC) - timedelta(days=31)
    auditor.record(
        ConsumerAccessEvent(
            occurred_at=expired_time.isoformat(),
            request_id=f"{request_prefix}-expired",
            consumer_key=consumer_key,
            method="GET",
            route_template="/api/v1/operations/security-status",
            status_code=200,
            auth_outcome="private_boundary",
        )
    )
    expired_audit_rows_purged = auditor.purge_expired()

    def exercise(worker: int) -> bool:
        decision = limiter.check(consumer_key=consumer_key, now=0.0)
        auditor.record(
            ConsumerAccessEvent(
                occurred_at=datetime.now(UTC).isoformat(),
                request_id=f"{request_prefix}-{worker}",
                consumer_key=consumer_key,
                method="GET",
                route_template="/api/v1/operations/security-status",
                status_code=200 if decision.allowed else 429,
                auth_outcome="private_boundary" if decision.allowed else "rate_limited",
            )
        )
        return decision.allowed

    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        decisions = list(pool.map(exercise, range(_WORKERS)))

    with factory() as session:
        persisted_count = session.scalar(
            select(ApiConsumerRateLimitWindow.request_count).where(
                ApiConsumerRateLimitWindow.consumer_key == consumer_key
            )
        )
        audit_count = session.scalar(
            select(func.count())
            .select_from(ApiConsumerAccessAudit)
            .where(ApiConsumerAccessAudit.request_id.like(f"{request_prefix}-%"))
        )

    audit_columns = set(ApiConsumerAccessAudit.__table__.columns.keys())
    forbidden_columns_absent = not bool(audit_columns & _FORBIDDEN_AUDIT_COLUMNS)
    allowed = sum(decisions)
    denied = _WORKERS - allowed
    passed = (
        allowed == _MAX_REQUESTS
        and denied == _WORKERS - _MAX_REQUESTS
        and persisted_count == _MAX_REQUESTS
        and audit_count == _WORKERS
        and expired_audit_rows_purged == 1
        and forbidden_columns_absent
    )
    report: dict[str, object] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "passed" if passed else "failed",
        "backend": "postgresql",
        "concurrent_workers": _WORKERS,
        "maximum_requests": _MAX_REQUESTS,
        "allowed": allowed,
        "denied": denied,
        "persisted_request_count": persisted_count,
        "minimized_audit_events": audit_count,
        "expired_audit_rows_purged": expired_audit_rows_purged,
        "forbidden_audit_columns_absent": forbidden_columns_absent,
        "raw_consumer_identity_reported": False,
        "network_used": False,
    }
    engine.dispose()
    if not passed:
        raise RuntimeError(f"consumer-control smoke failed: {report}")
    return report


def main() -> int:
    args = _parser().parse_args()
    database_url = os.environ.get("PYURI_DATABASE_URL")
    if not database_url:
        raise RuntimeError("PYURI_DATABASE_URL is required")
    report = run_smoke(database_url=database_url)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
