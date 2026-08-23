from __future__ import annotations

import pytest

from pixiv_yuri.analytics.tag_associations import (
    MAX_EDGE_LIMIT,
    MAX_TAGS_PER_WORK,
    MAX_WORK_SAMPLE,
    TagDescriptor,
    TaggedWork,
    build_tag_association_graph,
)


def _tag(name: str) -> TagDescriptor:
    return TagDescriptor(name=name, translation=f"{name} translated")


def _sample() -> tuple[TaggedWork, ...]:
    return (
        TaggedWork("w1", (_tag("a"), _tag("b"), _tag("c"))),
        TaggedWork("w2", (_tag("a"), _tag("b"))),
        TaggedWork("w3", (_tag("a"), _tag("c"))),
        TaggedWork("w4", (_tag("a"), _tag("d"))),
        TaggedWork("w5", (_tag("b"), _tag("d"))),
    )


def test_builds_explainable_deterministic_associations() -> None:
    graph = build_tag_association_graph(_sample())

    assert graph.sampled_work_count == 5
    assert graph.observed_tag_count == 4
    assert graph.eligible_edge_count == 5
    assert graph.result_truncated is False
    assert [(edge.left.name, edge.right.name) for edge in graph.edges] == [
        ("a", "c"),
        ("a", "b"),
        ("b", "c"),
        ("b", "d"),
        ("a", "d"),
    ]
    first = graph.edges[0]
    assert first.left_work_count == 4
    assert first.right_work_count == 2
    assert first.cooccurrence_work_count == 2
    assert first.sample_support_basis_points == 4_000
    assert first.jaccard_basis_points == 5_000
    assert first.pmi_milli_bits == 322


def test_anchor_support_threshold_and_limit_are_explicit() -> None:
    graph = build_tag_association_graph(
        _sample(), anchor_tag="b", minimum_cooccurrence=1, limit=2
    )

    assert graph.anchor_tag == "b"
    assert graph.eligible_edge_count == 3
    assert graph.result_truncated is True
    assert [(edge.left.name, edge.right.name) for edge in graph.edges] == [
        ("a", "b"),
        ("b", "c"),
    ]

    supported = build_tag_association_graph(_sample(), minimum_cooccurrence=2)
    assert [(edge.left.name, edge.right.name) for edge in supported.edges] == [
        ("a", "c"),
        ("a", "b"),
    ]


def test_duplicate_tag_within_work_is_counted_once() -> None:
    tag = _tag("a")
    graph = build_tag_association_graph((TaggedWork("w1", (tag, tag)),))

    assert graph.observed_tag_count == 1
    assert graph.eligible_edge_count == 0
    assert graph.edges == ()


@pytest.mark.parametrize(
    "works,kwargs",
    [
        ((TaggedWork("", ()),), {}),
        ((TaggedWork("w", (_tag("a"),)), TaggedWork("w", (_tag("b"),))), {}),
        ((TaggedWork("w", tuple(_tag(str(i)) for i in range(MAX_TAGS_PER_WORK + 1))),), {}),
        (tuple(TaggedWork(str(i), ()) for i in range(MAX_WORK_SAMPLE + 1)), {}),
        ((), {"anchor_tag": ""}),
        ((), {"minimum_cooccurrence": 0}),
        ((), {"limit": MAX_EDGE_LIMIT + 1}),
    ],
)
def test_invalid_or_unbounded_inputs_fail_closed(
    works: tuple[TaggedWork, ...], kwargs: dict[str, object]
) -> None:
    with pytest.raises(ValueError):
        build_tag_association_graph(works, **kwargs)  # type: ignore[arg-type]


def test_conflicting_public_translations_fail_closed() -> None:
    works = (
        TaggedWork("w1", (TagDescriptor("a", "one"),)),
        TaggedWork("w2", (TagDescriptor("a", "two"),)),
    )

    with pytest.raises(ValueError, match="conflicting translations"):
        build_tag_association_graph(works)


def test_empty_sample_is_a_valid_empty_graph() -> None:
    graph = build_tag_association_graph(())

    assert graph.sampled_work_count == 0
    assert graph.observed_tag_count == 0
    assert graph.edges == ()
