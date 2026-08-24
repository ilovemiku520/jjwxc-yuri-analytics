"""Read-only JJWXC fixture analytics API."""

from __future__ import annotations

import hmac
import os
from collections import defaultdict
from dataclasses import asdict
from datetime import date, datetime
from typing import Literal

from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from pixiv_yuri.jjwxc.analytics import (
    NOVEL_METRICS,
    MetricName,
    TimelineMetricName,
    correlation_matrix,
    metric_summary,
    normalized_timeline,
)
from pixiv_yuri.jjwxc.author_v_import import (
    MAX_AUTHOR_V_CLICK_NOVELS,
    MAX_AUTHOR_V_CLICK_RECORDS,
    AuthorVClickRecord,
    import_author_v_clicks,
)
from pixiv_yuri.jjwxc.author_v_jobs import (
    author_v_job_status,
    enqueue_author_v_job,
    retry_author_v_job,
)
from pixiv_yuri.jjwxc.cohort_import import (
    MAX_COHORT_NOVEL_IDS,
    MIN_CORRELATION_SAMPLE_SIZE,
    cohort_collection_status,
    queue_cohort_novels,
)
from pixiv_yuri.jjwxc.database_catalog import (
    DataMode,
    available_snapshot_days,
    load_catalog,
    load_latest_author_profiles,
    search_catalog,
    search_full_catalog_index,
)
from pixiv_yuri.jjwxc.demo import load_demo_catalog
from pixiv_yuri.jjwxc.models import (
    JjwxcCatalogSearchItem,
    JjwxcNovel,
    JjwxcTrendPoint,
)
from pixiv_yuri.jjwxc.persistence import (
    JjwxcAuthorRecord,
    JjwxcAuthorSnapshot,
    JjwxcChannelRankingSnapshot,
    JjwxcNovelRecord,
)
from pixiv_yuri.jjwxc.ratings import (
    AUTHOR_DEFAULT_WEIGHTS,
    RATING_METRICS,
    AuthorRatingMetric,
    RatingGrade,
    RatingMetric,
    build_author_profile_entities,
    build_novel_entities,
    evidence_weight_basis_points,
    score_author_profile_entities,
    score_entities,
)

NovelSort = Literal["reviews", "favorites", "points", "words", "clicks"]
AuthorSort = Literal["favorites", "reviews", "points", "novels"]


def _require_author_import_token(provided: str | None) -> None:
    expected = os.getenv("PYURI_COHORT_IMPORT_TOKEN")
    if not expected:
        raise HTTPException(status_code=503, detail="jjwxc_author_v_import_disabled")
    if provided is None or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=403, detail="jjwxc_author_v_import_forbidden")


class JjwxcOverviewResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    data_mode: DataMode
    novel_count: int = Field(ge=0)
    author_count: int = Field(ge=0)
    total_word_count: int = Field(ge=0)
    total_review_count: int = Field(ge=0)
    total_favorite_count: int = Field(ge=0)
    click_coverage_count: int = Field(ge=0)
    synopsis_feature_coverage_count: int = Field(ge=0)
    latest_observed_at: str


class JjwxcNovelPage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    data_mode: DataMode
    sort: NovelSort
    items: tuple[JjwxcNovel, ...]
    total: int = Field(ge=0)


class JjwxcSearchResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    data_mode: DataMode
    query: str
    match_fields: tuple[Literal["title", "author_display_name"], ...] = (
        "title",
        "author_display_name",
    )
    items: tuple[JjwxcNovel, ...]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


class JjwxcFullCatalogSearchResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    data_mode: DataMode
    query: str
    coverage: Literal["progressive_official_bookbase_index"] = "progressive_official_bookbase_index"
    match_fields: tuple[Literal["title", "author_display_name"], ...] = (
        "title",
        "author_display_name",
    )
    items: tuple[JjwxcCatalogSearchItem, ...]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


class JjwxcChannelRankingItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    rank: int = Field(ge=1, le=100)
    novel_id: str
    title: str
    author_id: str | None
    author_display_name: str | None
    observed_at: str


class JjwxcChannelRankingResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    ranking_key: Literal["channel_gold", "newcomer"]
    label: str
    observation_day: str | None
    items: tuple[JjwxcChannelRankingItem, ...]


class JjwxcAuthorSummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    author_id: str
    author_display_name: str
    novel_count: int = Field(ge=0)
    total_word_count: int = Field(ge=0)
    total_review_count: int = Field(ge=0)
    total_favorite_count: int = Field(ge=0)
    total_points: int = Field(ge=0)
    profile_nonlocked_work_count: int | None = Field(default=None, ge=0)
    profile_locked_work_count: int | None = Field(default=None, ge=0)
    profile_author_favorite_count: int | None = Field(default=None, ge=0)
    profile_total_word_count: int | None = Field(default=None, ge=0)
    profile_total_points: int | None = Field(default=None, ge=0)
    profile_observed_at: str | None = None


class JjwxcAuthorPage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    data_mode: DataMode
    sort: AuthorSort
    items: tuple[JjwxcAuthorSummary, ...]


class JjwxcAuthorDetail(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    author: JjwxcAuthorSummary
    novels: tuple[JjwxcNovel, ...]


class JjwxcTrendResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    data_mode: DataMode
    items: tuple[JjwxcTrendPoint, ...]


class JjwxcMetricSummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    metric: MetricName
    label: str
    observed_count: int = Field(ge=0)
    missing_count: int = Field(ge=0)
    coverage_basis_points: int = Field(ge=0, le=10_000)
    minimum: float | None
    maximum: float | None
    mean: float | None
    median: float | None
    standard_deviation: float | None
    p25: float | None
    p75: float | None
    coefficient_of_variation: float | None


class JjwxcCorrelationCell(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    x_metric: MetricName
    y_metric: MetricName
    paired_count: int = Field(ge=0)
    coefficient: float | None = Field(default=None, ge=-1, le=1)


class JjwxcNormalizedTrendPoint(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    day: str = Field(pattern=r"^20[0-9]{2}-[0-9]{2}-[0-9]{2}$")
    values: dict[TimelineMetricName, int | None]


class JjwxcMultivariateResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    data_mode: DataMode
    history_source: Literal["project_snapshot_fixture", "canonical_database_snapshot"]
    interpretation: Literal["descriptive_association_only"] = "descriptive_association_only"
    click_definition: Literal["average_non_v_chapter_click_count"] = (
        "average_non_v_chapter_click_count"
    )
    v_click_definition: Literal["average_v_chapter_click_count"] = "average_v_chapter_click_count"
    v_retention_definition: Literal[
        "average_v_chapter_click_count / average_non_v_chapter_click_count"
    ] = "average_v_chapter_click_count / average_non_v_chapter_click_count"
    correlation_method: Literal["pearson_log1p_zscore_pairwise_complete"] = (
        "pearson_log1p_zscore_pairwise_complete"
    )
    available_days: tuple[str, ...]
    selected_novel_ids: tuple[str, ...]
    cohort_items: tuple[JjwxcNovel, ...]
    timeline: tuple[JjwxcTrendPoint, ...]
    normalized_timeline: tuple[JjwxcNormalizedTrendPoint, ...]
    summaries: tuple[JjwxcMetricSummary, ...]
    correlation_matrix: tuple[JjwxcCorrelationCell, ...]


class JjwxcCohortImportRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: Literal["queue", "status"] = "queue"
    novel_ids: tuple[str, ...] = Field(min_length=1, max_length=MAX_COHORT_NOVEL_IDS)


class JjwxcCohortImportItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    novel_id: str
    status: Literal["ready", "queued", "running", "failed", "not_queued"]
    error_code: str | None = None


class JjwxcCohortImportResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    accepted_count: int = Field(ge=0, le=MAX_COHORT_NOVEL_IDS)
    ready_count: int = Field(ge=0, le=MAX_COHORT_NOVEL_IDS)
    minimum_analysis_sample: int = MIN_CORRELATION_SAMPLE_SIZE
    items: tuple[JjwxcCohortImportItem, ...]


class JjwxcAuthorVClickRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    novel_id: str = Field(pattern=r"^[1-9][0-9]{0,11}$")
    chapter_id: int = Field(ge=1, le=1_000_000)
    click_count: int = Field(ge=0, le=10**12)


class JjwxcAuthorVClickImportRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source_format: Literal["pyuri_jjwxc_author_v_clicks_json"]
    schema_version: Literal[1]
    generated_at: datetime
    authorization_attestation: Literal[True]
    records: tuple[JjwxcAuthorVClickRecord, ...] = Field(
        min_length=1, max_length=MAX_AUTHOR_V_CLICK_RECORDS
    )


class JjwxcAuthorVClickImportItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    novel_id: str
    status: Literal["imported", "duplicate", "rejected"]
    accepted_chapter_count: int = Field(ge=0)
    error_code: str | None = None


class JjwxcAuthorVClickImportResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    accepted_novel_count: int = Field(ge=0, le=MAX_AUTHOR_V_CLICK_NOVELS)
    accepted_chapter_count: int = Field(ge=0, le=MAX_AUTHOR_V_CLICK_RECORDS)
    items: tuple[JjwxcAuthorVClickImportItem, ...]


class JjwxcAuthorVClickJobResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    job_id: int = Field(ge=1)
    status: Literal["pending", "running", "completed", "failed"]
    task_status: Literal["pending", "running", "succeeded", "failed"]
    attempt_count: int = Field(ge=0, le=3)
    record_count: int = Field(ge=1, le=MAX_AUTHOR_V_CLICK_RECORDS)
    last_error_code: str | None = None
    novel_ids: tuple[str, ...] = Field(max_length=20)


class JjwxcRatingItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    entity_id: str
    title: str
    author_display_name: str
    score_basis_points: int = Field(ge=0, le=10_000)
    grade: RatingGrade
    coverage_basis_points: int = Field(ge=0, le=10_000)
    component_scores: dict[RatingMetric, int | None]


class JjwxcAuthorRatingItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    entity_id: str
    title: str
    author_display_name: str
    score_basis_points: int = Field(ge=0, le=10_000)
    grade: RatingGrade
    coverage_basis_points: int = Field(ge=0, le=10_000)
    component_scores: dict[AuthorRatingMetric, int | None]
    raw_values: dict[AuthorRatingMetric, int | None]


class JjwxcRatingResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    data_mode: DataMode
    model_version: Literal["jjwxc-public-performance-v1"] = "jjwxc-public-performance-v1"
    interpretation: Literal["cohort_relative_public_data_performance"] = (
        "cohort_relative_public_data_performance"
    )
    selected_day: str
    available_days: tuple[str, ...]
    default_weights: dict[RatingMetric, int]
    author_default_weights: dict[AuthorRatingMetric, int]
    effective_weights: dict[RatingMetric, int]
    novels: tuple[JjwxcRatingItem, ...]
    authors: tuple[JjwxcAuthorRatingItem, ...]


def register_jjwxc_routes(
    application: FastAPI,
    session_factory: sessionmaker[Session] | None = None,
) -> None:
    """Register source-specific read models without enabling source network access."""

    @application.get("/api/v1/jjwxc/overview", response_model=JjwxcOverviewResponse)
    def overview() -> JjwxcOverviewResponse:
        catalog, data_mode = load_catalog(session_factory)
        return JjwxcOverviewResponse(
            data_mode=data_mode,
            novel_count=len(catalog.novels),
            author_count=len({item.author_id for item in catalog.novels}),
            total_word_count=sum(item.word_count for item in catalog.novels),
            total_review_count=sum(item.review_count for item in catalog.novels),
            total_favorite_count=sum(item.favorite_count for item in catalog.novels),
            click_coverage_count=sum(
                item.average_non_v_chapter_click_count is not None for item in catalog.novels
            ),
            synopsis_feature_coverage_count=sum(
                item.synopsis_char_count is not None for item in catalog.novels
            ),
            latest_observed_at=max(item.observed_at for item in catalog.novels).isoformat(),
        )

    @application.get("/api/v1/jjwxc/novels", response_model=JjwxcNovelPage)
    def novels(
        query: str | None = Query(default=None, min_length=1, max_length=100),
        status: Literal["连载", "完结", "暂停", "锁定", "未知"] | None = None,
        genre: str | None = Query(default=None, min_length=1, max_length=40),
        sort: NovelSort = "favorites",
        limit: int = Query(default=100, ge=1, le=200),
    ) -> JjwxcNovelPage:
        catalog, data_mode = load_catalog(session_factory)
        items = list(catalog.novels)
        if query:
            needle = query.casefold()
            items = [
                item
                for item in items
                if needle in item.title.casefold() or needle in item.author_display_name.casefold()
            ]
        if status:
            items = [item for item in items if item.status == status]
        if genre:
            items = [item for item in items if genre in item.novel_type or genre in item.tags]
        key_by_sort = {
            "reviews": lambda item: item.review_count,
            "favorites": lambda item: item.favorite_count,
            "points": lambda item: item.points,
            "words": lambda item: item.word_count,
            "clicks": lambda item: item.average_non_v_chapter_click_count,
        }
        items.sort(
            key=lambda item: (
                key_by_sort[sort](item) is None,
                -(key_by_sort[sort](item) or 0),
                item.novel_id,
            )
        )
        total = len(items)
        return JjwxcNovelPage(
            data_mode=data_mode, sort=sort, items=tuple(items[:limit]), total=total
        )

    @application.get("/api/v1/jjwxc/novels/{novel_id}", response_model=JjwxcNovel)
    def novel_detail(novel_id: str) -> JjwxcNovel:
        catalog, _ = load_catalog(session_factory)
        matches = [item for item in catalog.novels if item.novel_id == novel_id]
        if not matches:
            raise HTTPException(status_code=404, detail="jjwxc_novel_not_found")
        return matches[0]

    @application.get("/api/v1/jjwxc/search", response_model=JjwxcSearchResponse)
    def search_novels(
        query: str = Query(min_length=1, max_length=100),
        limit: int = Query(default=50, ge=1, le=100),
        offset: int = Query(default=0, ge=0, le=100_000),
    ) -> JjwxcSearchResponse:
        normalized = " ".join(query.split())
        items, total, data_mode = search_catalog(
            session_factory,
            query=normalized,
            limit=limit,
            offset=offset,
        )
        return JjwxcSearchResponse(
            data_mode=data_mode,
            query=normalized,
            items=items,
            total=total,
            limit=limit,
            offset=offset,
        )

    @application.get(
        "/api/v1/jjwxc/catalog-search",
        response_model=JjwxcFullCatalogSearchResponse,
    )
    def search_full_catalog(
        query: str = Query(min_length=1, max_length=100),
        limit: int = Query(default=50, ge=1, le=100),
        offset: int = Query(default=0, ge=0, le=100_000),
    ) -> JjwxcFullCatalogSearchResponse:
        normalized = " ".join(query.split())
        items, total, data_mode = search_full_catalog_index(
            session_factory,
            query=normalized,
            limit=limit,
            offset=offset,
        )
        return JjwxcFullCatalogSearchResponse(
            data_mode=data_mode,
            query=normalized,
            items=items,
            total=total,
            limit=limit,
            offset=offset,
        )

    @application.get(
        "/api/v1/jjwxc/channel-rankings",
        response_model=JjwxcChannelRankingResponse,
    )
    def channel_rankings(
        ranking_key: Literal["channel_gold", "newcomer"] = "channel_gold",
        day: str | None = Query(default=None, pattern=r"^20[0-9]{2}-[0-9]{2}-[0-9]{2}$"),
    ) -> JjwxcChannelRankingResponse:
        labels = {"channel_gold": "频道金榜", "newcomer": "新手金榜"}
        if session_factory is None:
            return JjwxcChannelRankingResponse(
                ranking_key=ranking_key,
                label=labels[ranking_key],
                observation_day=None,
                items=(),
            )
        with session_factory() as session:
            selected_day = day
            if selected_day is None:
                latest_day = session.scalar(
                    select(func.max(JjwxcChannelRankingSnapshot.observation_day)).where(
                        JjwxcChannelRankingSnapshot.ranking_key == ranking_key
                    )
                )
                selected_day = latest_day.isoformat() if latest_day else None
            if selected_day is None:
                rows: list[
                    tuple[
                        JjwxcChannelRankingSnapshot,
                        JjwxcNovelRecord | None,
                        JjwxcAuthorRecord | None,
                    ]
                ] = []
            else:
                target_day = date.fromisoformat(selected_day)
                rows = list(
                    session.execute(
                        select(
                            JjwxcChannelRankingSnapshot,
                            JjwxcNovelRecord,
                            JjwxcAuthorRecord,
                        )
                        .outerjoin(
                            JjwxcNovelRecord,
                            JjwxcNovelRecord.novel_id == JjwxcChannelRankingSnapshot.novel_id,
                        )
                        .outerjoin(
                            JjwxcAuthorRecord,
                            JjwxcAuthorRecord.id == JjwxcNovelRecord.author_record_id,
                        )
                        .where(
                            JjwxcChannelRankingSnapshot.ranking_key == ranking_key,
                            JjwxcChannelRankingSnapshot.observation_day == target_day,
                        )
                        .order_by(JjwxcChannelRankingSnapshot.rank)
                    )
                    .tuples()
                    .all()
                )
        return JjwxcChannelRankingResponse(
            ranking_key=ranking_key,
            label=labels[ranking_key],
            observation_day=selected_day,
            items=tuple(
                JjwxcChannelRankingItem(
                    rank=ranking.rank,
                    novel_id=ranking.novel_id,
                    title=ranking.title,
                    author_id=author.author_id if author else None,
                    author_display_name=author.display_name if author else None,
                    observed_at=ranking.observed_at.isoformat(),
                )
                for ranking, _, author in rows
            ),
        )

    @application.get("/api/v1/jjwxc/authors", response_model=JjwxcAuthorPage)
    def authors(sort: AuthorSort = "favorites") -> JjwxcAuthorPage:
        catalog, data_mode = load_catalog(session_factory)
        profiles = load_latest_author_profiles(session_factory)
        summaries = list(_author_summaries(catalog.novels, profiles).values())
        key_by_sort = {
            "favorites": lambda item: item.total_favorite_count,
            "reviews": lambda item: item.total_review_count,
            "points": lambda item: item.total_points,
            "novels": lambda item: (
                item.profile_nonlocked_work_count
                if item.profile_nonlocked_work_count is not None
                else item.novel_count
            ),
        }
        summaries.sort(key=lambda item: (-key_by_sort[sort](item), item.author_id))
        return JjwxcAuthorPage(data_mode=data_mode, sort=sort, items=tuple(summaries))

    @application.get("/api/v1/jjwxc/authors/{author_id}", response_model=JjwxcAuthorDetail)
    def author_detail(author_id: str) -> JjwxcAuthorDetail:
        catalog, _ = load_catalog(session_factory)
        profiles = load_latest_author_profiles(session_factory)
        summaries = _author_summaries(catalog.novels, profiles)
        author = summaries.get(author_id)
        if author is None:
            raise HTTPException(status_code=404, detail="jjwxc_author_not_found")
        novels_by_author = tuple(item for item in catalog.novels if item.author_id == author_id)
        return JjwxcAuthorDetail(author=author, novels=novels_by_author)

    @application.get("/api/v1/jjwxc/trends", response_model=JjwxcTrendResponse)
    def trends() -> JjwxcTrendResponse:
        catalog, data_mode = load_catalog(session_factory)
        return JjwxcTrendResponse(data_mode=data_mode, items=catalog.trends)

    @application.get(
        "/api/v1/jjwxc/analytics/multivariate",
        response_model=JjwxcMultivariateResponse,
    )
    def multivariate_analytics(
        novel_ids: str | None = Query(
            default=None,
            max_length=1299,
            pattern=r"^[1-9][0-9]{0,11}(,[1-9][0-9]{0,11}){0,99}$",
        ),
    ) -> JjwxcMultivariateResponse:
        selected_novel_ids = tuple(dict.fromkeys(novel_ids.split(","))) if novel_ids else ()
        catalog, data_mode = load_catalog(
            session_factory,
            novel_ids=frozenset(selected_novel_ids) if selected_novel_ids else None,
        )
        if selected_novel_ids and (
            data_mode != "database_snapshot"
            or {item.novel_id for item in catalog.novels} != set(selected_novel_ids)
        ):
            raise HTTPException(status_code=404, detail="jjwxc_analytics_cohort_not_found")
        return JjwxcMultivariateResponse(
            data_mode=data_mode,
            history_source=(
                "canonical_database_snapshot"
                if data_mode == "database_snapshot"
                else "project_snapshot_fixture"
            ),
            available_days=(
                available_snapshot_days(session_factory)
                or tuple(item.day for item in catalog.trends)
            ),
            selected_novel_ids=selected_novel_ids,
            cohort_items=catalog.novels,
            timeline=catalog.trends,
            normalized_timeline=tuple(
                JjwxcNormalizedTrendPoint.model_validate(item)
                for item in normalized_timeline(catalog.trends)
            ),
            summaries=tuple(
                JjwxcMetricSummary.model_validate(metric_summary(catalog.novels, definition))
                for definition in NOVEL_METRICS
            ),
            correlation_matrix=tuple(
                JjwxcCorrelationCell.model_validate(item)
                for item in correlation_matrix(catalog.novels)
            ),
        )

    @application.post(
        "/api/v1/jjwxc/analytics/cohorts/import",
        response_model=JjwxcCohortImportResponse,
        include_in_schema=False,
    )
    def import_analytics_cohort(
        request: JjwxcCohortImportRequest,
        x_pyuri_internal_operation: str | None = Header(default=None),
    ) -> JjwxcCohortImportResponse:
        expected_token = os.getenv("PYURI_COHORT_IMPORT_TOKEN")
        if not expected_token:
            raise HTTPException(status_code=503, detail="jjwxc_cohort_import_disabled")
        if x_pyuri_internal_operation is None or not hmac.compare_digest(
            x_pyuri_internal_operation, expected_token
        ):
            raise HTTPException(status_code=403, detail="jjwxc_cohort_import_forbidden")
        if session_factory is None:
            raise HTTPException(status_code=503, detail="jjwxc_database_required")
        try:
            with session_factory() as session:
                items = (
                    queue_cohort_novels(session, novel_ids=request.novel_ids)
                    if request.mode == "queue"
                    else cohort_collection_status(session, novel_ids=request.novel_ids)
                )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        response_items = tuple(
            JjwxcCohortImportItem(
                novel_id=item.novel_id,
                status=item.status,
                error_code=item.error_code,
            )
            for item in items
        )
        return JjwxcCohortImportResponse(
            accepted_count=len(response_items),
            ready_count=sum(item.status == "ready" for item in response_items),
            items=response_items,
        )

    @application.post(
        "/api/v1/jjwxc/analytics/author-v-clicks/import",
        response_model=JjwxcAuthorVClickImportResponse,
        include_in_schema=False,
    )
    def import_author_v_click_export(
        request: JjwxcAuthorVClickImportRequest,
        x_pyuri_internal_operation: str | None = Header(default=None),
    ) -> JjwxcAuthorVClickImportResponse:
        expected_token = os.getenv("PYURI_COHORT_IMPORT_TOKEN")
        if not expected_token:
            raise HTTPException(status_code=503, detail="jjwxc_author_v_import_disabled")
        if x_pyuri_internal_operation is None or not hmac.compare_digest(
            x_pyuri_internal_operation, expected_token
        ):
            raise HTTPException(status_code=403, detail="jjwxc_author_v_import_forbidden")
        if session_factory is None:
            raise HTTPException(status_code=503, detail="jjwxc_database_required")
        try:
            with session_factory() as session:
                imported = import_author_v_clicks(
                    session,
                    records=tuple(
                        AuthorVClickRecord(
                            novel_id=item.novel_id,
                            chapter_id=item.chapter_id,
                            click_count=item.click_count,
                        )
                        for item in request.records
                    ),
                    observed_at=request.generated_at,
                    authorization_attested=request.authorization_attestation,
                )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        items = tuple(
            JjwxcAuthorVClickImportItem(
                novel_id=item.novel_id,
                status=item.status,
                accepted_chapter_count=item.accepted_chapter_count,
                error_code=item.error_code,
            )
            for item in imported
        )
        return JjwxcAuthorVClickImportResponse(
            accepted_novel_count=sum(item.status != "rejected" for item in items),
            accepted_chapter_count=sum(item.accepted_chapter_count for item in items),
            items=items,
        )

    @application.post(
        "/api/v1/jjwxc/analytics/author-v-clicks/jobs",
        response_model=JjwxcAuthorVClickJobResponse,
        include_in_schema=False,
    )
    def create_author_v_click_job(
        request: JjwxcAuthorVClickImportRequest,
        x_pyuri_internal_operation: str | None = Header(default=None),
    ) -> JjwxcAuthorVClickJobResponse:
        _require_author_import_token(x_pyuri_internal_operation)
        if session_factory is None:
            raise HTTPException(status_code=503, detail="jjwxc_database_required")
        with session_factory() as session:
            job = enqueue_author_v_job(session, payload=request.model_dump(mode="json"))
        return JjwxcAuthorVClickJobResponse(**asdict(job))

    @application.get(
        "/api/v1/jjwxc/analytics/author-v-clicks/jobs/{job_id}",
        response_model=JjwxcAuthorVClickJobResponse,
        include_in_schema=False,
    )
    def get_author_v_click_job(
        job_id: int,
        x_pyuri_internal_operation: str | None = Header(default=None),
    ) -> JjwxcAuthorVClickJobResponse:
        _require_author_import_token(x_pyuri_internal_operation)
        if session_factory is None:
            raise HTTPException(status_code=503, detail="jjwxc_database_required")
        try:
            with session_factory() as session:
                job = author_v_job_status(session, job_id=job_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return JjwxcAuthorVClickJobResponse(**asdict(job))

    @application.post(
        "/api/v1/jjwxc/analytics/author-v-clicks/jobs/{job_id}/retry",
        response_model=JjwxcAuthorVClickJobResponse,
        include_in_schema=False,
    )
    def retry_author_v_click_job(
        job_id: int,
        x_pyuri_internal_operation: str | None = Header(default=None),
    ) -> JjwxcAuthorVClickJobResponse:
        _require_author_import_token(x_pyuri_internal_operation)
        if session_factory is None:
            raise HTTPException(status_code=503, detail="jjwxc_database_required")
        try:
            with session_factory() as session:
                job = retry_author_v_job(session, job_id=job_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return JjwxcAuthorVClickJobResponse(**asdict(job))

    @application.get(
        "/api/v1/jjwxc/analytics/ratings",
        response_model=JjwxcRatingResponse,
    )
    def ratings(
        day: str | None = Query(default=None, pattern=r"^20[0-9]{2}-[0-9]{2}-[0-9]{2}$"),
        reviews: int | None = Query(default=None, ge=0, le=10_000),
        favorites: int | None = Query(default=None, ge=0, le=10_000),
        points: int | None = Query(default=None, ge=0, le=10_000),
        words: int | None = Query(default=None, ge=0, le=10_000),
        clicks: int | None = Query(default=None, ge=0, le=10_000),
    ) -> JjwxcRatingResponse:
        available_days = available_snapshot_days(session_factory)
        if not available_days:
            fixture = load_demo_catalog()
            available_days = tuple(
                sorted({item.observed_at.date().isoformat() for item in fixture.novels})
            )
        selected_day = day or available_days[-1]
        if selected_day not in available_days:
            raise HTTPException(status_code=422, detail="jjwxc_rating_day_not_available")
        catalog, data_mode = load_catalog(session_factory, selected_day=selected_day)
        profiles = load_latest_author_profiles(session_factory, selected_day=selected_day)
        default_weights = evidence_weight_basis_points(catalog.novels)
        supplied: dict[RatingMetric, int | None] = {
            "reviews": reviews,
            "favorites": favorites,
            "points": points,
            "words": words,
            "clicks": clicks,
        }
        effective_weights = (
            default_weights
            if all(value is None for value in supplied.values())
            else _validated_rating_weights(supplied)
        )
        return JjwxcRatingResponse(
            data_mode=data_mode,
            selected_day=selected_day,
            available_days=available_days,
            default_weights=default_weights,
            author_default_weights=AUTHOR_DEFAULT_WEIGHTS,
            effective_weights=effective_weights,
            novels=tuple(
                JjwxcRatingItem.model_validate(item)
                for item in score_entities(build_novel_entities(catalog.novels), effective_weights)
            ),
            authors=tuple(
                JjwxcAuthorRatingItem.model_validate(item)
                for item in score_author_profile_entities(
                    build_author_profile_entities(
                        catalog.novels,
                        _author_profile_rating_values(profiles),
                    ),
                    AUTHOR_DEFAULT_WEIGHTS,
                )
            ),
        )


def _author_summaries(
    novels: tuple[JjwxcNovel, ...],
    profiles: dict[str, JjwxcAuthorSnapshot],
) -> dict[str, JjwxcAuthorSummary]:
    grouped: dict[str, list[JjwxcNovel]] = defaultdict(list)
    for novel in novels:
        grouped[novel.author_id].append(novel)
    return {
        author_id: JjwxcAuthorSummary(
            author_id=author_id,
            author_display_name=novels[0].author_display_name,
            novel_count=len(novels),
            total_word_count=sum(item.word_count for item in novels),
            total_review_count=sum(item.review_count for item in novels),
            total_favorite_count=sum(item.favorite_count for item in novels),
            total_points=sum(item.points for item in novels),
            profile_nonlocked_work_count=(
                profiles[author_id].nonlocked_work_count if author_id in profiles else None
            ),
            profile_locked_work_count=(
                profiles[author_id].locked_work_count if author_id in profiles else None
            ),
            profile_author_favorite_count=(
                profiles[author_id].author_favorite_count if author_id in profiles else None
            ),
            profile_total_word_count=(
                profiles[author_id].total_word_count if author_id in profiles else None
            ),
            profile_total_points=(
                profiles[author_id].total_points if author_id in profiles else None
            ),
            profile_observed_at=(
                profiles[author_id].observed_at.isoformat() if author_id in profiles else None
            ),
        )
        for author_id, novels in grouped.items()
    }


def _author_profile_rating_values(
    profiles: dict[str, JjwxcAuthorSnapshot],
) -> dict[str, dict[AuthorRatingMetric, float | None]]:
    return {
        author_id: {
            "nonlocked_works": float(snapshot.nonlocked_work_count),
            "author_favorites": float(snapshot.author_favorite_count),
            "work_favorites": None,
            "words": float(snapshot.total_word_count),
            "points": float(snapshot.total_points),
        }
        for author_id, snapshot in profiles.items()
    }


def _validated_rating_weights(
    supplied: dict[RatingMetric, int | None],
) -> dict[RatingMetric, int]:
    weights = {metric: supplied[metric] or 0 for metric in RATING_METRICS}
    if sum(weights.values()) <= 0:
        raise HTTPException(status_code=422, detail="jjwxc_rating_weights_empty")
    total = sum(weights.values())
    normalized = {metric: weights[metric] * 10_000 // total for metric in RATING_METRICS}
    remainder = 10_000 - sum(normalized.values())
    for metric in RATING_METRICS[:remainder]:
        normalized[metric] += 1
    return normalized
