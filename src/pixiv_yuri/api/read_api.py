"""Phase 2 read-only, payload-minimized database API."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal, cast

from fastapi import FastAPI, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from pixiv_yuri.api.cache import private_cached
from pixiv_yuri.api.cursor import InvalidCursorError, decode_cursor, encode_cursor
from pixiv_yuri.ingest.models import RawObservation, SchemaDefinition, SourceRecord

EntityTypeValue = Literal["work", "author", "tag_page", "search_page"]
SchemaStatusValue = Literal["discovered", "approved", "rejected"]
ValidationStatusValue = Literal["pending", "valid", "invalid", "quarantined"]


class SourceRecordItem(BaseModel):
    """Public operational identity without URL, payload, credential, or metadata."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    id: int
    source_system: str
    entity_type: EntityTypeValue
    source_id: str
    current_availability: str
    first_seen_at: datetime
    last_seen_at: datetime


class SourceRecordPage(BaseModel):
    """Stable keyset page; absence of a cursor means the page is terminal."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    items: tuple[SourceRecordItem, ...]
    next_cursor: str | None
    next_after_id: int | None


class SchemaDefinitionItem(BaseModel):
    """Schema lifecycle summary that deliberately omits the structural definition."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    id: int
    entity_type: EntityTypeValue
    fingerprint: str
    sample_count: int
    status: SchemaStatusValue
    compatible_parser_min: str | None
    compatible_parser_max: str | None
    first_seen_at: datetime
    last_seen_at: datetime


class SchemaDefinitionPage(BaseModel):
    """Opaque-cursor page of schema lifecycle summaries."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    items: tuple[SchemaDefinitionItem, ...]
    next_cursor: str | None


class ObservationItem(BaseModel):
    """Observation history without source URL, object key, hash, or metadata."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    id: int
    observed_at: datetime
    status_code: int
    content_type: str
    payload_bytes: int
    schema_fingerprint: str
    parser_version: str | None
    validation_status: ValidationStatusValue
    created_at: datetime


class ObservationPage(BaseModel):
    """Opaque-cursor page of minimized observation history."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    source_record_id: int
    items: tuple[ObservationItem, ...]
    next_cursor: str | None


def register_read_routes(
    application: FastAPI,
    session_factory: sessionmaker[Session] | None,
) -> None:
    """Register only read routes; no mutation or acquisition path is exposed."""

    @application.get(
        "/api/v1/source-records",
        response_model=SourceRecordPage,
        responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "Unavailable"}},
    )
    def list_source_records(
        request: Request,
        response: Response,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        cursor: str | None = None,
        after_id: Annotated[int, Query(ge=0, deprecated=True)] = 0,
        entity_type: EntityTypeValue | None = None,
    ) -> SourceRecordPage | Response:
        factory = _require_factory(session_factory)
        if cursor is not None and after_id != 0:
            raise _invalid_cursor()
        row_cursor = _cursor_value(cursor) if cursor is not None else after_id
        try:
            statement = (
                select(SourceRecord)
                .where(SourceRecord.id > row_cursor)
                .order_by(SourceRecord.id)
                .limit(limit + 1)
            )
            if entity_type is not None:
                statement = statement.where(SourceRecord.entity_type == entity_type)
            with factory() as session:
                rows = session.scalars(statement).all()
        except Exception:
            raise _unavailable() from None
        has_more = len(rows) > limit
        page_rows = rows[:limit]
        next_id = page_rows[-1].id if has_more else None
        page = SourceRecordPage(
            items=tuple(
                SourceRecordItem(
                    id=row.id,
                    source_system=row.source_system,
                    entity_type=cast(EntityTypeValue, row.entity_type),
                    source_id=row.source_id,
                    current_availability=row.current_availability,
                    first_seen_at=_database_utc(row.first_seen_at),
                    last_seen_at=_database_utc(row.last_seen_at),
                )
                for row in page_rows
            ),
            next_cursor=encode_cursor(next_id) if next_id is not None else None,
            next_after_id=next_id,
        )
        return private_cached(request, response, page, max_age=15)

    @application.get(
        "/api/v1/schema-definitions",
        response_model=SchemaDefinitionPage,
        responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "Unavailable"}},
    )
    def list_schema_definitions(
        request: Request,
        response: Response,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        cursor: str | None = None,
        entity_type: EntityTypeValue | None = None,
        schema_status: Annotated[SchemaStatusValue | None, Query(alias="status")] = None,
    ) -> SchemaDefinitionPage | Response:
        factory = _require_factory(session_factory)
        row_cursor = _cursor_value(cursor)
        try:
            statement = (
                select(SchemaDefinition)
                .where(SchemaDefinition.id > row_cursor)
                .order_by(SchemaDefinition.id)
                .limit(limit + 1)
            )
            if entity_type is not None:
                statement = statement.where(SchemaDefinition.entity_type == entity_type)
            if schema_status is not None:
                statement = statement.where(SchemaDefinition.status == schema_status)
            with factory() as session:
                rows = session.scalars(statement).all()
        except Exception:
            raise _unavailable() from None
        has_more = len(rows) > limit
        page_rows = rows[:limit]
        page = SchemaDefinitionPage(
            items=tuple(
                SchemaDefinitionItem(
                    id=row.id,
                    entity_type=cast(EntityTypeValue, row.entity_type),
                    fingerprint=row.fingerprint,
                    sample_count=row.sample_count,
                    status=cast(SchemaStatusValue, row.status),
                    compatible_parser_min=row.compatible_parser_min,
                    compatible_parser_max=row.compatible_parser_max,
                    first_seen_at=_database_utc(row.first_seen_at),
                    last_seen_at=_database_utc(row.last_seen_at),
                )
                for row in page_rows
            ),
            next_cursor=encode_cursor(page_rows[-1].id) if has_more else None,
        )
        return private_cached(request, response, page, max_age=60)

    @application.get(
        "/api/v1/source-records/{source_record_id}/observations",
        response_model=ObservationPage,
        responses={
            status.HTTP_404_NOT_FOUND: {"description": "Source record not found"},
            status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "Unavailable"},
        },
    )
    def list_observations(
        source_record_id: int,
        request: Request,
        response: Response,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        cursor: str | None = None,
    ) -> ObservationPage | Response:
        if source_record_id <= 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="invalid_source_record_id",
            )
        factory = _require_factory(session_factory)
        row_cursor = _cursor_value(cursor)
        try:
            with factory() as session:
                exists = session.scalar(
                    select(SourceRecord.id).where(SourceRecord.id == source_record_id)
                )
                if exists is None:
                    raise _not_found()
                rows = session.scalars(
                    select(RawObservation)
                    .where(
                        RawObservation.source_record_id == source_record_id,
                        RawObservation.id > row_cursor,
                    )
                    .order_by(RawObservation.id)
                    .limit(limit + 1)
                ).all()
        except HTTPException:
            raise
        except Exception:
            raise _unavailable() from None
        has_more = len(rows) > limit
        page_rows = rows[:limit]
        page = ObservationPage(
            source_record_id=source_record_id,
            items=tuple(
                ObservationItem(
                    id=row.id,
                    observed_at=_database_utc(row.observed_at),
                    status_code=row.status_code,
                    content_type=row.content_type,
                    payload_bytes=row.payload_bytes,
                    schema_fingerprint=row.schema_fingerprint,
                    parser_version=row.parser_version,
                    validation_status=cast(ValidationStatusValue, row.validation_status),
                    created_at=_database_utc(row.created_at),
                )
                for row in page_rows
            ),
            next_cursor=encode_cursor(page_rows[-1].id) if has_more else None,
        )
        return private_cached(request, response, page, max_age=30)


def _require_factory(factory: sessionmaker[Session] | None) -> sessionmaker[Session]:
    if factory is None:
        raise _unavailable()
    return factory


def _cursor_value(cursor: str | None) -> int:
    try:
        return decode_cursor(cursor)
    except InvalidCursorError:
        raise _invalid_cursor() from None


def _invalid_cursor() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail="invalid_cursor",
    )


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="source_record_not_found",
    )


def _unavailable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="data_service_unavailable",
    )


def _database_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
