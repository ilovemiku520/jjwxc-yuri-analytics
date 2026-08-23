"""Private read-only Phase 5 tag association API."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from pixiv_yuri.analytics.models import CatalogTag, CatalogWork, CatalogWorkTag
from pixiv_yuri.analytics.tag_associations import (
    MAX_EDGE_LIMIT,
    MAX_WORK_SAMPLE,
    TagAssociationEdge,
    TagDescriptor,
    TaggedWork,
    build_tag_association_graph,
)
from pixiv_yuri.analytics.tag_sensitivity import (
    TagAssociationReviewCandidate,
    build_tag_association_sensitivity_report,
)
from pixiv_yuri.api.cache import private_cached


class TagAssociationNodeResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    tag_name: str
    tag_translation: str | None
    sampled_work_count: int


class TagAssociationEdgeResponse(BaseModel):
    """One descriptive edge without semantic classification."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    left: TagAssociationNodeResponse
    right: TagAssociationNodeResponse
    cooccurrence_work_count: int
    sample_support_basis_points: int
    jaccard_basis_points: int
    pmi_milli_bits: int


class TagAssociationGraphResponse(BaseModel):
    """Bounded sampled graph with explicit non-classification semantics."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    interpretation: Literal["descriptive_association_only"] = (
        "descriptive_association_only"
    )
    semantic_classification_performed: Literal[False] = False
    catalog_work_count: int
    sampled_work_count: int
    sample_truncated: bool
    observed_tag_count: int
    eligible_edge_count: int
    result_truncated: bool
    anchor_tag: str | None
    minimum_cooccurrence: int
    edges: tuple[TagAssociationEdgeResponse, ...]


class TagSensitivityPointResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    minimum_cooccurrence: int
    eligible_edge_count: int
    returned_edge_count: int
    baseline_edge_retention_basis_points: int
    stability_comparable: bool


class TagReviewCandidateResponse(BaseModel):
    """Descriptive evidence awaiting accountable human review."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    rank: int
    left_tag_name: str
    left_tag_translation: str | None
    right_tag_name: str
    right_tag_translation: str | None
    cooccurrence_work_count: int
    sample_support_basis_points: int
    jaccard_basis_points: int
    pmi_milli_bits: int
    survives_minimum_cooccurrence: tuple[int, ...]
    review_state: Literal["pending_human_review"] = "pending_human_review"


class TagAssociationSensitivityResponse(BaseModel):
    """Fixture-safe sensitivity evidence without an automated semantic decision."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    interpretation: Literal["descriptive_association_only"] = (
        "descriptive_association_only"
    )
    semantic_classification_performed: Literal[False] = False
    catalog_work_count: int
    sampled_work_count: int
    sample_truncated: bool
    anchor_tag: str | None
    thresholds: tuple[int, ...]
    baseline_edge_count: int
    baseline_result_truncated: bool
    points: tuple[TagSensitivityPointResponse, ...]
    review_candidates: tuple[TagReviewCandidateResponse, ...]


def register_tag_analytics_routes(
    application: FastAPI,
    session_factory: sessionmaker[Session] | None,
) -> None:
    """Register the bounded GET-only tag association projection."""

    @application.get(
        "/api/v1/analytics/tags/co-occurrence",
        response_model=TagAssociationGraphResponse,
    )
    def tag_cooccurrence(
        request: Request,
        response: Response,
        anchor_tag: Annotated[str | None, Query(min_length=1, max_length=255)] = None,
        minimum_cooccurrence: Annotated[
            int, Query(ge=1, le=MAX_WORK_SAMPLE)
        ] = 1,
        limit: Annotated[int, Query(ge=1, le=MAX_EDGE_LIMIT)] = 100,
        sample_work_limit: Annotated[
            int, Query(ge=1, le=MAX_WORK_SAMPLE)
        ] = 1_000,
    ) -> TagAssociationGraphResponse | Response:
        factory = _require_factory(session_factory)
        try:
            catalog_work_count, sampled_works = _load_sampled_works(
                factory, sample_work_limit
            )
            graph = build_tag_association_graph(
                sampled_works,
                anchor_tag=anchor_tag,
                minimum_cooccurrence=minimum_cooccurrence,
                limit=limit,
            )
        except HTTPException:
            raise
        except Exception:
            raise _unavailable() from None

        payload = TagAssociationGraphResponse(
            catalog_work_count=catalog_work_count,
            sampled_work_count=graph.sampled_work_count,
            sample_truncated=catalog_work_count > graph.sampled_work_count,
            observed_tag_count=graph.observed_tag_count,
            eligible_edge_count=graph.eligible_edge_count,
            result_truncated=graph.result_truncated,
            anchor_tag=graph.anchor_tag,
            minimum_cooccurrence=graph.minimum_cooccurrence,
            edges=tuple(_edge_response(edge) for edge in graph.edges),
        )
        return private_cached(request, response, payload, max_age=60)

    @application.get(
        "/api/v1/analytics/tags/association-sensitivity",
        response_model=TagAssociationSensitivityResponse,
    )
    def tag_association_sensitivity(
        request: Request,
        response: Response,
        anchor_tag: Annotated[str | None, Query(min_length=1, max_length=255)] = None,
        candidate_limit: Annotated[int, Query(ge=1, le=MAX_EDGE_LIMIT)] = 50,
        sample_work_limit: Annotated[
            int, Query(ge=1, le=MAX_WORK_SAMPLE)
        ] = 1_000,
    ) -> TagAssociationSensitivityResponse | Response:
        factory = _require_factory(session_factory)
        try:
            catalog_work_count, sampled_works = _load_sampled_works(
                factory, sample_work_limit
            )
            report = build_tag_association_sensitivity_report(
                sampled_works,
                anchor_tag=anchor_tag,
                candidate_limit=candidate_limit,
            )
        except HTTPException:
            raise
        except Exception:
            raise _unavailable() from None

        payload = TagAssociationSensitivityResponse(
            catalog_work_count=catalog_work_count,
            sampled_work_count=report.sampled_work_count,
            sample_truncated=catalog_work_count > report.sampled_work_count,
            anchor_tag=report.anchor_tag,
            thresholds=report.thresholds,
            baseline_edge_count=report.baseline_edge_count,
            baseline_result_truncated=report.baseline_result_truncated,
            points=tuple(
                TagSensitivityPointResponse(
                    minimum_cooccurrence=point.minimum_cooccurrence,
                    eligible_edge_count=point.eligible_edge_count,
                    returned_edge_count=point.returned_edge_count,
                    baseline_edge_retention_basis_points=(
                        point.baseline_edge_retention_basis_points
                    ),
                    stability_comparable=point.stability_comparable,
                )
                for point in report.points
            ),
            review_candidates=tuple(
                _candidate_response(candidate)
                for candidate in report.review_candidates
            ),
        )
        return private_cached(request, response, payload, max_age=60)


def _edge_response(edge: TagAssociationEdge) -> TagAssociationEdgeResponse:
    return TagAssociationEdgeResponse(
        left=TagAssociationNodeResponse(
            tag_name=edge.left.name,
            tag_translation=edge.left.translation,
            sampled_work_count=edge.left_work_count,
        ),
        right=TagAssociationNodeResponse(
            tag_name=edge.right.name,
            tag_translation=edge.right.translation,
            sampled_work_count=edge.right_work_count,
        ),
        cooccurrence_work_count=edge.cooccurrence_work_count,
        sample_support_basis_points=edge.sample_support_basis_points,
        jaccard_basis_points=edge.jaccard_basis_points,
        pmi_milli_bits=edge.pmi_milli_bits,
    )


def _candidate_response(
    candidate: TagAssociationReviewCandidate,
) -> TagReviewCandidateResponse:
    return TagReviewCandidateResponse(
        rank=candidate.rank,
        left_tag_name=candidate.left.name,
        left_tag_translation=candidate.left.translation,
        right_tag_name=candidate.right.name,
        right_tag_translation=candidate.right.translation,
        cooccurrence_work_count=candidate.cooccurrence_work_count,
        sample_support_basis_points=candidate.sample_support_basis_points,
        jaccard_basis_points=candidate.jaccard_basis_points,
        pmi_milli_bits=candidate.pmi_milli_bits,
        survives_minimum_cooccurrence=candidate.survives_minimum_cooccurrence,
    )


def _load_sampled_works(
    factory: sessionmaker[Session], sample_work_limit: int
) -> tuple[int, tuple[TaggedWork, ...]]:
    with factory() as session:
        catalog_work_count = int(
            session.scalar(select(func.count(CatalogWork.id))) or 0
        )
        work_rows = session.execute(
            select(CatalogWork.id, CatalogWork.work_id)
            .order_by(CatalogWork.created_at.desc(), CatalogWork.id.desc())
            .limit(sample_work_limit)
        ).all()
        internal_ids = [int(row.id) for row in work_rows]
        tags_by_work: dict[int, list[TagDescriptor]] = {
            internal_id: [] for internal_id in internal_ids
        }
        if internal_ids:
            tag_rows = session.execute(
                select(
                    CatalogWorkTag.work_id,
                    CatalogTag.tag_name,
                    CatalogTag.tag_translation,
                )
                .join(CatalogTag, CatalogTag.id == CatalogWorkTag.tag_id)
                .where(CatalogWorkTag.work_id.in_(internal_ids))
                .order_by(
                    CatalogWorkTag.work_id,
                    CatalogTag.tag_name,
                    CatalogTag.id,
                )
            ).all()
            for row in tag_rows:
                tags_by_work[int(row.work_id)].append(
                    TagDescriptor(
                        name=str(row.tag_name),
                        translation=(
                            str(row.tag_translation)
                            if row.tag_translation is not None
                            else None
                        ),
                    )
                )
        sampled_works = tuple(
            TaggedWork(
                work_id=str(row.work_id),
                tags=tuple(tags_by_work[int(row.id)]),
            )
            for row in work_rows
        )
    return catalog_work_count, sampled_works


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
