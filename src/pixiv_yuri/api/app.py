"""FastAPI liveness and database-readiness endpoints."""

from __future__ import annotations

import os
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import UTC
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker
from starlette.routing import Match

from pixiv_yuri.api.auth import (
    ANALYTICS_READ_SCOPE,
    ConsumerAuthenticationError,
    ConsumerAuthorizer,
    TrustedHmacProxyAuthorizer,
)
from pixiv_yuri.api.author_analytics import register_author_analytics_routes
from pixiv_yuri.api.catalog_api import register_catalog_routes
from pixiv_yuri.api.detail_api import register_detail_routes
from pixiv_yuri.api.jjwxc_api import register_jjwxc_routes
from pixiv_yuri.api.operations import (
    ApiPerformancePolicy,
    ApiRequestObservation,
    ApiRequestObserver,
    AuthOutcome,
    ConsumerAccessAuditor,
    ConsumerAccessEvent,
    ConsumerRateLimiter,
    MonotonicClock,
    StructuredLogConsumerAccessAuditor,
    StructuredLogRequestObserver,
    UtcClock,
    consumer_subject_digest,
    utc_now,
)
from pixiv_yuri.api.operations_read_api import register_operations_read_routes
from pixiv_yuri.api.postgres_operations import (
    PostgresConsumerAccessAuditor,
    PostgresFixedWindowConsumerRateLimiter,
)
from pixiv_yuri.api.read_api import register_read_routes
from pixiv_yuri.api.tag_analytics import register_tag_analytics_routes
from pixiv_yuri.shared.database import build_engine, build_session_factory
from pixiv_yuri.shared.logging import bind_request_id, reset_request_id

ReadinessProbe = Callable[[], None]
_REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class DatabaseNotConfiguredError(RuntimeError):
    """Raised when readiness has no database target to verify."""


class LivenessResponse(BaseModel):
    """Stable liveness response contract."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["alive"] = "alive"


class ReadinessResponse(BaseModel):
    """Stable readiness response without infrastructure details."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["ready", "not_ready"]
    database: Literal["ready", "not_configured", "unavailable"]


def probe_database() -> None:
    """Run a minimal database query without exposing credentials or errors."""
    database_url = os.getenv("PYURI_DATABASE_URL")
    if not database_url:
        raise DatabaseNotConfiguredError

    engine = build_engine(database_url)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    finally:
        engine.dispose()


def create_app(
    readiness_probe: ReadinessProbe | None = None,
    *,
    session_factory: sessionmaker[Session] | None = None,
    consumer_authorizer: ConsumerAuthorizer | None = None,
    consumer_rate_limiter: ConsumerRateLimiter | None = None,
    consumer_access_auditor: ConsumerAccessAuditor | None = None,
    request_observer: ApiRequestObserver | None = None,
    performance_policy: ApiPerformancePolicy | None = None,
    monotonic_clock: MonotonicClock = time.perf_counter,
    utc_clock: UtcClock = utc_now,
    shared_consumer_controls_enabled: bool | None = None,
    audit_retention_days: int | None = None,
) -> FastAPI:
    """Build the Phase 0 API with an injectable readiness boundary."""
    probe = readiness_probe or probe_database
    application = FastAPI(
        title="JJWXC Yuri Novel Analytics API",
        version="0.1.0",
        description="Read-only JJWXC novel analytics; live collection is disabled by default.",
    )
    controls_enabled = (
        _shared_controls_enabled()
        if shared_consumer_controls_enabled is None
        else shared_consumer_controls_enabled
    )
    retention_days = (
        audit_retention_days
        if audit_retention_days is not None
        else _bounded_env_int(
            "PYURI_API_AUDIT_RETENTION_DAYS", default=30, minimum=1, maximum=365
        )
    )
    if controls_enabled and session_factory is None:
        raise ValueError("shared consumer controls require a database session factory")
    if controls_enabled and consumer_rate_limiter is None:
        assert session_factory is not None
        consumer_rate_limiter = PostgresFixedWindowConsumerRateLimiter(
            session_factory,
            max_requests=_bounded_env_int(
                "PYURI_API_RATE_LIMIT_MAX_REQUESTS",
                default=120,
                minimum=1,
                maximum=100_000,
            ),
            window_seconds=_bounded_env_int(
                "PYURI_API_RATE_LIMIT_WINDOW_SECONDS",
                default=60,
                minimum=1,
                maximum=86_400,
            ),
            max_consumers=_bounded_env_int(
                "PYURI_API_RATE_LIMIT_MAX_CONSUMERS",
                default=100_000,
                minimum=1,
                maximum=1_000_000,
            ),
            utc_clock=utc_clock,
        )
    observer = request_observer or StructuredLogRequestObserver()
    auditor = consumer_access_auditor or (
        PostgresConsumerAccessAuditor(session_factory, retention_days=retention_days)
        if controls_enabled and session_factory is not None
        else StructuredLogConsumerAccessAuditor()
    )
    timing_policy = performance_policy or ApiPerformancePolicy()

    @application.middleware("http")
    async def request_id_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        candidate = request.headers.get(_REQUEST_ID_HEADER, "")
        request_id = candidate if _REQUEST_ID_PATTERN.fullmatch(candidate) else uuid.uuid4().hex
        token = bind_request_id(request_id)
        started = monotonic_clock()
        is_read_api = request.url.path.startswith("/api/v1")
        auth_outcome: AuthOutcome = "private_boundary" if is_read_api else "not_applicable"
        consumer_key: str | None = None
        duration_ms = 0.0
        response_status = status.HTTP_500_INTERNAL_SERVER_ERROR
        response: Response
        try:
            if is_read_api and consumer_authorizer is not None:
                try:
                    identity = consumer_authorizer.authorize(request)
                except ConsumerAuthenticationError:
                    auth_outcome = "authentication_failed"
                    response = JSONResponse(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        content={"detail": "consumer_authentication_required"},
                    )
                except Exception:
                    auth_outcome = "authorization_unavailable"
                    response = JSONResponse(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        content={"detail": "authorization_service_unavailable"},
                    )
                else:
                    consumer_key = consumer_subject_digest(identity.subject)
                    if ANALYTICS_READ_SCOPE not in identity.scopes:
                        auth_outcome = "scope_denied"
                        response = JSONResponse(
                            status_code=status.HTTP_403_FORBIDDEN,
                            content={"detail": "analytics_read_scope_required"},
                        )
                    else:
                        auth_outcome = "authenticated"
                        if consumer_rate_limiter is not None:
                            try:
                                rate_decision = consumer_rate_limiter.check(
                                    consumer_key=consumer_key,
                                    now=started,
                                )
                            except Exception:
                                auth_outcome = "rate_limit_unavailable"
                                response = JSONResponse(
                                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                                    content={"detail": "rate_limit_service_unavailable"},
                                )
                            else:
                                if not rate_decision.allowed:
                                    auth_outcome = "rate_limited"
                                    response = JSONResponse(
                                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                                        content={"detail": "consumer_rate_limit_exceeded"},
                                        headers={
                                            "Retry-After": str(
                                                max(1, rate_decision.retry_after_seconds)
                                            )
                                        },
                                    )
                                else:
                                    request.state.consumer_identity = identity
                                    response = await call_next(request)
                        else:
                            request.state.consumer_identity = identity
                            response = await call_next(request)
            else:
                response = await call_next(request)
            response_status = response.status_code
        finally:
            duration_ms = max(0.0, (monotonic_clock() - started) * 1000)
            route_template = _route_template(request, is_read_api=is_read_api)
            budget_ms = timing_policy.budget_for(route_template)
            observation = ApiRequestObservation(
                request_id=request_id,
                method=request.method,
                route_template=route_template,
                status_code=response_status,
                duration_ms=duration_ms,
                budget_ms=budget_ms,
                budget_exceeded=duration_ms > budget_ms,
                auth_outcome=auth_outcome,
            )
            with suppress(Exception):
                observer.observe(observation)
            if is_read_api:
                with suppress(Exception):
                    occurred_at = utc_clock()
                    if occurred_at.tzinfo is None:
                        occurred_at = occurred_at.replace(tzinfo=UTC)
                    auditor.record(
                        ConsumerAccessEvent(
                            occurred_at=occurred_at.astimezone(UTC).isoformat(),
                            request_id=request_id,
                            consumer_key=consumer_key,
                            method=request.method,
                            route_template=route_template,
                            status_code=response_status,
                            auth_outcome=auth_outcome,
                        )
                    )
            reset_request_id(token)
        response.headers[_REQUEST_ID_HEADER] = request_id
        response.headers["Server-Timing"] = f"app;dur={duration_ms:.3f}"
        completed_route = _route_template(request, is_read_api=is_read_api)
        completed_budget_ms = timing_policy.budget_for(completed_route)
        response.headers["X-Query-Budget"] = (
            "exceeded" if duration_ms > completed_budget_ms else "met"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        if "cache-control" not in response.headers:
            response.headers["Cache-Control"] = "no-store"
        return response

    @application.get("/health/live", response_model=LivenessResponse)
    def liveness() -> LivenessResponse:
        return LivenessResponse()

    @application.get(
        "/health/ready",
        response_model=ReadinessResponse,
        responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadinessResponse}},
    )
    def readiness(response: Response) -> ReadinessResponse:
        try:
            probe()
        except DatabaseNotConfiguredError:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return ReadinessResponse(status="not_ready", database="not_configured")
        except Exception:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return ReadinessResponse(status="not_ready", database="unavailable")
        return ReadinessResponse(status="ready", database="ready")

    register_read_routes(application, session_factory)
    register_catalog_routes(application, session_factory)
    register_detail_routes(application, session_factory)
    register_author_analytics_routes(application, session_factory)
    register_tag_analytics_routes(application, session_factory)
    register_operations_read_routes(
        application,
        session_factory,
        shared_controls_enabled=controls_enabled,
        audit_retention_days=retention_days,
        identity_adapter_configured=consumer_authorizer is not None,
    )
    register_jjwxc_routes(application, session_factory)

    return application


def _route_template(request: Request, *, is_read_api: bool) -> str:
    """Return a route template without retaining path parameters or query values."""
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    if isinstance(path, str) and path.startswith("/"):
        return path
    for candidate_route in request.app.routes:
        match, _ = candidate_route.matches(request.scope)
        candidate_path = getattr(candidate_route, "path", None)
        if match is Match.FULL and isinstance(candidate_path, str):
            return candidate_path
    if is_read_api:
        return "/api/v1/unmatched"
    if request.url.path.startswith("/health/"):
        return "/health/unmatched"
    return "/unmatched"


def _configured_session_factory() -> sessionmaker[Session] | None:
    database_url = os.getenv("PYURI_DATABASE_URL")
    if not database_url:
        return None
    return build_session_factory(build_engine(database_url))


def _shared_controls_enabled() -> bool:
    value = os.getenv("PYURI_SHARED_CONSUMER_CONTROLS_ENABLED", "false").strip().lower()
    if value not in {"true", "false"}:
        raise ValueError("PYURI_SHARED_CONSUMER_CONTROLS_ENABLED must be true or false")
    return value == "true"


def _configured_consumer_authorizer() -> ConsumerAuthorizer | None:
    mode = os.getenv("PYURI_CONSUMER_AUTH_MODE", "disabled").strip().lower()
    if mode == "disabled":
        return None
    if mode != "trusted_hmac_proxy":
        raise ValueError("PYURI_CONSUMER_AUTH_MODE must be disabled or trusted_hmac_proxy")
    proxy_id = os.getenv("PYURI_TRUSTED_PROXY_ID", "")
    secret = _trusted_proxy_secret()
    return TrustedHmacProxyAuthorizer(
        proxy_id=proxy_id,
        secret=secret,
        maximum_age_seconds=_bounded_env_int(
            "PYURI_TRUSTED_PROXY_MAX_AGE_SECONDS",
            default=30,
            minimum=1,
            maximum=300,
        ),
    )


def _trusted_proxy_secret() -> bytes:
    inline = os.getenv("PYURI_TRUSTED_PROXY_HMAC_SECRET")
    file_name = os.getenv("PYURI_TRUSTED_PROXY_HMAC_SECRET_FILE")
    if inline is not None and file_name is not None:
        raise ValueError("trusted proxy secret must use either inline or file configuration")
    if file_name is not None:
        secret_path = Path(file_name)
        if not secret_path.is_absolute() or not secret_path.is_file():
            raise ValueError("trusted proxy secret file must be an available absolute path")
        secret = secret_path.read_bytes()
    else:
        secret = (inline or "").encode("utf-8")
    if len(secret) > 4096:
        raise ValueError("trusted proxy secret is too large")
    return secret


def _bounded_env_int(name: str, *, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    try:
        value = default if raw is None else int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < minimum or value > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


app = create_app(
    session_factory=_configured_session_factory(),
    consumer_authorizer=_configured_consumer_authorizer(),
)
