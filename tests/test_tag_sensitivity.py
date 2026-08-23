from __future__ import annotations

import pytest

from pixiv_yuri.analytics.tag_associations import TagDescriptor, TaggedWork
from pixiv_yuri.analytics.tag_sensitivity import (
    DEFAULT_COOCCURRENCE_THRESHOLDS,
    MAX_SENSITIVITY_THRESHOLDS,
    build_tag_association_sensitivity_report,
)


def _tag(name: str) -> TagDescriptor:
    return TagDescriptor(name=name)


def _sample() -> tuple[TaggedWork, ...]:
    return (
        TaggedWork("w1", (_tag("a"), _tag("b"), _tag("c"))),
        TaggedWork("w2", (_tag("a"), _tag("b"))),
        TaggedWork("w3", (_tag("a"), _tag("c"))),
        TaggedWork("w4", (_tag("a"), _tag("d"))),
        TaggedWork("w5", (_tag("b"), _tag("d"))),
    )


def test_fixed_thresholds_expose_deterministic_retention() -> None:
    report = build_tag_association_sensitivity_report(_sample())

    assert report.thresholds == DEFAULT_COOCCURRENCE_THRESHOLDS
    assert report.sampled_work_count == 5
    assert report.baseline_edge_count == 5
    assert report.baseline_result_truncated is False
    assert report.semantic_classification_performed is False
    assert [point.eligible_edge_count for point in report.points] == [5, 2, 0, 0, 0]
    assert [point.baseline_edge_retention_basis_points for point in report.points] == [
        10_000,
        4_000,
        0,
        0,
        0,
    ]
    assert all(point.stability_comparable for point in report.points)


def test_candidates_are_ranked_evidence_for_human_review_only() -> None:
    report = build_tag_association_sensitivity_report(_sample(), candidate_limit=2)

    assert [(item.left.name, item.right.name) for item in report.review_candidates] == [
        ("a", "c"),
        ("a", "b"),
    ]
    assert [item.rank for item in report.review_candidates] == [1, 2]
    assert report.review_candidates[0].survives_minimum_cooccurrence == (1, 2)
    assert all(
        item.review_state == "pending_human_review"
        for item in report.review_candidates
    )
    assert all(not hasattr(item, "semantic_label") for item in report.review_candidates)


def test_anchor_and_custom_thresholds_are_preserved() -> None:
    report = build_tag_association_sensitivity_report(
        _sample(), thresholds=(1, 2), anchor_tag="b"
    )

    assert report.anchor_tag == "b"
    assert [point.eligible_edge_count for point in report.points] == [3, 1]
    assert report.points[1].baseline_edge_retention_basis_points == 3_333


def test_empty_sample_is_explicit_and_does_not_claim_full_retention() -> None:
    report = build_tag_association_sensitivity_report(())

    assert report.baseline_edge_count == 0
    assert all(point.eligible_edge_count == 0 for point in report.points)
    assert all(
        point.baseline_edge_retention_basis_points == 0 for point in report.points
    )
    assert report.review_candidates == ()


@pytest.mark.parametrize(
    "thresholds,candidate_limit",
    [
        ((), 1),
        ((2, 3), 1),
        ((1, 1), 1),
        ((1, 3, 2), 1),
        (tuple(range(1, MAX_SENSITIVITY_THRESHOLDS + 2)), 1),
        ((1, 5_001), 1),
        ((1,), 0),
        ((1,), 201),
    ],
)
def test_invalid_or_unbounded_report_inputs_fail_closed(
    thresholds: tuple[int, ...], candidate_limit: int
) -> None:
    with pytest.raises(ValueError):
        build_tag_association_sensitivity_report(
            _sample(), thresholds=thresholds, candidate_limit=candidate_limit
        )
