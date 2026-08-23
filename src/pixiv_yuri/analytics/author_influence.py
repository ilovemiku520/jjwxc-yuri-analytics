"""Deterministic author influence scoring over reviewed complete metrics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

MODEL_VERSION = "allowed-metadata-v1"
QualityQuadrant = Literal["core", "boutique", "ordinary", "volume"]


@dataclass(frozen=True, slots=True)
class AuthorInfluenceWeights:
    """Integer basis-point weights restricted to approved score components."""

    bookmark: int = 4_375
    like: int = 3_750
    production: int = 1_875

    def validate(self) -> None:
        values = (self.bookmark, self.like, self.production)
        if any(value < 0 or value > 10_000 for value in values) or sum(values) != 10_000:
            raise ValueError("influence weights must be bounded and total 10000")


@dataclass(frozen=True, slots=True)
class AuthorInfluenceInput:
    author_id: str
    author_display_name: str
    work_count: int
    average_bookmark_count_x100: int
    average_like_count_x100: int


@dataclass(frozen=True, slots=True)
class AuthorInfluenceScore:
    author_id: str
    author_display_name: str
    work_count: int
    average_bookmark_count_x100: int
    average_like_count_x100: int
    bookmark_component_basis_points: int
    like_component_basis_points: int
    production_component_basis_points: int
    influence_score_basis_points: int


def score_author_influence(
    authors: list[AuthorInfluenceInput],
    weights: AuthorInfluenceWeights,
    *,
    limit: int,
) -> tuple[AuthorInfluenceScore, ...]:
    """Normalize within one explicit sample and return a stable bounded ranking."""
    weights.validate()
    if limit < 1 or limit > 100:
        raise ValueError("influence ranking limit must be between 1 and 100")
    if not authors:
        return ()
    if any(
        not author.author_id
        or author.work_count < 1
        or author.average_bookmark_count_x100 < 0
        or author.average_like_count_x100 < 0
        for author in authors
    ):
        raise ValueError("influence inputs are invalid")

    max_bookmarks = max(author.average_bookmark_count_x100 for author in authors)
    max_likes = max(author.average_like_count_x100 for author in authors)
    max_works = max(author.work_count for author in authors)
    scores = tuple(
        _score_one(
            author,
            weights,
            max_bookmarks=max_bookmarks,
            max_likes=max_likes,
            max_works=max_works,
        )
        for author in authors
    )
    return tuple(
        sorted(
            scores,
            key=lambda item: (-item.influence_score_basis_points, item.author_id),
        )[:limit]
    )


def classify_author_quality(
    *,
    work_count_x100: int,
    average_bookmarks_x100: int,
    work_threshold_x100: int,
    bookmark_threshold_x100: int,
) -> QualityQuadrant:
    """Classify one point against explicit sample-relative thresholds."""
    high_volume = work_count_x100 >= work_threshold_x100
    high_quality = average_bookmarks_x100 >= bookmark_threshold_x100
    if high_volume and high_quality:
        return "core"
    if high_quality:
        return "boutique"
    if high_volume:
        return "volume"
    return "ordinary"


def _score_one(
    author: AuthorInfluenceInput,
    weights: AuthorInfluenceWeights,
    *,
    max_bookmarks: int,
    max_likes: int,
    max_works: int,
) -> AuthorInfluenceScore:
    bookmark_component = _relative_basis_points(
        author.average_bookmark_count_x100, max_bookmarks
    )
    like_component = _relative_basis_points(author.average_like_count_x100, max_likes)
    production_component = _relative_basis_points(author.work_count, max_works)
    weighted_total = (
        bookmark_component * weights.bookmark
        + like_component * weights.like
        + production_component * weights.production
    )
    return AuthorInfluenceScore(
        author_id=author.author_id,
        author_display_name=author.author_display_name,
        work_count=author.work_count,
        average_bookmark_count_x100=author.average_bookmark_count_x100,
        average_like_count_x100=author.average_like_count_x100,
        bookmark_component_basis_points=bookmark_component,
        like_component_basis_points=like_component,
        production_component_basis_points=production_component,
        influence_score_basis_points=(weighted_total + 5_000) // 10_000,
    )


def _relative_basis_points(value: int, maximum: int) -> int:
    if maximum == 0:
        return 0
    return (value * 10_000 + maximum // 2) // maximum
