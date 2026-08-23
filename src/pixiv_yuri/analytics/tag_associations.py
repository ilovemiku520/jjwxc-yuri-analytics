"""Bounded, explainable tag co-occurrence metrics over reviewed catalog tags."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from itertools import combinations
from math import log2

MAX_WORK_SAMPLE = 5_000
MAX_TAGS_PER_WORK = 64
MAX_EDGE_LIMIT = 200


@dataclass(frozen=True, slots=True)
class TagDescriptor:
    """One reviewed public tag identity and its optional public translation."""

    name: str
    translation: str | None = None


@dataclass(frozen=True, slots=True)
class TaggedWork:
    """One sampled work represented only by its reviewed public tags."""

    work_id: str
    tags: tuple[TagDescriptor, ...]


@dataclass(frozen=True, slots=True)
class TagAssociationEdge:
    """A descriptive association; it is not a semantic or Yuri classification."""

    left: TagDescriptor
    right: TagDescriptor
    left_work_count: int
    right_work_count: int
    cooccurrence_work_count: int
    sample_support_basis_points: int
    jaccard_basis_points: int
    pmi_milli_bits: int


@dataclass(frozen=True, slots=True)
class TagAssociationGraph:
    """A bounded result with enough sample metadata to interpret every edge."""

    sampled_work_count: int
    observed_tag_count: int
    eligible_edge_count: int
    result_truncated: bool
    anchor_tag: str | None
    minimum_cooccurrence: int
    edges: tuple[TagAssociationEdge, ...]


def build_tag_association_graph(
    works: tuple[TaggedWork, ...],
    *,
    anchor_tag: str | None = None,
    minimum_cooccurrence: int = 1,
    limit: int = 100,
) -> TagAssociationGraph:
    """Calculate deterministic support, Jaccard and PMI from a bounded work sample."""
    if len(works) > MAX_WORK_SAMPLE:
        raise ValueError("work sample exceeds the bounded maximum")
    if not 1 <= minimum_cooccurrence <= MAX_WORK_SAMPLE:
        raise ValueError("minimum_cooccurrence is outside the bounded range")
    if not 1 <= limit <= MAX_EDGE_LIMIT:
        raise ValueError("limit is outside the bounded range")
    if anchor_tag is not None and not anchor_tag:
        raise ValueError("anchor_tag must not be empty")

    tag_counts: Counter[str] = Counter()
    pair_counts: Counter[tuple[str, str]] = Counter()
    descriptors: dict[str, TagDescriptor] = {}
    seen_work_ids: set[str] = set()

    for work in works:
        if not work.work_id or work.work_id in seen_work_ids:
            raise ValueError("work identifiers must be non-empty and unique")
        seen_work_ids.add(work.work_id)
        if len(work.tags) > MAX_TAGS_PER_WORK:
            raise ValueError("work tag count exceeds the bounded maximum")

        unique_names: set[str] = set()
        for tag in work.tags:
            if not tag.name:
                raise ValueError("tag names must not be empty")
            existing = descriptors.get(tag.name)
            if existing is not None and existing.translation != tag.translation:
                raise ValueError("one tag name has conflicting translations")
            descriptors[tag.name] = tag
            unique_names.add(tag.name)

        ordered_names = sorted(unique_names)
        tag_counts.update(ordered_names)
        pair_counts.update(combinations(ordered_names, 2))

    sample_size = len(works)
    edges: list[TagAssociationEdge] = []
    for (left_name, right_name), cooccurrence in pair_counts.items():
        if cooccurrence < minimum_cooccurrence:
            continue
        if anchor_tag is not None and anchor_tag not in (left_name, right_name):
            continue
        left_count = tag_counts[left_name]
        right_count = tag_counts[right_name]
        union_count = left_count + right_count - cooccurrence
        edges.append(
            TagAssociationEdge(
                left=descriptors[left_name],
                right=descriptors[right_name],
                left_work_count=left_count,
                right_work_count=right_count,
                cooccurrence_work_count=cooccurrence,
                sample_support_basis_points=_ratio_basis_points(
                    cooccurrence, sample_size
                ),
                jaccard_basis_points=_ratio_basis_points(cooccurrence, union_count),
                pmi_milli_bits=_pmi_milli_bits(
                    cooccurrence=cooccurrence,
                    sample_size=sample_size,
                    left_count=left_count,
                    right_count=right_count,
                ),
            )
        )

    edges.sort(
        key=lambda edge: (
            -edge.cooccurrence_work_count,
            -edge.jaccard_basis_points,
            -edge.pmi_milli_bits,
            edge.left.name,
            edge.right.name,
        )
    )
    eligible_count = len(edges)
    return TagAssociationGraph(
        sampled_work_count=sample_size,
        observed_tag_count=len(tag_counts),
        eligible_edge_count=eligible_count,
        result_truncated=eligible_count > limit,
        anchor_tag=anchor_tag,
        minimum_cooccurrence=minimum_cooccurrence,
        edges=tuple(edges[:limit]),
    )


def _ratio_basis_points(numerator: int, denominator: int) -> int:
    if denominator <= 0:
        return 0
    return (numerator * 10_000 + denominator // 2) // denominator


def _pmi_milli_bits(
    *,
    cooccurrence: int,
    sample_size: int,
    left_count: int,
    right_count: int,
) -> int:
    if cooccurrence <= 0 or sample_size <= 0 or left_count <= 0 or right_count <= 0:
        raise ValueError("PMI inputs must be positive")
    scaled = log2((cooccurrence * sample_size) / (left_count * right_count)) * 1_000
    return int(scaled + 0.5) if scaled >= 0 else int(scaled - 0.5)
