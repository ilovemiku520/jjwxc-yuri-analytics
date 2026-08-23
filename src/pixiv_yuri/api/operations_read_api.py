"""Minimized read-only operational views for the private Phase 3 interface."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal, cast

from fastapi import FastAPI, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from pixiv_yuri.api.cache import private_cached
from pixiv_yuri.api.cursor import InvalidCursorError, decode_cursor, encode_cursor
from pixiv_yuri.api.persistence_models import (
    ApiConsumerAccessAudit,
    ApiConsumerRateLimitWindow,
)
from pixiv_yuri.ingest.models import CrawlRun, CrawlTask, QuarantineRecord

RunStatusValue = Literal[
    "pending",
    "running",
    "completed",
    "completed_with_errors",
    "failed",
    "cancelled",
]
TaskStatusValue = Literal["pending", "running", "succeeded", "failed", "cancelled"]
QuarantineStatusValue = Literal["open", "resolved", "ignored"]
EntityTypeValue = Literal["work", "author", "tag_page", "search_page"]


class OperationalRunItem(BaseModel):
    """Bounded run status without configuration, requester, or stop details."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    id: int
    run_type: str
    provider: str
    status: RunStatusValue
    task_count: int
    succeeded_task_count: int
    failed_task_count: int
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class OperationalRunPage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    items: tuple[OperationalRunItem, ...]
    next_cursor: str | None


class OperationalTaskItem(BaseModel):
    """Task state without logical targets, idempotency keys, or lease identity."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    id: int
    run_id: int
    task_type: str
    status: TaskStatusValue
    priority: int
    attempt_count: int
    last_error_code: str | None
    available_at: datetime
    updated_at: datetime


class OperationalTaskPage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    items: tuple[OperationalTaskItem, ...]
    next_cursor: str | None


class QuarantineSummaryItem(BaseModel):
    """Review-queue status without source identity, free text, or attempt linkage."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    id: int
    entity_type: EntityTypeValue
    error_code: str
    status: QuarantineStatusValue
    first_failed_at: datetime
    last_failed_at: datetime


class QuarantineSummaryPage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    items: tuple[QuarantineSummaryItem, ...]
    next_cursor: str | None


class ConsumerSecurityStatus(BaseModel):
    """Aggregate control health without consumer identities or request targets."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    shared_rate_limit_backend: Literal["postgres", "disabled"]
    durable_access_audit_sink: Literal["postgres", "structured_log"]
    identity_adapter_configured: bool
    external_publication_approved: Literal[False] = False
    rate_limit_window_count: int
    audit_event_count: int
    oldest_audit_at: datetime | None
    latest_audit_at: datetime | None
    audit_retention_days: int


def register_operations_read_routes(
    application: FastAPI,
    session_factory: sessionmaker[Session] | None,
    *,
    shared_controls_enabled: bool = False,
    audit_retention_days: int = 30,
    identity_adapter_configured: bool = False,
) -> None:
    """Register private operational GET routes without mutation capabilities."""

    @application.get(
        "/api/v1/operations/runs",
        response_model=OperationalRunPage,
        responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "Unavailable"}},
    )
    def list_operational_runs(
        request: Request,
        response: Response,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        cursor: str | None = None,
        run_status: Annotated[RunStatusValue | None, Query(alias="status")] = None,
    ) -> OperationalRunPage | Response:
        factory = _require_factory(session_factory)
        row_cursor = _cursor_value(cursor)
        task_count = (
            select(func.count(CrawlTask.id))
            .where(CrawlTask.run_id == CrawlRun.id)
            .correlate(CrawlRun)
            .scalar_subquery()
        )
        succeeded_count = (
            select(func.count(CrawlTask.id))
            .where(CrawlTask.run_id == CrawlRun.id, CrawlTask.status == "succeeded")
            .correlate(CrawlRun)
            .scalar_subquery()
        )
        failed_count = (
            select(func.count(CrawlTask.id))
            .where(CrawlTask.run_id == CrawlRun.id, CrawlTask.status == "failed")
            .correlate(CrawlRun)
            .scalar_subquery()
        )
        statement = (
            select(CrawlRun, task_count, succeeded_count, failed_count)
            .where(CrawlRun.id > row_cursor)
            .order_by(CrawlRun.id)
            .limit(limit + 1)
        )
        if run_status is not None:
            statement = statement.where(CrawlRun.status == run_status)
        try:
            with factory() as session:
                rows = session.execute(statement).all()
        except Exception:
            raise _unavailable() from None
        has_more = len(rows) > limit
        page_rows = rows[:limit]
        page = OperationalRunPage(
            items=tuple(
                OperationalRunItem(
                    id=run.id,
                    run_type=run.run_type,
                    provider=run.provider,
                    status=cast(RunStatusValue, run.status),
                    task_count=int(total),
                    succeeded_task_count=int(succeeded),
                    failed_task_count=int(failed),
                    started_at=_database_utc_or_none(run.started_at),
                    finished_at=_database_utc_or_none(run.finished_at),
                    created_at=_database_utc(run.created_at),
                )
                for run, total, succeeded, failed in page_rows
            ),
            next_cursor=encode_cursor(page_rows[-1][0].id) if has_more else None,
        )
        return private_cached(request, response, page, max_age=10)

    @application.get(
        "/api/v1/operations/tasks",
        response_model=OperationalTaskPage,
        responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "Unavailable"}},
    )
    def list_operational_tasks(
        request: Request,
        response: Response,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        cursor: str | None = None,
        run_id: Annotated[int | None, Query(ge=1)] = None,
        task_status: Annotated[TaskStatusValue | None, Query(alias="status")] = None,
    ) -> OperationalTaskPage | Response:
        factory = _require_factory(session_factory)
        row_cursor = _cursor_value(cursor)
        statement = (
            select(CrawlTask)
            .where(CrawlTask.id > row_cursor)
            .order_by(CrawlTask.id)
            .limit(limit + 1)
        )
        if run_id is not None:
            statement = statement.where(CrawlTask.run_id == run_id)
        if task_status is not None:
            statement = statement.where(CrawlTask.status == task_status)
        try:
            with factory() as session:
                rows = session.scalars(statement).all()
        except Exception:
            raise _unavailable() from None
        has_more = len(rows) > limit
        page_rows = rows[:limit]
        page = OperationalTaskPage(
            items=tuple(
                OperationalTaskItem(
                    id=row.id,
                    run_id=row.run_id,
                    task_type=row.task_type,
                    status=cast(TaskStatusValue, row.status),
                    priority=row.priority,
                    attempt_count=row.attempt_count,
                    last_error_code=row.last_error_code,
                    available_at=_database_utc(row.available_at),
                    updated_at=_database_utc(row.updated_at),
                )
                for row in page_rows
            ),
            next_cursor=encode_cursor(page_rows[-1].id) if has_more else None,
        )
        return private_cached(request, response, page, max_age=10)

    @application.get(
        "/api/v1/operations/quarantine",
        response_model=QuarantineSummaryPage,
        responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "Unavailable"}},
    )
    def list_quarantine_summaries(
        request: Request,
        response: Response,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        cursor: str | None = None,
        entity_type: EntityTypeValue | None = None,
        quarantine_status: Annotated[
            QuarantineStatusValue | None, Query(alias="status")
        ] = None,
    ) -> QuarantineSummaryPage | Response:
        factory = _require_factory(session_factory)
        row_cursor = _cursor_value(cursor)
        statement = (
            select(QuarantineRecord)
            .where(QuarantineRecord.id > row_cursor)
            .order_by(QuarantineRecord.id)
            .limit(limit + 1)
        )
        if entity_type is not None:
            statement = statement.where(QuarantineRecord.entity_type == entity_type)
        if quarantine_status is not None:
            statement = statement.where(QuarantineRecord.status == quarantine_status)
        try:
            with factory() as session:
                rows = session.scalars(statement).all()
        except Exception:
            raise _unavailable() from None
        has_more = len(rows) > limit
        page_rows = rows[:limit]
        page = QuarantineSummaryPage(
            items=tuple(
                QuarantineSummaryItem(
                    id=row.id,
                    entity_type=cast(EntityTypeValue, row.entity_type),
                    error_code=row.error_code,
                    status=cast(QuarantineStatusValue, row.status),
                    first_failed_at=_database_utc(row.first_failed_at),
                    last_failed_at=_database_utc(row.last_failed_at),
                )
                for row in page_rows
            ),
            next_cursor=encode_cursor(page_rows[-1].id) if has_more else None,
        )
        return private_cached(request, response, page, max_age=10)

    @application.get(
        "/api/v1/operations/security-status",
        response_model=ConsumerSecurityStatus,
        responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "Unavailable"}},
    )
    def consumer_security_status(
        request: Request,
        response: Response,
    ) -> ConsumerSecurityStatus | Response:
        factory = _require_factory(session_factory)
        try:
            with factory() as session:
                window_count = session.scalar(
                    select(func.count()).select_from(ApiConsumerRateLimitWindow)
                )
                audit_summary = session.execute(
                    select(
                        func.count(ApiConsumerAccessAudit.id),
                        func.min(ApiConsumerAccessAudit.occurred_at),
                        func.max(ApiConsumerAccessAudit.occurred_at),
                    )
                ).one()
        except Exception:
            raise _unavailable() from None
        page = ConsumerSecurityStatus(
            shared_rate_limit_backend="postgres" if shared_controls_enabled else "disabled",
            durable_access_audit_sink=(
                "postgres" if shared_controls_enabled else "structured_log"
            ),
            identity_adapter_configured=identity_adapter_configured,
            rate_limit_window_count=int(window_count or 0),
            audit_event_count=int(audit_summary[0] or 0),
            oldest_audit_at=_database_utc_or_none(audit_summary[1]),
            latest_audit_at=_database_utc_or_none(audit_summary[2]),
            audit_retention_days=audit_retention_days,
        )
        return private_cached(request, response, page, max_age=5)


def _require_factory(factory: sessionmaker[Session] | None) -> sessionmaker[Session]:
    if factory is None:
        raise _unavailable()
    return factory


def _cursor_value(cursor: str | None) -> int:
    try:
        return decode_cursor(cursor)
    except InvalidCursorError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="invalid_cursor",
        ) from None


def _unavailable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="data_service_unavailable",
    )


def _database_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _database_utc_or_none(value: datetime | None) -> datetime | None:
    return _database_utc(value) if value is not None else None
