"""Catalog detail and stable keyset ranking endpoints."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import FastAPI, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, or_, select
from sqlalchemy.orm import InstrumentedAttribute, Session, sessionmaker
from sqlalchemy.sql.elements import ColumnElement

from pixiv_yuri.analytics.models import CatalogAuthor, CatalogTag, CatalogWork, CatalogWorkTag
from pixiv_yuri.api.cache import private_cached
from pixiv_yuri.api.catalog_api import CatalogTagItem, CatalogWorkItem
from pixiv_yuri.api.cursor import (
    InvalidCursorError,
    decode_rank_cursor,
    encode_rank_cursor,
)

RankingMetric = Literal["likes", "bookmarks", "views"]
AuthorRankingMetric = Literal[
    "likes",
    "bookmarks",
    "views",
    "works",
    "average_likes",
    "average_bookmarks",
]


class AuthorDetail(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    author_id: str
    author_display_name: str
    first_seen_at: datetime
    last_seen_at: datetime
    work_count: int
    total_public_view_count: int
    total_public_bookmark_count: int
    total_public_like_count: int


class TagDetail(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    tag_name: str
    tag_translation: str | None
    work_count: int


class WorkRankingItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    work_id: str
    work_title: str
    author_id: str
    author_display_name: str
    score: int


class WorkRankingPage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    metric: RankingMetric
    items: tuple[WorkRankingItem, ...]
    next_cursor: str | None


class AuthorRankingItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    author_id: str
    author_display_name: str
    work_count: int
    metric_coverage_count: int
    score: int
    score_scale: Literal[1, 100]


class AuthorRankingPage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    metric: AuthorRankingMetric
    items: tuple[AuthorRankingItem, ...]
    next_cursor: str | None


def register_detail_routes(
    application: FastAPI,
    session_factory: sessionmaker[Session] | None,
) -> None:
    """Register payload-minimized detail and ranking reads."""

    @application.get("/api/v1/works/{work_id}", response_model=CatalogWorkItem)
    def work_detail(
        work_id: str,
        request: Request,
        response: Response,
    ) -> CatalogWorkItem | Response:
        factory = _require_factory(session_factory)
        try:
            with factory() as session:
                rows = session.execute(
                    select(CatalogWork, CatalogAuthor)
                    .join(CatalogAuthor, CatalogAuthor.id == CatalogWork.author_id)
                    .where(CatalogWork.work_id == work_id)
                    .limit(2)
                ).all()
                _require_single(rows, "work")
                work, author = rows[0]
                tags = _work_tags(session, work.id)
        except HTTPException:
            raise
        except Exception:
            raise _unavailable() from None
        payload = CatalogWorkItem(
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
            public_tags=tags,
        )
        return private_cached(request, response, payload, max_age=30)

    @application.get("/api/v1/authors/{author_id}", response_model=AuthorDetail)
    def author_detail(
        author_id: str,
        request: Request,
        response: Response,
    ) -> AuthorDetail | Response:
        factory = _require_factory(session_factory)
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
                    .where(CatalogAuthor.author_id == author_id)
                    .group_by(CatalogAuthor.id)
                    .limit(2)
                ).all()
                _require_single(rows, "author")
                author, works, views, bookmarks, likes = rows[0]
        except HTTPException:
            raise
        except Exception:
            raise _unavailable() from None
        payload = AuthorDetail(
            author_id=author.author_id,
            author_display_name=author.display_name,
            first_seen_at=_database_utc(author.first_seen_at),
            last_seen_at=_database_utc(author.last_seen_at),
            work_count=int(works),
            total_public_view_count=int(views),
            total_public_bookmark_count=int(bookmarks),
            total_public_like_count=int(likes),
        )
        return private_cached(request, response, payload, max_age=30)

    @application.get("/api/v1/tags/{tag_name:path}", response_model=TagDetail)
    def tag_detail(
        tag_name: str,
        request: Request,
        response: Response,
    ) -> TagDetail | Response:
        factory = _require_factory(session_factory)
        try:
            with factory() as session:
                rows = session.execute(
                    select(CatalogTag, func.count(CatalogWorkTag.work_id))
                    .outerjoin(CatalogWorkTag, CatalogWorkTag.tag_id == CatalogTag.id)
                    .where(CatalogTag.tag_name == tag_name)
                    .group_by(CatalogTag.id)
                    .limit(2)
                ).all()
                _require_single(rows, "tag")
                tag, works = rows[0]
        except HTTPException:
            raise
        except Exception:
            raise _unavailable() from None
        payload = TagDetail(
            tag_name=tag.tag_name,
            tag_translation=tag.tag_translation,
            work_count=int(works),
        )
        return private_cached(request, response, payload, max_age=60)

    @application.get("/api/v1/rankings/works", response_model=WorkRankingPage)
    def rank_works(
        request: Request,
        response: Response,
        metric: RankingMetric = "likes",
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        cursor: str | None = None,
    ) -> WorkRankingPage | Response:
        factory = _require_factory(session_factory)
        namespace = f"work-ranking:{metric}"
        rank_cursor = _rank_cursor(cursor, namespace)
        metric_column = _metric_column(metric)
        score = func.coalesce(metric_column, 0)
        statement = (
            select(CatalogWork, CatalogAuthor, score.label("score"))
            .join(CatalogAuthor, CatalogAuthor.id == CatalogWork.author_id)
            .order_by(score.desc(), CatalogWork.id)
            .limit(limit + 1)
        )
        if rank_cursor is not None:
            cursor_score, cursor_id = rank_cursor
            statement = statement.where(
                or_(
                    score < cursor_score,
                    (score == cursor_score) & (CatalogWork.id > cursor_id),
                )
            )
        try:
            with factory() as session:
                rows = session.execute(statement).all()
        except Exception:
            raise _unavailable() from None
        has_more = len(rows) > limit
        page_rows = rows[:limit]
        payload = WorkRankingPage(
            metric=metric,
            items=tuple(
                WorkRankingItem(
                    work_id=work.work_id,
                    work_title=work.title,
                    author_id=author.author_id,
                    author_display_name=author.display_name,
                    score=int(row_score),
                )
                for work, author, row_score in page_rows
            ),
            next_cursor=(
                encode_rank_cursor(
                    int(page_rows[-1][2]), page_rows[-1][0].id, namespace
                )
                if has_more
                else None
            ),
        )
        return private_cached(request, response, payload, max_age=30)

    @application.get("/api/v1/rankings/authors", response_model=AuthorRankingPage)
    def rank_authors(
        request: Request,
        response: Response,
        metric: AuthorRankingMetric = "likes",
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        cursor: str | None = None,
    ) -> AuthorRankingPage | Response:
        factory = _require_factory(session_factory)
        namespace = f"author-ranking:{metric}"
        rank_cursor = _rank_cursor(cursor, namespace)
        work_count = func.count(CatalogWork.id)
        coverage: ColumnElement[Any]
        score: ColumnElement[Any]
        if metric == "works":
            coverage = work_count
            score = work_count
            score_scale: Literal[1, 100] = 1
        else:
            base_metric: RankingMetric
            if metric == "average_likes":
                base_metric = "likes"
            elif metric == "average_bookmarks":
                base_metric = "bookmarks"
            else:
                base_metric = metric
            metric_column = _metric_column(base_metric)
            coverage = func.count(metric_column)
            total = func.coalesce(func.sum(metric_column), 0)
            if metric.startswith("average_"):
                score = (total * 100).op("/")(func.nullif(coverage, 0))
                score_scale = 100
            else:
                score = total
                score_scale = 1
        aggregate = (
            select(
                CatalogAuthor.id.label("internal_id"),
                CatalogAuthor.author_id.label("author_id"),
                CatalogAuthor.display_name.label("display_name"),
                work_count.label("work_count"),
                coverage.label("metric_coverage_count"),
                score.label("score"),
            )
            .outerjoin(CatalogWork, CatalogWork.author_id == CatalogAuthor.id)
            .group_by(CatalogAuthor.id)
            .subquery()
        )
        statement = (
            select(aggregate)
            .where(aggregate.c.metric_coverage_count > 0)
            .order_by(aggregate.c.score.desc(), aggregate.c.internal_id)
            .limit(limit + 1)
        )
        if rank_cursor is not None:
            cursor_score, cursor_id = rank_cursor
            statement = statement.where(
                or_(
                    aggregate.c.score < cursor_score,
                    (aggregate.c.score == cursor_score)
                    & (aggregate.c.internal_id > cursor_id),
                )
            )
        try:
            with factory() as session:
                rows = session.execute(statement).all()
        except Exception:
            raise _unavailable() from None
        has_more = len(rows) > limit
        page_rows = rows[:limit]
        payload = AuthorRankingPage(
            metric=metric,
            items=tuple(
                AuthorRankingItem(
                    author_id=row.author_id,
                    author_display_name=row.display_name,
                    work_count=int(row.work_count),
                    metric_coverage_count=int(row.metric_coverage_count),
                    score=int(row.score),
                    score_scale=score_scale,
                )
                for row in page_rows
            ),
            next_cursor=(
                encode_rank_cursor(
                    int(page_rows[-1].score),
                    int(page_rows[-1].internal_id),
                    namespace,
                )
                if has_more
                else None
            ),
        )
        return private_cached(request, response, payload, max_age=30)


def _metric_column(metric: RankingMetric) -> InstrumentedAttribute[int | None]:
    return {
        "likes": CatalogWork.public_like_count,
        "bookmarks": CatalogWork.public_bookmark_count,
        "views": CatalogWork.public_view_count,
    }[metric]


def _rank_cursor(cursor: str | None, namespace: str) -> tuple[int, int] | None:
    try:
        return decode_rank_cursor(cursor, namespace)
    except InvalidCursorError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="invalid_cursor",
        ) from None


def _work_tags(session: Session, work_id: int) -> tuple[CatalogTagItem, ...]:
    rows = session.scalars(
        select(CatalogTag)
        .join(CatalogWorkTag, CatalogWorkTag.tag_id == CatalogTag.id)
        .where(CatalogWorkTag.work_id == work_id)
        .order_by(CatalogWorkTag.position)
    ).all()
    return tuple(
        CatalogTagItem(tag_name=tag.tag_name, tag_translation=tag.tag_translation)
        for tag in rows
    )


def _require_single(rows: Sequence[object], entity: str) -> None:
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{entity}_not_found",
        )
    if len(rows) > 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"ambiguous_{entity}_id",
        )


def _require_factory(
    factory: sessionmaker[Session] | None,
) -> sessionmaker[Session]:
    if factory is None:
        raise _unavailable()
    return factory


def _unavailable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="data_service_unavailable",
    )


def _database_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
