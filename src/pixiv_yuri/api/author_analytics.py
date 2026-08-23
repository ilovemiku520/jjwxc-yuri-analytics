"""Read-only Phase 4 author analytics derived from reviewed catalog fields."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session, sessionmaker

from pixiv_yuri.analytics.author_influence import (
    MODEL_VERSION,
    AuthorInfluenceInput,
    AuthorInfluenceWeights,
    classify_author_quality,
    score_author_influence,
)
from pixiv_yuri.analytics.models import (
    CatalogAuthor,
    CatalogTag,
    CatalogWork,
    CatalogWorkMetricSnapshot,
    CatalogWorkTag,
)
from pixiv_yuri.api.cache import private_cached


class AuthorMetricCoverage(BaseModel):
    """Number of works carrying each optional reviewed public metric."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    public_view_count: int
    public_bookmark_count: int
    public_like_count: int


class AuthorTagAffinity(BaseModel):
    """Observed author/tag association without semantic classification."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tag_name: str
    tag_translation: str | None
    work_count: int
    work_share_basis_points: int


class AuthorAnalyticsProfile(BaseModel):
    """Bounded descriptive profile derived only from current reviewed projections."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    author_id: str
    author_display_name: str
    analyzed_work_count: int
    first_work_created_at: datetime | None
    latest_work_created_at: datetime | None
    total_page_count: int
    total_public_view_count: int | None
    total_public_bookmark_count: int | None
    total_public_like_count: int | None
    public_bookmark_rate_basis_points: int | None
    public_like_rate_basis_points: int | None
    metric_coverage: AuthorMetricCoverage
    top_public_tags: tuple[AuthorTagAffinity, ...]


class AuthorDailyMetricTrendItem(BaseModel):
    """Latest-per-work daily public metrics with explicit coverage."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    day: date
    observed_work_count: int
    public_view_coverage_count: int
    public_bookmark_coverage_count: int
    public_like_coverage_count: int
    total_public_view_count: int | None
    total_public_bookmark_count: int | None
    total_public_like_count: int | None


class AuthorMetricTrendResponse(BaseModel):
    """Bounded author metric series that does not infer cross-cohort growth."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    author_id: str
    date_from: date
    date_to: date
    items: tuple[AuthorDailyMetricTrendItem, ...]


class AuthorMetricCohortGrowth(BaseModel):
    """One metric calculated only across works complete at both endpoints."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    complete_work_count: int
    start_total: int | None
    end_total: int | None
    absolute_change: int | None
    growth_basis_points: int | None


class AuthorCohortGrowthResponse(BaseModel):
    """Endpoint-to-endpoint change for a stable observed work intersection."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    author_id: str
    date_from: date
    date_to: date
    start_observed_work_count: int
    end_observed_work_count: int
    matched_work_count: int
    start_only_work_count: int
    end_only_work_count: int
    public_views: AuthorMetricCohortGrowth
    public_bookmarks: AuthorMetricCohortGrowth
    public_likes: AuthorMetricCohortGrowth


AuthorQualityQuadrant = Literal["core", "boutique", "ordinary", "volume"]


class AuthorQualityMapItem(BaseModel):
    """One bounded author point with complete bookmark-axis semantics."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    author_id: str
    author_display_name: str
    work_count: int
    bookmark_coverage_count: int
    average_public_bookmark_count_x100: int
    like_coverage_count: int
    total_public_like_count: int | None
    quadrant: AuthorQualityQuadrant


class AuthorQualityMapResponse(BaseModel):
    """Bounded scatter sample and explicit sample-relative median thresholds."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sampled_author_count: int
    sample_truncated: bool
    work_count_threshold_x100: int
    average_bookmark_threshold_x100: int
    items: tuple[AuthorQualityMapItem, ...]


class AuthorInfluenceWeightResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    bookmark: int
    like: int
    production: int


class AuthorInfluenceRankingItem(BaseModel):
    """One complete-metric influence result with inspectable components."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    author_id: str
    author_display_name: str
    work_count: int
    complete_metric_work_count: int
    average_public_bookmark_count_x100: int
    average_public_like_count_x100: int
    bookmark_component_basis_points: int
    like_component_basis_points: int
    production_component_basis_points: int
    influence_score_basis_points: int


class AuthorInfluenceRankingResponse(BaseModel):
    """Versioned, sample-relative ranking using approved metadata only."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    model_version: str
    weights: AuthorInfluenceWeightResponse
    sampled_author_count: int
    sample_truncated: bool
    items: tuple[AuthorInfluenceRankingItem, ...]


def register_author_analytics_routes(
    application: FastAPI,
    session_factory: sessionmaker[Session] | None,
) -> None:
    """Register the first Phase 4 author-analysis endpoint."""

    @application.get(
        "/api/v1/analytics/authors/quality-map",
        response_model=AuthorQualityMapResponse,
    )
    def author_quality_map(
        request: Request,
        response: Response,
        limit: Annotated[int, Query(ge=1, le=200)] = 100,
    ) -> AuthorQualityMapResponse | Response:
        factory = _require_factory(session_factory)
        aggregates = (
            select(
                CatalogAuthor.id.label("internal_id"),
                CatalogAuthor.author_id.label("author_id"),
                CatalogAuthor.display_name.label("display_name"),
                func.count(CatalogWork.id).label("work_count"),
                func.count(CatalogWork.public_bookmark_count).label(
                    "bookmark_coverage"
                ),
                func.coalesce(func.sum(CatalogWork.public_bookmark_count), 0).label(
                    "bookmark_total"
                ),
                func.count(CatalogWork.public_like_count).label("like_coverage"),
                func.coalesce(func.sum(CatalogWork.public_like_count), 0).label(
                    "like_total"
                ),
            )
            .outerjoin(CatalogWork, CatalogWork.author_id == CatalogAuthor.id)
            .group_by(CatalogAuthor.id)
            .subquery()
        )
        statement = (
            select(aggregates)
            .where(
                aggregates.c.work_count > 0,
                aggregates.c.bookmark_coverage > 0,
            )
            .order_by(aggregates.c.work_count.desc(), aggregates.c.internal_id)
            .limit(limit + 1)
        )
        try:
            with factory() as session:
                rows = session.execute(statement).all()
        except Exception:
            raise _unavailable() from None

        truncated = len(rows) > limit
        sample_rows = rows[:limit]
        work_threshold = _median_scaled(
            [int(row.work_count) * 100 for row in sample_rows]
        )
        bookmark_averages = [
            int(row.bookmark_total) * 100 // int(row.bookmark_coverage)
            for row in sample_rows
        ]
        bookmark_threshold = _median_scaled(bookmark_averages)
        items = tuple(
            AuthorQualityMapItem(
                author_id=row.author_id,
                author_display_name=row.display_name,
                work_count=int(row.work_count),
                bookmark_coverage_count=int(row.bookmark_coverage),
                average_public_bookmark_count_x100=average_bookmarks,
                like_coverage_count=int(row.like_coverage),
                total_public_like_count=(
                    int(row.like_total) if int(row.like_coverage) > 0 else None
                ),
                quadrant=classify_author_quality(
                    work_count_x100=int(row.work_count) * 100,
                    average_bookmarks_x100=average_bookmarks,
                    work_threshold_x100=work_threshold,
                    bookmark_threshold_x100=bookmark_threshold,
                ),
            )
            for row, average_bookmarks in zip(
                sample_rows, bookmark_averages, strict=True
            )
        )
        payload = AuthorQualityMapResponse(
            sampled_author_count=len(items),
            sample_truncated=truncated,
            work_count_threshold_x100=work_threshold,
            average_bookmark_threshold_x100=bookmark_threshold,
            items=items,
        )
        return private_cached(request, response, payload, max_age=60)

    @application.get(
        "/api/v1/analytics/authors/influence-ranking",
        response_model=AuthorInfluenceRankingResponse,
    )
    def author_influence_ranking(
        request: Request,
        response: Response,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        bookmark_weight: Annotated[int, Query(ge=0, le=10_000)] = 4_375,
        like_weight: Annotated[int, Query(ge=0, le=10_000)] = 3_750,
        production_weight: Annotated[int, Query(ge=0, le=10_000)] = 1_875,
    ) -> AuthorInfluenceRankingResponse | Response:
        weights = AuthorInfluenceWeights(
            bookmark=bookmark_weight,
            like=like_weight,
            production=production_weight,
        )
        try:
            weights.validate()
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="invalid_influence_weights",
            ) from None

        factory = _require_factory(session_factory)
        aggregates = (
            select(
                CatalogAuthor.id.label("internal_id"),
                CatalogAuthor.author_id.label("author_id"),
                CatalogAuthor.display_name.label("display_name"),
                func.count(CatalogWork.id).label("work_count"),
                func.count(CatalogWork.public_bookmark_count).label(
                    "bookmark_coverage"
                ),
                func.coalesce(func.sum(CatalogWork.public_bookmark_count), 0).label(
                    "bookmark_total"
                ),
                func.count(CatalogWork.public_like_count).label("like_coverage"),
                func.coalesce(func.sum(CatalogWork.public_like_count), 0).label(
                    "like_total"
                ),
            )
            .outerjoin(CatalogWork, CatalogWork.author_id == CatalogAuthor.id)
            .group_by(CatalogAuthor.id)
            .subquery()
        )
        statement = (
            select(aggregates)
            .where(
                aggregates.c.work_count > 0,
                aggregates.c.bookmark_coverage == aggregates.c.work_count,
                aggregates.c.like_coverage == aggregates.c.work_count,
            )
            .order_by(aggregates.c.internal_id)
            .limit(201)
        )
        try:
            with factory() as session:
                rows = session.execute(statement).all()
        except Exception:
            raise _unavailable() from None

        truncated = len(rows) > 200
        sample_rows = rows[:200]
        inputs = [
            AuthorInfluenceInput(
                author_id=row.author_id,
                author_display_name=row.display_name,
                work_count=int(row.work_count),
                average_bookmark_count_x100=(
                    int(row.bookmark_total) * 100 // int(row.bookmark_coverage)
                ),
                average_like_count_x100=(
                    int(row.like_total) * 100 // int(row.like_coverage)
                ),
            )
            for row in sample_rows
        ]
        ranked = score_author_influence(inputs, weights, limit=limit)
        payload = AuthorInfluenceRankingResponse(
            model_version=MODEL_VERSION,
            weights=AuthorInfluenceWeightResponse(
                bookmark=weights.bookmark,
                like=weights.like,
                production=weights.production,
            ),
            sampled_author_count=len(inputs),
            sample_truncated=truncated,
            items=tuple(
                AuthorInfluenceRankingItem(
                    author_id=item.author_id,
                    author_display_name=item.author_display_name,
                    work_count=item.work_count,
                    complete_metric_work_count=item.work_count,
                    average_public_bookmark_count_x100=(
                        item.average_bookmark_count_x100
                    ),
                    average_public_like_count_x100=item.average_like_count_x100,
                    bookmark_component_basis_points=(
                        item.bookmark_component_basis_points
                    ),
                    like_component_basis_points=item.like_component_basis_points,
                    production_component_basis_points=(
                        item.production_component_basis_points
                    ),
                    influence_score_basis_points=item.influence_score_basis_points,
                )
                for item in ranked
            ),
        )
        return private_cached(request, response, payload, max_age=60)

    @application.get(
        "/api/v1/analytics/authors/{author_id}/profile",
        response_model=AuthorAnalyticsProfile,
    )
    def author_analytics_profile(
        author_id: str,
        request: Request,
        response: Response,
    ) -> AuthorAnalyticsProfile | Response:
        factory = _require_factory(session_factory)
        try:
            with factory() as session:
                authors = session.scalars(
                    select(CatalogAuthor)
                    .where(CatalogAuthor.author_id == author_id)
                    .order_by(CatalogAuthor.id)
                    .limit(2)
                ).all()
                _require_single_author(authors)
                author = authors[0]
                (
                    work_count,
                    first_created_at,
                    latest_created_at,
                    page_count,
                    view_coverage,
                    bookmark_coverage,
                    like_coverage,
                    view_total,
                    bookmark_total,
                    like_total,
                ) = session.execute(
                    select(
                        func.count(CatalogWork.id),
                        func.min(CatalogWork.created_at),
                        func.max(CatalogWork.created_at),
                        func.coalesce(func.sum(CatalogWork.page_count), 0),
                        func.count(CatalogWork.public_view_count),
                        func.count(CatalogWork.public_bookmark_count),
                        func.count(CatalogWork.public_like_count),
                        func.coalesce(func.sum(CatalogWork.public_view_count), 0),
                        func.coalesce(func.sum(CatalogWork.public_bookmark_count), 0),
                        func.coalesce(func.sum(CatalogWork.public_like_count), 0),
                    ).where(CatalogWork.author_id == author.id)
                ).one()
                tag_count = func.count(CatalogWorkTag.work_id)
                tag_rows = session.execute(
                    select(CatalogTag, tag_count.label("work_count"))
                    .join(CatalogWorkTag, CatalogWorkTag.tag_id == CatalogTag.id)
                    .join(CatalogWork, CatalogWork.id == CatalogWorkTag.work_id)
                    .where(CatalogWork.author_id == author.id)
                    .group_by(CatalogTag.id)
                    .order_by(tag_count.desc(), CatalogTag.tag_name, CatalogTag.id)
                    .limit(10)
                ).all()
        except HTTPException:
            raise
        except Exception:
            raise _unavailable() from None

        works = int(work_count)
        views_seen = int(view_coverage)
        bookmarks_seen = int(bookmark_coverage)
        likes_seen = int(like_coverage)
        views = int(view_total)
        bookmarks = int(bookmark_total)
        likes = int(like_total)
        payload = AuthorAnalyticsProfile(
            author_id=author.author_id,
            author_display_name=author.display_name,
            analyzed_work_count=works,
            first_work_created_at=_database_utc(first_created_at),
            latest_work_created_at=_database_utc(latest_created_at),
            total_page_count=int(page_count),
            total_public_view_count=_covered_total(views_seen, views),
            total_public_bookmark_count=_covered_total(bookmarks_seen, bookmarks),
            total_public_like_count=_covered_total(likes_seen, likes),
            public_bookmark_rate_basis_points=_complete_rate(
                works=works,
                view_coverage=views_seen,
                numerator_coverage=bookmarks_seen,
                views=views,
                numerator=bookmarks,
            ),
            public_like_rate_basis_points=_complete_rate(
                works=works,
                view_coverage=views_seen,
                numerator_coverage=likes_seen,
                views=views,
                numerator=likes,
            ),
            metric_coverage=AuthorMetricCoverage(
                public_view_count=views_seen,
                public_bookmark_count=bookmarks_seen,
                public_like_count=likes_seen,
            ),
            top_public_tags=tuple(
                AuthorTagAffinity(
                    tag_name=tag.tag_name,
                    tag_translation=tag.tag_translation,
                    work_count=int(count),
                    work_share_basis_points=_basis_points(int(count), works),
                )
                for tag, count in tag_rows
            ),
        )
        return private_cached(request, response, payload, max_age=60)

    @application.get(
        "/api/v1/analytics/authors/{author_id}/metric-trends",
        response_model=AuthorMetricTrendResponse,
    )
    def author_metric_trends(
        author_id: str,
        date_from: date,
        date_to: date,
        request: Request,
        response: Response,
    ) -> AuthorMetricTrendResponse | Response:
        _validate_date_range(date_from, date_to)
        factory = _require_factory(session_factory)
        range_start = datetime.combine(date_from, time.min, tzinfo=UTC)
        range_end = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=UTC)
        day_value = func.date(CatalogWorkMetricSnapshot.observed_at)
        try:
            with factory() as session:
                authors = session.scalars(
                    select(CatalogAuthor)
                    .where(CatalogAuthor.author_id == author_id)
                    .order_by(CatalogAuthor.id)
                    .limit(2)
                ).all()
                _require_single_author(authors)
                author = authors[0]
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
                    .join(CatalogWork, CatalogWork.id == CatalogWorkMetricSnapshot.work_id)
                    .where(
                        CatalogWork.author_id == author.id,
                        CatalogWorkMetricSnapshot.observed_at >= range_start,
                        CatalogWorkMetricSnapshot.observed_at < range_end,
                    )
                    .subquery()
                )
                rows = session.execute(
                    select(
                        ranked.c.day,
                        func.count(ranked.c.work_id),
                        func.count(ranked.c.views),
                        func.count(ranked.c.bookmarks),
                        func.count(ranked.c.likes),
                        func.coalesce(func.sum(ranked.c.views), 0),
                        func.coalesce(func.sum(ranked.c.bookmarks), 0),
                        func.coalesce(func.sum(ranked.c.likes), 0),
                    )
                    .where(ranked.c.daily_rank == 1)
                    .group_by(ranked.c.day)
                    .order_by(ranked.c.day)
                ).all()
        except HTTPException:
            raise
        except Exception:
            raise _unavailable() from None

        payload = AuthorMetricTrendResponse(
            author_id=author.author_id,
            date_from=date_from,
            date_to=date_to,
            items=tuple(
                AuthorDailyMetricTrendItem(
                    day=day,
                    observed_work_count=int(work_count),
                    public_view_coverage_count=int(view_coverage),
                    public_bookmark_coverage_count=int(bookmark_coverage),
                    public_like_coverage_count=int(like_coverage),
                    total_public_view_count=_covered_total(
                        int(view_coverage), int(view_total)
                    ),
                    total_public_bookmark_count=_covered_total(
                        int(bookmark_coverage), int(bookmark_total)
                    ),
                    total_public_like_count=_covered_total(
                        int(like_coverage), int(like_total)
                    ),
                )
                for (
                    day,
                    work_count,
                    view_coverage,
                    bookmark_coverage,
                    like_coverage,
                    view_total,
                    bookmark_total,
                    like_total,
                ) in rows
            ),
        )
        return private_cached(request, response, payload, max_age=60)

    @application.get(
        "/api/v1/analytics/authors/{author_id}/growth",
        response_model=AuthorCohortGrowthResponse,
    )
    def author_cohort_growth(
        author_id: str,
        date_from: date,
        date_to: date,
        request: Request,
        response: Response,
    ) -> AuthorCohortGrowthResponse | Response:
        _validate_growth_range(date_from, date_to)
        factory = _require_factory(session_factory)
        start_begin = datetime.combine(date_from, time.min, tzinfo=UTC)
        start_end = start_begin + timedelta(days=1)
        end_begin = datetime.combine(date_to, time.min, tzinfo=UTC)
        end_end = end_begin + timedelta(days=1)
        # Keep both sides of the comparison typed as SQL DATE values. SQLite
        # accepts an ISO string here, but PostgreSQL correctly rejects
        # comparisons between DATE and VARCHAR.
        start_day = date_from
        end_day = date_to
        day_value = func.date(CatalogWorkMetricSnapshot.observed_at)
        try:
            with factory() as session:
                authors = session.scalars(
                    select(CatalogAuthor)
                    .where(CatalogAuthor.author_id == author_id)
                    .order_by(CatalogAuthor.id)
                    .limit(2)
                ).all()
                _require_single_author(authors)
                author = authors[0]
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
                    .join(CatalogWork, CatalogWork.id == CatalogWorkMetricSnapshot.work_id)
                    .where(
                        CatalogWork.author_id == author.id,
                        or_(
                            and_(
                                CatalogWorkMetricSnapshot.observed_at >= start_begin,
                                CatalogWorkMetricSnapshot.observed_at < start_end,
                            ),
                            and_(
                                CatalogWorkMetricSnapshot.observed_at >= end_begin,
                                CatalogWorkMetricSnapshot.observed_at < end_end,
                            ),
                        ),
                    )
                    .subquery()
                )
                daily = (
                    select(
                        ranked.c.work_id,
                        ranked.c.day,
                        ranked.c.views,
                        ranked.c.bookmarks,
                        ranked.c.likes,
                    )
                    .where(ranked.c.daily_rank == 1)
                    .subquery()
                )
                pairs = (
                    select(
                        daily.c.work_id,
                        func.max(case((daily.c.day == start_day, 1), else_=0)).label(
                            "start_seen"
                        ),
                        func.max(case((daily.c.day == end_day, 1), else_=0)).label(
                            "end_seen"
                        ),
                        func.max(case((daily.c.day == start_day, daily.c.views))).label(
                            "start_views"
                        ),
                        func.max(case((daily.c.day == end_day, daily.c.views))).label(
                            "end_views"
                        ),
                        func.max(case((daily.c.day == start_day, daily.c.bookmarks))).label(
                            "start_bookmarks"
                        ),
                        func.max(case((daily.c.day == end_day, daily.c.bookmarks))).label(
                            "end_bookmarks"
                        ),
                        func.max(case((daily.c.day == start_day, daily.c.likes))).label(
                            "start_likes"
                        ),
                        func.max(case((daily.c.day == end_day, daily.c.likes))).label(
                            "end_likes"
                        ),
                    )
                    .group_by(daily.c.work_id)
                    .subquery()
                )
                matched = and_(pairs.c.start_seen == 1, pairs.c.end_seen == 1)
                views_complete = and_(
                    matched,
                    pairs.c.start_views.is_not(None),
                    pairs.c.end_views.is_not(None),
                )
                bookmarks_complete = and_(
                    matched,
                    pairs.c.start_bookmarks.is_not(None),
                    pairs.c.end_bookmarks.is_not(None),
                )
                likes_complete = and_(
                    matched,
                    pairs.c.start_likes.is_not(None),
                    pairs.c.end_likes.is_not(None),
                )
                row = session.execute(
                    select(
                        func.coalesce(func.sum(pairs.c.start_seen), 0),
                        func.coalesce(func.sum(pairs.c.end_seen), 0),
                        func.coalesce(func.sum(case((matched, 1), else_=0)), 0),
                        func.coalesce(
                            func.sum(
                                case(
                                    (
                                        and_(
                                            pairs.c.start_seen == 1,
                                            pairs.c.end_seen == 0,
                                        ),
                                        1,
                                    ),
                                    else_=0,
                                )
                            ),
                            0,
                        ),
                        func.coalesce(
                            func.sum(
                                case(
                                    (
                                        and_(
                                            pairs.c.start_seen == 0,
                                            pairs.c.end_seen == 1,
                                        ),
                                        1,
                                    ),
                                    else_=0,
                                )
                            ),
                            0,
                        ),
                        func.coalesce(func.sum(case((views_complete, 1), else_=0)), 0),
                        func.coalesce(
                            func.sum(case((views_complete, pairs.c.start_views), else_=0)),
                            0,
                        ),
                        func.coalesce(
                            func.sum(case((views_complete, pairs.c.end_views), else_=0)),
                            0,
                        ),
                        func.coalesce(
                            func.sum(case((bookmarks_complete, 1), else_=0)), 0
                        ),
                        func.coalesce(
                            func.sum(
                                case(
                                    (bookmarks_complete, pairs.c.start_bookmarks), else_=0
                                )
                            ),
                            0,
                        ),
                        func.coalesce(
                            func.sum(
                                case((bookmarks_complete, pairs.c.end_bookmarks), else_=0)
                            ),
                            0,
                        ),
                        func.coalesce(func.sum(case((likes_complete, 1), else_=0)), 0),
                        func.coalesce(
                            func.sum(case((likes_complete, pairs.c.start_likes), else_=0)),
                            0,
                        ),
                        func.coalesce(
                            func.sum(case((likes_complete, pairs.c.end_likes), else_=0)),
                            0,
                        ),
                    )
                ).one()
        except HTTPException:
            raise
        except Exception:
            raise _unavailable() from None

        (
            start_count,
            end_count,
            matched_count,
            start_only_count,
            end_only_count,
            view_complete_count,
            view_start_total,
            view_end_total,
            bookmark_complete_count,
            bookmark_start_total,
            bookmark_end_total,
            like_complete_count,
            like_start_total,
            like_end_total,
        ) = (int(value) for value in row)
        payload = AuthorCohortGrowthResponse(
            author_id=author.author_id,
            date_from=date_from,
            date_to=date_to,
            start_observed_work_count=start_count,
            end_observed_work_count=end_count,
            matched_work_count=matched_count,
            start_only_work_count=start_only_count,
            end_only_work_count=end_only_count,
            public_views=_metric_cohort_growth(
                view_complete_count, view_start_total, view_end_total
            ),
            public_bookmarks=_metric_cohort_growth(
                bookmark_complete_count, bookmark_start_total, bookmark_end_total
            ),
            public_likes=_metric_cohort_growth(
                like_complete_count, like_start_total, like_end_total
            ),
        )
        return private_cached(request, response, payload, max_age=60)


def _covered_total(coverage: int, total: int) -> int | None:
    return total if coverage > 0 else None


def _complete_rate(
    *,
    works: int,
    view_coverage: int,
    numerator_coverage: int,
    views: int,
    numerator: int,
) -> int | None:
    if works == 0 or view_coverage != works or numerator_coverage != works or views <= 0:
        return None
    return _basis_points(numerator, views)


def _metric_cohort_growth(
    complete_work_count: int,
    start_total: int,
    end_total: int,
) -> AuthorMetricCohortGrowth:
    if complete_work_count == 0:
        return AuthorMetricCohortGrowth(
            complete_work_count=0,
            start_total=None,
            end_total=None,
            absolute_change=None,
            growth_basis_points=None,
        )
    change = end_total - start_total
    return AuthorMetricCohortGrowth(
        complete_work_count=complete_work_count,
        start_total=start_total,
        end_total=end_total,
        absolute_change=change,
        growth_basis_points=(
            _signed_basis_points(change, start_total) if start_total > 0 else None
        ),
    )


def _basis_points(numerator: int, denominator: int) -> int:
    if numerator < 0 or denominator <= 0:
        raise ValueError("basis-point inputs must be nonnegative with a positive denominator")
    return (numerator * 10_000 + denominator // 2) // denominator


def _signed_basis_points(numerator: int, denominator: int) -> int:
    if denominator <= 0:
        raise ValueError("signed basis-point denominator must be positive")
    magnitude = (abs(numerator) * 10_000 + denominator // 2) // denominator
    return magnitude if numerator >= 0 else -magnitude


def _median_scaled(values: list[int]) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) // 2


def _validate_date_range(date_from: date, date_to: date) -> None:
    if date_to < date_from or (date_to - date_from).days > 365:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="invalid_date_range",
        )


def _validate_growth_range(date_from: date, date_to: date) -> None:
    if date_to <= date_from or (date_to - date_from).days > 365:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="invalid_date_range",
        )


def _require_single_author(authors: Sequence[CatalogAuthor]) -> None:
    if not authors:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="author_not_found",
        )
    if len(authors) > 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="ambiguous_author_id",
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


def _database_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
