"""Deterministic descriptive analytics for minimized JJWXC snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from math import log1p, sqrt
from statistics import fmean, median, pstdev
from typing import Literal

from pixiv_yuri.jjwxc.models import (
    JjwxcDistributionSummary,
    JjwxcNovel,
    JjwxcTrendPoint,
)

MetricName = Literal[
    "reviews",
    "favorites",
    "nutrition",
    "first_clicks",
    "loyalty",
    "click_favorite",
    "points",
    "words",
    "clicks",
    "v_clicks",
    "v_retention",
    "synopsis_chars",
]
TimelineMetricName = Literal[
    "reviews",
    "favorites",
    "points",
    "words",
    "clicks",
    "v_clicks",
]


@dataclass(frozen=True)
class MetricDefinition:
    name: MetricName
    label: str
    attribute: str
    scale_divisor: float = 1.0


NOVEL_METRICS = (
    MetricDefinition("reviews", "总书评数", "review_count"),
    MetricDefinition("favorites", "当前被收藏数", "favorite_count"),
    MetricDefinition("nutrition", "营养液数", "nutrition_count"),
    MetricDefinition("first_clicks", "首章点击数", "first_chapter_click_count"),
    MetricDefinition(
        "loyalty",
        "营养液/收藏投入比（代理）",
        "nutrition_to_favorite_basis_points",
        10_000.0,
    ),
    MetricDefinition(
        "click_favorite",
        "首章点击/收藏转化比（代理）",
        "first_click_to_favorite_basis_points",
        10_000.0,
    ),
    MetricDefinition("points", "文章积分", "points"),
    MetricDefinition("words", "全文字数", "word_count"),
    MetricDefinition("clicks", "非 V 章节章均点击数", "average_non_v_chapter_click_count"),
    MetricDefinition("v_clicks", "V 章节章均点击数", "average_v_chapter_click_count"),
    MetricDefinition(
        "v_retention",
        "V/非 V 点击留存比（代理）",
        "v_to_non_v_click_retention_basis_points",
        10_000.0,
    ),
    MetricDefinition("synopsis_chars", "文案字符数", "synopsis_char_count"),
)

CORRELATION_METRICS = tuple(
    definition for definition in NOVEL_METRICS if definition.name != "v_clicks"
)

_TIMELINE_ATTRIBUTES: dict[TimelineMetricName, str] = {
    "reviews": "total_review_count",
    "favorites": "total_favorite_count",
    "points": "total_points",
    "words": "total_word_count",
    "clicks": "mean_non_v_chapter_click_count",
    "v_clicks": "mean_v_chapter_click_count",
}


def metric_summary(
    novels: tuple[JjwxcNovel, ...], definition: MetricDefinition
) -> dict[str, object]:
    """Summarize one cross-sectional metric while preserving missingness."""
    values = [
        float(value) / definition.scale_divisor
        for novel in novels
        if (value := getattr(novel, definition.attribute)) is not None
    ]
    observed_count = len(values)
    missing_count = len(novels) - observed_count
    coverage_basis_points = round(observed_count * 10_000 / len(novels)) if novels else 0
    if not values:
        return {
            "metric": definition.name,
            "label": definition.label,
            "observed_count": 0,
            "missing_count": missing_count,
            "coverage_basis_points": coverage_basis_points,
            "minimum": None,
            "maximum": None,
            "mean": None,
            "median": None,
            "standard_deviation": None,
            "p25": None,
            "p75": None,
            "coefficient_of_variation": None,
        }
    mean = fmean(values)
    deviation = pstdev(values)
    return {
        "metric": definition.name,
        "label": definition.label,
        "observed_count": observed_count,
        "missing_count": missing_count,
        "coverage_basis_points": coverage_basis_points,
        "minimum": min(values),
        "maximum": max(values),
        "mean": mean,
        "median": median(values),
        "standard_deviation": deviation,
        "p25": _percentile(values, 0.25),
        "p75": _percentile(values, 0.75),
        "coefficient_of_variation": deviation / mean if mean else None,
    }


def distribution_summary(
    values: list[int | float], *, group_size: int = 10
) -> JjwxcDistributionSummary:
    """Summarize one daily slice for top/bottom means and a Tukey box plot."""
    if not 1 <= group_size <= 10:
        raise ValueError("distribution_group_size_out_of_range")
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return JjwxcDistributionSummary(observed_count=0, top_group_count=0, bottom_group_count=0)
    p25 = _percentile(ordered, 0.25)
    middle = _percentile(ordered, 0.5)
    p75 = _percentile(ordered, 0.75)
    iqr = p75 - p25
    lower_fence = p25 - 1.5 * iqr
    upper_fence = p75 + 1.5 * iqr
    inliers = [value for value in ordered if lower_fence <= value <= upper_fence]
    selected_count = min(group_size, len(ordered))
    return JjwxcDistributionSummary(
        observed_count=len(ordered),
        top_group_count=selected_count,
        bottom_group_count=selected_count,
        top_mean=fmean(ordered[-selected_count:]),
        bottom_mean=fmean(ordered[:selected_count]),
        lower_whisker=min(inliers) if inliers else ordered[0],
        p25=p25,
        median=middle,
        p75=p75,
        upper_whisker=max(inliers) if inliers else ordered[-1],
        outliers=tuple(
            value for value in ordered if value < lower_fence or value > upper_fence
        ),
    )


def research_indicator_summary(novels: tuple[JjwxcNovel, ...]) -> dict[str, object]:
    """Build cohort-level reader-input proxies without imputing unavailable values."""
    nutrition_observed = [item for item in novels if item.nutrition_count is not None]
    nutrition_sum = sum(item.nutrition_count or 0 for item in nutrition_observed)
    favorite_sum = sum(item.favorite_count for item in nutrition_observed)
    click_favorite_ratios = [
        item.first_chapter_click_count / item.favorite_count
        for item in novels
        if item.first_chapter_click_count is not None and item.favorite_count > 0
    ]
    serial_nutrition = [
        item.nutrition_count
        for item in novels
        if item.status == "连载" and item.nutrition_count is not None
    ]
    completed_nutrition = [
        item.nutrition_count
        for item in novels
        if item.status == "完结" and item.nutrition_count is not None
    ]
    serial_mean = fmean(serial_nutrition) if serial_nutrition else None
    completed_mean = fmean(completed_nutrition) if completed_nutrition else None
    return {
        "cohort_count": len(novels),
        "nutrition_observed_count": len(nutrition_observed),
        "nutrition_coverage_basis_points": (
            round(len(nutrition_observed) * 10_000 / len(novels)) if novels else 0
        ),
        "loyalty_ratio": nutrition_sum / favorite_sum if favorite_sum else None,
        "click_favorite_observed_count": len(click_favorite_ratios),
        "median_click_favorite_ratio": (
            median(click_favorite_ratios) if click_favorite_ratios else None
        ),
        "serial_nutrition_observed_count": len(serial_nutrition),
        "serial_nutrition_mean": serial_mean,
        "completed_nutrition_observed_count": len(completed_nutrition),
        "completed_nutrition_mean": completed_mean,
        "completed_to_serial_nutrition_ratio": (
            completed_mean / serial_mean
            if completed_mean is not None and serial_mean is not None and serial_mean > 0
            else None
        ),
    }


def correlation_matrix(novels: tuple[JjwxcNovel, ...]) -> tuple[dict[str, object], ...]:
    """Return pairwise-complete Pearson r after log1p and z-score normalization."""
    cells: list[dict[str, object]] = []
    for y_definition in CORRELATION_METRICS:
        for x_definition in CORRELATION_METRICS:
            pairs = [
                (
                    float(x_value) / x_definition.scale_divisor,
                    float(y_value) / y_definition.scale_divisor,
                )
                for novel in novels
                if (x_value := getattr(novel, x_definition.attribute)) is not None
                and (y_value := getattr(novel, y_definition.attribute)) is not None
            ]
            cells.append(
                {
                    "x_metric": x_definition.name,
                    "y_metric": y_definition.name,
                    "paired_count": len(pairs),
                    "coefficient": _log_standardized_pearson(pairs),
                }
            )
    return tuple(cells)


def normalized_timeline(
    trends: tuple[JjwxcTrendPoint, ...],
) -> tuple[dict[str, object], ...]:
    """Index each aggregate series to its first non-zero observation (10000 = 100%)."""
    baselines: dict[TimelineMetricName, float | None] = {}
    for metric, attribute in _TIMELINE_ATTRIBUTES.items():
        baselines[metric] = next(
            (
                float(value)
                for point in trends
                if (value := getattr(point, attribute)) is not None and float(value) != 0
            ),
            None,
        )
    normalized: list[dict[str, object]] = []
    for point in trends:
        values: dict[str, int | None] = {}
        for metric, attribute in _TIMELINE_ATTRIBUTES.items():
            value = getattr(point, attribute)
            baseline = baselines[metric]
            values[metric] = (
                round(float(value) * 10_000 / baseline)
                if value is not None and baseline is not None
                else None
            )
        normalized.append({"day": point.day, "values": values})
    return tuple(normalized)


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _pearson(pairs: list[tuple[float, float]]) -> float | None:
    if len(pairs) < 2:
        return None
    x_values = [pair[0] for pair in pairs]
    y_values = [pair[1] for pair in pairs]
    x_mean = fmean(x_values)
    y_mean = fmean(y_values)
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in pairs)
    x_scale = sqrt(sum((x - x_mean) ** 2 for x in x_values))
    y_scale = sqrt(sum((y - y_mean) ** 2 for y in y_values))
    if x_scale == 0 or y_scale == 0:
        return None
    return max(-1.0, min(1.0, numerator / (x_scale * y_scale)))


def _log_standardized_pearson(pairs: list[tuple[float, float]]) -> float | None:
    """Reduce heavy-tail leverage, then explicitly standardize both paired series."""
    if len(pairs) < 2:
        return None
    transformed = [(log1p(x), log1p(y)) for x, y in pairs]
    x_values = [pair[0] for pair in transformed]
    y_values = [pair[1] for pair in transformed]
    x_mean = fmean(x_values)
    y_mean = fmean(y_values)
    x_scale = pstdev(x_values)
    y_scale = pstdev(y_values)
    if x_scale == 0 or y_scale == 0:
        return None
    standardized = [((x - x_mean) / x_scale, (y - y_mean) / y_scale) for x, y in transformed]
    return _pearson(standardized)
