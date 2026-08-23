"""Inspectable cohort-relative ratings for minimized JJWXC metadata."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from math import log1p
from statistics import fmean
from typing import Literal, cast

from pixiv_yuri.jjwxc.analytics import NOVEL_METRICS, correlation_matrix, metric_summary
from pixiv_yuri.jjwxc.models import JjwxcNovel

RatingMetric = Literal["reviews", "favorites", "points", "words", "clicks"]
RatingGrade = Literal["SSS", "SS", "S", "A", "B"]

RATING_METRICS: tuple[RatingMetric, ...] = (
    "reviews",
    "favorites",
    "points",
    "words",
    "clicks",
)

_ATTRIBUTES: dict[RatingMetric, str] = {
    "reviews": "review_count",
    "favorites": "favorite_count",
    "points": "points",
    "words": "word_count",
    "clicks": "average_non_v_chapter_click_count",
}

# Product priors preserve the meaning of a public-data performance score. The
# observed sample adjusts them, but a tiny or highly correlated cohort cannot
# turn word count into the dominant signal by accident.
_PRODUCT_PRIORS: dict[RatingMetric, float] = {
    "reviews": 0.25,
    "favorites": 0.30,
    "points": 0.20,
    "words": 0.10,
    "clicks": 0.15,
}


@dataclass(frozen=True, slots=True)
class RatingEntity:
    entity_id: str
    title: str
    author_display_name: str
    values: dict[RatingMetric, float | None]


def evidence_weight_basis_points(novels: tuple[JjwxcNovel, ...]) -> dict[RatingMetric, int]:
    """Blend product priors with coverage, dispersion, and redundancy evidence."""
    definitions = {item.name: item for item in NOVEL_METRICS if item.name in RATING_METRICS}
    summaries = {
        metric: metric_summary(novels, definitions[metric]) for metric in RATING_METRICS
    }
    correlations = correlation_matrix(novels)
    evidence: dict[RatingMetric, float] = {}
    for metric in RATING_METRICS:
        summary = summaries[metric]
        related = [
            abs(float(cast(float, cell["coefficient"])))
            for cell in correlations
            if cell["x_metric"] == metric
            and cell["y_metric"] in RATING_METRICS
            and cell["y_metric"] != metric
            and cell["coefficient"] is not None
        ]
        coverage = cast(int, summary["coverage_basis_points"]) / 10_000
        dispersion_value = cast(float | None, summary["coefficient_of_variation"])
        dispersion = min(dispersion_value or 0.0, 2.0)
        redundancy = fmean(related) if related else 0.0
        evidence[metric] = max(0.05, coverage * dispersion / (1.0 + redundancy))

    evidence_ceiling = max(evidence.values(), default=1.0)
    adjusted = {
        metric: _PRODUCT_PRIORS[metric]
        * (0.5 + 0.5 * evidence[metric] / evidence_ceiling)
        for metric in RATING_METRICS
    }
    return _normalized_basis_points(adjusted)


def build_novel_entities(novels: tuple[JjwxcNovel, ...]) -> tuple[RatingEntity, ...]:
    return tuple(
        RatingEntity(
            entity_id=novel.novel_id,
            title=novel.title,
            author_display_name=novel.author_display_name,
            values={
                metric: (
                    float(value)
                    if (value := getattr(novel, _ATTRIBUTES[metric])) is not None
                    else None
                )
                for metric in RATING_METRICS
            },
        )
        for novel in novels
    )


def build_author_entities(novels: tuple[JjwxcNovel, ...]) -> tuple[RatingEntity, ...]:
    grouped: dict[str, list[JjwxcNovel]] = defaultdict(list)
    for novel in novels:
        grouped[novel.author_id].append(novel)
    entities: list[RatingEntity] = []
    for author_id, works in grouped.items():
        clicks = [
            item.average_non_v_chapter_click_count
            for item in works
            if item.average_non_v_chapter_click_count is not None
        ]
        entities.append(
            RatingEntity(
                entity_id=author_id,
                title=works[0].author_display_name,
                author_display_name=works[0].author_display_name,
                values={
                    "reviews": float(sum(item.review_count for item in works)),
                    "favorites": float(sum(item.favorite_count for item in works)),
                    "points": float(sum(item.points for item in works)),
                    "words": float(sum(item.word_count for item in works)),
                    "clicks": fmean(clicks) if clicks else None,
                },
            )
        )
    return tuple(entities)


def score_entities(
    entities: tuple[RatingEntity, ...], weights: dict[RatingMetric, int]
) -> tuple[dict[str, object], ...]:
    """Return log-scaled percentile components and weighted 0-100 scores."""
    normalized_weights = _normalized_basis_points(
        {metric: max(0.0, float(weights.get(metric, 0))) for metric in RATING_METRICS}
    )
    component_scores = {
        metric: _percentile_scores(
            {
                entity.entity_id: value
                for entity in entities
                if (value := entity.values[metric]) is not None
            }
        )
        for metric in RATING_METRICS
    }
    rows: list[dict[str, object]] = []
    for entity in entities:
        available = [
            metric
            for metric in RATING_METRICS
            if entity.values[metric] is not None and normalized_weights[metric] > 0
        ]
        observed_weight = sum(normalized_weights[metric] for metric in available)
        score = (
            sum(
                component_scores[metric][entity.entity_id] * normalized_weights[metric]
                for metric in available
            )
            / observed_weight
            if observed_weight
            else 0.0
        )
        score_basis_points = round(score * 100)
        rows.append(
            {
                "entity_id": entity.entity_id,
                "title": entity.title,
                "author_display_name": entity.author_display_name,
                "score_basis_points": score_basis_points,
                "grade": grade_for_score(score_basis_points),
                "coverage_basis_points": round(len(available) * 10_000 / len(RATING_METRICS)),
                "component_scores": {
                    metric: (
                        round(component_scores[metric][entity.entity_id] * 100)
                        if entity.values[metric] is not None
                        else None
                    )
                    for metric in RATING_METRICS
                },
            }
        )
    return tuple(
        sorted(
            rows,
            key=lambda row: (
                -cast(int, row["score_basis_points"]),
                cast(str, row["entity_id"]),
            ),
        )
    )


def grade_for_score(score_basis_points: int) -> RatingGrade:
    if score_basis_points >= 9_000:
        return "SSS"
    if score_basis_points >= 8_000:
        return "SS"
    if score_basis_points >= 6_500:
        return "S"
    if score_basis_points >= 4_500:
        return "A"
    return "B"


def _percentile_scores(values: dict[str, float]) -> dict[str, float]:
    transformed = {entity_id: log1p(value) for entity_id, value in values.items()}
    ordered = sorted(transformed.values())
    if len(ordered) <= 1:
        return {entity_id: 100.0 for entity_id in transformed}
    scores: dict[str, float] = {}
    for entity_id, value in transformed.items():
        lower = sum(candidate < value for candidate in ordered)
        equal = sum(candidate == value for candidate in ordered)
        average_rank = lower + (equal - 1) / 2
        scores[entity_id] = average_rank * 100 / (len(ordered) - 1)
    return scores


def _normalized_basis_points(values: dict[RatingMetric, float]) -> dict[RatingMetric, int]:
    total = sum(values.values())
    if total <= 0:
        raise ValueError("rating weights must include at least one positive value")
    exact = {metric: values[metric] * 10_000 / total for metric in RATING_METRICS}
    rounded = {metric: int(exact[metric]) for metric in RATING_METRICS}
    remainder = 10_000 - sum(rounded.values())
    for metric in sorted(
        RATING_METRICS,
        key=lambda item: (exact[item] - rounded[item], item),
        reverse=True,
    )[:remainder]:
        rounded[metric] += 1
    return rounded
