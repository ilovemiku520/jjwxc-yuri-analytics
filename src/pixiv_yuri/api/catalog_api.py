"""Read-only catalog search and baseline aggregate endpoints."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from pixiv_yuri.analytics.models import (
    CatalogAuthor,
    CatalogTag,
    CatalogWork,
    CatalogWorkMetricSnapshot,
    CatalogWorkTag,
)
from pixiv_yuri.api.cache import private_cached
from pixiv_yuri.api.cursor import InvalidCursorError, decode_cursor, encode_cursor


class CatalogTagItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    tag_name: str
    tag_translation: str | None


class CatalogWorkItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    work_id: str
    work_title: str
    author_id: str
    author_display_name: str
    created_at: datetime
    page_count: int
    width: int | None
    height: int | None
    public_view_count: int | None
    public_bookmark_count: int | None
    public_like_count: int | None
    public_tags: tuple[CatalogTagItem, ...]


class CatalogWorkPage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    items: tuple[CatalogWorkItem, ...]
    next_cursor: str | None


class TagAggregateItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    tag_name: str
    tag_translation: str | None
    work_count: int


class TagAggregatePage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    items: tuple[TagAggregateItem, ...]
    next_cursor: str | None


class AuthorAggregateItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    author_id: str
    author_display_name: str
    work_count: int
    total_public_view_count: int
    total_public_bookmark_count: int
    total_public_like_count: int


class AuthorAggregatePage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    items: tuple[AuthorAggregateItem, ...]
    next_cursor: str | None


class WorkMetricSnapshotItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    observed_at: datetime
    public_view_count: int | None
    public_bookmark_count: int | None
    public_like_count: int | None


class WorkMetricHistoryPage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    work_id: str
    items: tuple[WorkMetricSnapshotItem, ...]
    next_cursor: str | None


class DailyMetricTrendItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    day: date
    observed_work_count: int
    total_public_view_count: int
    total_public_bookmark_count: int
    total_public_like_count: int


class DailyMetricTrendResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    date_from: date
    date_to: date
    items: tuple[DailyMetricTrendItem, ...]


class CatalogFreshnessResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    latest_observed_at: datetime | None
    author_count: int
    work_count: int
    tag_count: int
    metric_snapshot_count: int


def register_catalog_routes(
    application: FastAPI,
    session_factory: sessionmaker[Session] | None,
) -> None:
    """Register normalized catalog reads without adding mutation or collection routes."""

    @application.get(
        "/api/v1/works",
        response_model=CatalogWorkPage,
        responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "Unavailable"}},
    )
    def list_works(
        request: Request,
        response: Response,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        cursor: str | None = None,
        q: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
        author_id: Annotated[str | None, Query(min_length=1, max_length=255)] = None,
        tag: Annotated[str | None, Query(min_length=1, max_length=255)] = None,
    ) -> CatalogWorkPage | Response:
        factory = _require_factory(session_factory)
        row_cursor = _cursor_value(cursor)
        query_text = q.strip() if q is not None else None
        if q is not None and not query_text:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="invalid_query",
            )
        try:
            statement = (
                select(CatalogWork, CatalogAuthor)
                .join(CatalogAuthor, CatalogAuthor.id == CatalogWork.author_id)
                .where(CatalogWork.id > row_cursor)
                .order_by(CatalogWork.id)
                .limit(limit + 1)
            )
            if query_text is not None:
                escaped = _like_literal(query_text)
                statement = statement.where(
                    CatalogWork.title.ilike(f"%{escaped}%", escape="\\")
                )
            if author_id is not None:
                statement = statement.where(CatalogAuthor.author_id == author_id)
            if tag is not None:
                tagged_work_ids = (
                    select(CatalogWorkTag.work_id)
                    .join(CatalogTag, CatalogTag.id == CatalogWorkTag.tag_id)
                    .where(CatalogTag.tag_name == tag)
                )
                statement = statement.where(CatalogWork.id.in_(tagged_work_ids))
            with factory() as session:
                rows = session.execute(statement).all()
                page_rows = rows[:limit]
                tags_by_work = _load_tags(
                    session, [work.id for work, _author in page_rows]
                )
        except Exception:
            raise _unavailable() from None
        has_more = len(rows) > limit
        page = CatalogWorkPage(
            items=tuple(
                CatalogWorkItem(
                    work_id=work.work_id,
                    work_title=work.title,
                    author_id=author.author_id,
                    author_display_name=author.display_name,
                    created_at=_database_utc(work.created_at),
                    page_count=work.page_count,
                    width=work.width,
                    height=work.height,
                    public_view_count=work.public_view_count,
                    public_bookmark_count=work.public_bookmark_count,
                    public_like_count=work.public_like_count,
                    public_tags=tags_by_work.get(work.id, ()),
                )
                for work, author in page_rows
            ),
            next_cursor=encode_cursor(page_rows[-1][0].id) if has_more else None,
        )
        return private_cached(request, response, page, max_age=15)

    @application.get("/api/v1/analytics/tags", response_model=TagAggregatePage)
    def list_tag_aggregates(
        request: Request,
        response: Response,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        cursor: str | None = None,
    ) -> TagAggregatePage | Response:
        factory = _require_factory(session_factory)
        row_cursor = _cursor_value(cursor)
        try:
            with factory() as session:
                rows = session.execute(
                    select(CatalogTag, func.count(CatalogWorkTag.work_id))
                    .outerjoin(CatalogWorkTag, CatalogWorkTag.tag_id == CatalogTag.id)
                    .where(CatalogTag.id > row_cursor)
                    .group_by(CatalogTag.id)
                    .order_by(CatalogTag.id)
                    .limit(limit + 1)
                ).all()
        except Exception:
            raise _unavailable() from None
        has_more = len(rows) > limit
        page_rows = rows[:limit]
        page = TagAggregatePage(
            items=tuple(
                TagAggregateItem(
                    tag_name=tag_row.tag_name,
                    tag_translation=tag_row.tag_translation,
                    work_count=int(work_count),
                )
                for tag_row, work_count in page_rows
            ),
            next_cursor=encode_cursor(page_rows[-1][0].id) if has_more else None,
        )
        return private_cached(request, response, page, max_age=60)

    @application.get("/api/v1/analytics/authors", response_model=AuthorAggregatePage)
    def list_author_aggregates(
        request: Request,
        response: Response,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        cursor: str | None = None,
    ) -> AuthorAggregatePage | Response:
        factory = _require_factory(session_factory)
        row_cursor = _cursor_value(cursor)
        try:
            with factory() as session:
                rows = session.execute(
                    select(
                        CatalogAuthor,
                        func.count(CatalogWork.id),
                        func.coalesce(func.sum(CatalogWork.public_view_count), 0),
                        func.coalesce(func.sum(CatalogWork.public_bookmark_count), 0),
                        func.coalesce(func.sum(CatalogWork.public_like_count), 0),
                    )
                    .outerjoin(CatalogWork, CatalogWork.author_id == CatalogAuthor.id)
                    .where(CatalogAuthor.id > row_cursor)
                    .group_by(CatalogAuthor.id)
                    .order_by(CatalogAuthor.id)
                    .limit(limit + 1)
                ).all()
        except Exception:
            raise _unavailable() from None
        has_more = len(rows) > limit
        page_rows = rows[:limit]
        page = AuthorAggregatePage(
            items=tuple(
                AuthorAggregateItem(
                    author_id=author.author_id,
                    author_display_name=author.display_name,
                    work_count=int(work_count),
                    total_public_view_count=int(view_count),
                    total_public_bookmark_count=int(bookmark_count),
                    total_public_like_count=int(like_count),
                )
                for author, work_count, view_count, bookmark_count, like_count in page_rows
            ),
            next_cursor=encode_cursor(page_rows[-1][0].id) if has_more else None,
        )
        return private_cached(request, response, page, max_age=60)

    @application.get(
        "/api/v1/works/{work_id}/metric-history",
        response_model=WorkMetricHistoryPage,
        responses={
            status.HTTP_404_NOT_FOUND: {"description": "Work not found"},
            status.HTTP_409_CONFLICT: {"description": "Ambiguous work identity"},
        },
    )
    def list_work_metric_history(
        work_id: str,
        request: Request,
        response: Response,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        cursor: str | None = None,
        observed_from: Annotated[datetime | None, Query(alias="from")] = None,
        observed_to: Annotated[datetime | None, Query(alias="to")] = None,
    ) -> WorkMetricHistoryPage | Response:
        factory = _require_factory(session_factory)
        row_cursor = _cursor_value(cursor)
        _validate_datetime_range(observed_from, observed_to)
        try:
            with factory() as session:
                works = session.scalars(
                    select(CatalogWork).where(CatalogWork.work_id == work_id).limit(2)
                ).all()
                if not works:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="work_not_found",
                    )
                if len(works) > 1:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="ambiguous_work_id",
                    )
                statement = (
                    select(CatalogWorkMetricSnapshot)
                    .where(
                        CatalogWorkMetricSnapshot.work_id == works[0].id,
                        CatalogWorkMetricSnapshot.id > row_cursor,
                    )
                    .order_by(CatalogWorkMetricSnapshot.id)
                    .limit(limit + 1)
                )
                if observed_from is not None:
                    statement = statement.where(
                        CatalogWorkMetricSnapshot.observed_at >= observed_from
                    )
                if observed_to is not None:
                    statement = statement.where(
                        CatalogWorkMetricSnapshot.observed_at < observed_to
                    )
                rows = session.scalars(statement).all()
        except HTTPException:
            raise
        except Exception:
            raise _unavailable() from None
        has_more = len(rows) > limit
        page_rows = rows[:limit]
        page = WorkMetricHistoryPage(
            work_id=work_id,
            items=tuple(
                WorkMetricSnapshotItem(
                    observed_at=_database_utc(row.observed_at),
                    public_view_count=row.public_view_count,
                    public_bookmark_count=row.public_bookmark_count,
                    public_like_count=row.public_like_count,
                )
                for row in page_rows
            ),
            next_cursor=encode_cursor(page_rows[-1].id) if has_more else None,
        )
        return private_cached(request, response, page, max_age=30)

    @application.get(
        "/api/v1/analytics/metric-trends",
        response_model=DailyMetricTrendResponse,
    )
    def list_metric_trends(
        request: Request,
        response: Response,
        date_from: date,
        date_to: date,
    ) -> DailyMetricTrendResponse | Response:
        if date_to < date_from or (date_to - date_from).days > 365:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="invalid_date_range",
            )
        factory = _require_factory(session_factory)
        range_start = datetime.combine(date_from, time.min, tzinfo=UTC)
        range_end = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=UTC)
        day_value = func.date(CatalogWorkMetricSnapshot.observed_at)
        ranked = (
            select(
                CatalogWorkMetricSnapshot.work_id.label("work_id"),
                day_value.label("day"),
                CatalogWorkMetricSnapshot.public_view_count.label("views"),
                CatalogWorkMetricSnapshot.public_bookmark_count.label("bookmarks"),
                CatalogWorkMetricSnapshot.public_like_count.label("likes"),
                func.row_number()
                .over(
                    partition_by=(CatalogWorkMetricSnapshot.work_id, day_value),
                    order_by=(
                        CatalogWorkMetricSnapshot.observed_at.desc(),
                        CatalogWorkMetricSnapshot.id.desc(),
                    ),
                )
                .label("daily_rank"),
            )
            .where(
                CatalogWorkMetricSnapshot.observed_at >= range_start,
                CatalogWorkMetricSnapshot.observed_at < range_end,
            )
            .subquery()
        )
        try:
            with factory() as session:
                rows = session.execute(
                    select(
                        ranked.c.day,
                        func.count(ranked.c.work_id),
                        func.coalesce(func.sum(ranked.c.views), 0),
                        func.coalesce(func.sum(ranked.c.bookmarks), 0),
                        func.coalesce(func.sum(ranked.c.likes), 0),
                    )
                    .where(ranked.c.daily_rank == 1)
                    .group_by(ranked.c.day)
                    .order_by(ranked.c.day)
                ).all()
        except Exception:
            raise _unavailable() from None
        payload = DailyMetricTrendResponse(
            date_from=date_from,
            date_to=date_to,
            items=tuple(
                DailyMetricTrendItem(
                    day=day,
                    observed_work_count=int(work_count),
                    total_public_view_count=int(view_count),
                    total_public_bookmark_count=int(bookmark_count),
                    total_public_like_count=int(like_count),
                )
                for day, work_count, view_count, bookmark_count, like_count in rows
            ),
        )
        return private_cached(request, response, payload, max_age=60)

    @application.get(
        "/api/v1/analytics/freshness",
        response_model=CatalogFreshnessResponse,
    )
    def catalog_freshness(
        request: Request,
        response: Response,
    ) -> CatalogFreshnessResponse | Response:
        factory = _require_factory(session_factory)
        try:
            with factory() as session:
                latest, authors, works, tags, snapshots = session.execute(
                    select(
                        func.max(CatalogWorkMetricSnapshot.observed_at),
                        select(func.count()).select_from(CatalogAuthor).scalar_subquery(),
                        select(func.count()).select_from(CatalogWork).scalar_subquery(),
                        select(func.count()).select_from(CatalogTag).scalar_subquery(),
                        select(func.count())
                        .select_from(CatalogWorkMetricSnapshot)
                        .scalar_subquery(),
                    )
                ).one()
        except Exception:
            raise _unavailable() from None
        payload = CatalogFreshnessResponse(
            latest_observed_at=_database_utc(latest) if latest is not None else None,
            author_count=int(authors),
            work_count=int(works),
            tag_count=int(tags),
            metric_snapshot_count=int(snapshots),
        )
        return private_cached(request, response, payload, max_age=30)


def _load_tags(
    session: Session,
    work_ids: list[int],
) -> dict[int, tuple[CatalogTagItem, ...]]:
    if not work_ids:
        return {}
    grouped: defaultdict[int, list[CatalogTagItem]] = defaultdict(list)
    rows = session.execute(
        select(CatalogWorkTag.work_id, CatalogTag)
        .join(CatalogTag, CatalogTag.id == CatalogWorkTag.tag_id)
        .where(CatalogWorkTag.work_id.in_(work_ids))
        .order_by(CatalogWorkTag.work_id, CatalogWorkTag.position)
    ).all()
    for work_id, tag in rows:
        grouped[work_id].append(
            CatalogTagItem(tag_name=tag.tag_name, tag_translation=tag.tag_translation)
        )
    return {work_id: tuple(items) for work_id, items in grouped.items()}


def _require_factory(
    factory: sessionmaker[Session] | None,
) -> sessionmaker[Session]:
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


def _like_literal(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _validate_datetime_range(
    observed_from: datetime | None,
    observed_to: datetime | None,
) -> None:
    for value in (observed_from, observed_to):
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="timezone_required",
            )
    if observed_from is not None and observed_to is not None and observed_from >= observed_to:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="invalid_time_range",
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
