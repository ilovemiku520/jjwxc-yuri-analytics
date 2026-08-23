"""Fixture-only threshold sensitivity and human-review candidate evidence."""

from __future__ import annotations

from dataclasses import dataclass

from pixiv_yuri.analytics.tag_associations import (
    MAX_EDGE_LIMIT,
    MAX_WORK_SAMPLE,
    TagAssociationEdge,
    TagDescriptor,
    TaggedWork,
    build_tag_association_graph,
)

DEFAULT_COOCCURRENCE_THRESHOLDS = (1, 2, 3, 5, 10)
MAX_SENSITIVITY_THRESHOLDS = 8


@dataclass(frozen=True, slots=True)
class ThresholdSensitivityPoint:
    """One threshold's bounded edge population and baseline retention."""

    minimum_cooccurrence: int
    eligible_edge_count: int
    returned_edge_count: int
    baseline_edge_retention_basis_points: int
    stability_comparable: bool


@dataclass(frozen=True, slots=True)
class TagAssociationReviewCandidate:
    """Evidence queued for a human; this object intentionally has no label field."""

    rank: int
    left: TagDescriptor
    right: TagDescriptor
    cooccurrence_work_count: int
    sample_support_basis_points: int
    jaccard_basis_points: int
    pmi_milli_bits: int
    survives_minimum_cooccurrence: tuple[int, ...]
    review_state: str = "pending_human_review"


@dataclass(frozen=True, slots=True)
class TagAssociationSensitivityReport:
    """Bounded descriptive evidence, never an automated semantic decision."""

    sampled_work_count: int
    anchor_tag: str | None
    thresholds: tuple[int, ...]
    baseline_edge_count: int
    baseline_result_truncated: bool
    semantic_classification_performed: bool
    points: tuple[ThresholdSensitivityPoint, ...]
    review_candidates: tuple[TagAssociationReviewCandidate, ...]


def build_tag_association_sensitivity_report(
    works: tuple[TaggedWork, ...],
    *,
    thresholds: tuple[int, ...] = DEFAULT_COOCCURRENCE_THRESHOLDS,
    anchor_tag: str | None = None,
    candidate_limit: int = 50,
) -> TagAssociationSensitivityReport:
    """Compare fixed support thresholds and rank evidence for human review only."""
    _validate_thresholds(thresholds)
    if not 1 <= candidate_limit <= MAX_EDGE_LIMIT:
        raise ValueError("candidate_limit is outside the bounded range")

    graphs = tuple(
        build_tag_association_graph(
            works,
            anchor_tag=anchor_tag,
            minimum_cooccurrence=threshold,
            limit=MAX_EDGE_LIMIT,
        )
        for threshold in thresholds
    )
    baseline = graphs[0]
    baseline_keys = {_edge_key(edge) for edge in baseline.edges}
    edge_keys_by_threshold = tuple(
        {_edge_key(edge) for edge in graph.edges} for graph in graphs
    )

    points = tuple(
        ThresholdSensitivityPoint(
            minimum_cooccurrence=threshold,
            eligible_edge_count=graph.eligible_edge_count,
            returned_edge_count=len(graph.edges),
            baseline_edge_retention_basis_points=_retention_basis_points(
                baseline_keys, current_keys
            ),
            stability_comparable=(
                not baseline.result_truncated and not graph.result_truncated
            ),
        )
        for threshold, graph, current_keys in zip(
            thresholds, graphs, edge_keys_by_threshold, strict=True
        )
    )
    candidates = tuple(
        _candidate(
            rank=rank,
            edge=edge,
            thresholds=thresholds,
            edge_keys_by_threshold=edge_keys_by_threshold,
        )
        for rank, edge in enumerate(baseline.edges[:candidate_limit], start=1)
    )
    return TagAssociationSensitivityReport(
        sampled_work_count=baseline.sampled_work_count,
        anchor_tag=anchor_tag,
        thresholds=thresholds,
        baseline_edge_count=len(baseline.edges),
        baseline_result_truncated=baseline.result_truncated,
        semantic_classification_performed=False,
        points=points,
        review_candidates=candidates,
    )


def _validate_thresholds(thresholds: tuple[int, ...]) -> None:
    if not thresholds or len(thresholds) > MAX_SENSITIVITY_THRESHOLDS:
        raise ValueError("threshold count is outside the bounded range")
    if thresholds != tuple(sorted(set(thresholds))):
        raise ValueError("thresholds must be unique and strictly increasing")
    if thresholds[0] != 1:
        raise ValueError("the baseline threshold must be 1")
    if any(value < 1 or value > MAX_WORK_SAMPLE for value in thresholds):
        raise ValueError("threshold is outside the bounded range")


def _candidate(
    *,
    rank: int,
    edge: TagAssociationEdge,
    thresholds: tuple[int, ...],
    edge_keys_by_threshold: tuple[set[tuple[str, str]], ...],
) -> TagAssociationReviewCandidate:
    key = _edge_key(edge)
    return TagAssociationReviewCandidate(
        rank=rank,
        left=edge.left,
        right=edge.right,
        cooccurrence_work_count=edge.cooccurrence_work_count,
        sample_support_basis_points=edge.sample_support_basis_points,
        jaccard_basis_points=edge.jaccard_basis_points,
        pmi_milli_bits=edge.pmi_milli_bits,
        survives_minimum_cooccurrence=tuple(
            threshold
            for threshold, keys in zip(thresholds, edge_keys_by_threshold, strict=True)
            if key in keys
        ),
    )


def _edge_key(edge: TagAssociationEdge) -> tuple[str, str]:
    return edge.left.name, edge.right.name


def _retention_basis_points(
    baseline_keys: set[tuple[str, str]], current_keys: set[tuple[str, str]]
) -> int:
    if not baseline_keys:
        return 0
    retained = len(baseline_keys.intersection(current_keys))
    return (retained * 10_000 + len(baseline_keys) // 2) // len(baseline_keys)
