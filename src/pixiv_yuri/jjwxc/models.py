"""Strict models for minimized JJWXC novel and author metadata."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator


class JjwxcNovel(BaseModel):
    """One normalized novel snapshot without raw synopsis, chapter text, or comments."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    novel_id: str = Field(pattern=r"^[1-9][0-9]{0,11}$")
    title: str = Field(min_length=1, max_length=200)
    author_id: str = Field(pattern=r"^[1-9][0-9]{0,11}$")
    author_display_name: str = Field(min_length=1, max_length=80)
    novel_type: str = Field(min_length=1, max_length=100)
    perspective: str | None = Field(default=None, max_length=30)
    status: Literal["连载", "完结", "暂停", "锁定", "未知"]
    word_count: int = Field(ge=0)
    review_count: int = Field(ge=0)
    favorite_count: int = Field(ge=0)
    points: int = Field(ge=0)
    average_non_v_chapter_click_count: int | None = Field(default=None, ge=0)
    average_v_chapter_click_count: int | None = Field(default=None, ge=0)
    non_v_chapter_count: int = Field(default=0, ge=0)
    v_chapter_count: int = Field(default=0, ge=0)
    chapter_click_coverage_count: int = Field(default=0, ge=0)
    synopsis_char_count: int | None = Field(default=None, ge=0, le=100_000)
    synopsis_sentence_count: int | None = Field(default=None, ge=0, le=10_000)
    synopsis_theme_terms: tuple[str, ...] = Field(default=(), max_length=12)
    tags: tuple[str, ...] = Field(default=(), max_length=20)
    observed_at: datetime
    source_mode: Literal["synthetic_fixture", "public_candidate"]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def v_to_non_v_click_retention_basis_points(self) -> int | None:
        """Return the V/non-V chapter-click ratio without treating missing clicks as zero."""
        non_v_clicks = self.average_non_v_chapter_click_count
        v_clicks = self.average_v_chapter_click_count
        if non_v_clicks is None or v_clicks is None or non_v_clicks <= 0:
            return None
        return round(v_clicks * 10_000 / non_v_clicks)

    @field_validator("observed_at")
    @classmethod
    def require_aware_observation(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at must include a timezone")
        return value

    @field_validator("tags")
    @classmethod
    def validate_unique_tags(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("tags must be unique")
        if any(not item.strip() or len(item) > 40 for item in value):
            raise ValueError("tag is outside the minimized display contract")
        return value

    @field_validator("synopsis_theme_terms")
    @classmethod
    def validate_theme_terms(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("synopsis theme terms must be unique")
        if any(not item.strip() or len(item) > 20 for item in value):
            raise ValueError("synopsis theme term is outside the minimized contract")
        return value


class JjwxcNovelCandidate(JjwxcNovel):
    """A one-request public candidate that has not entered canonical storage."""

    source_mode: Literal["public_candidate"] = "public_candidate"
    source_url: str = Field(
        pattern=r"^https://www\.jjwxc\.net/onebook\.php\?novelid=[1-9][0-9]{0,11}$"
    )


class JjwxcChapterMetric(BaseModel):
    """Copyright-minimized chapter metadata; titles and summaries are never retained."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    chapter_id: int = Field(ge=1, le=1_000_000)
    position: int = Field(ge=1, le=1_000_000)
    is_vip: bool
    word_count: int = Field(ge=0)
    click_count: int | None = Field(default=None, ge=0)


class JjwxcCatalogSearchItem(BaseModel):
    """One lightweight full-site catalog hit, optionally linked to detailed analytics."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    novel_id: str = Field(pattern=r"^[1-9][0-9]{0,11}$")
    title: str = Field(min_length=1, max_length=200)
    author_id: str = Field(pattern=r"^[1-9][0-9]{0,11}$")
    author_display_name: str = Field(min_length=1, max_length=80)
    novel_type: str = Field(min_length=1, max_length=100)
    status: Literal["连载", "完结", "暂停", "锁定", "未知"]
    word_count: int = Field(ge=0)
    points: int = Field(ge=0)
    published_at: datetime | None
    last_seen_at: datetime
    detail_available: bool


class JjwxcDistributionSummary(BaseModel):
    """One daily cross-sectional distribution with robust comparison bands."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    observed_count: int = Field(ge=0)
    top_group_count: int = Field(ge=0, le=10)
    bottom_group_count: int = Field(ge=0, le=10)
    top_mean: float | None = Field(default=None, ge=0)
    bottom_mean: float | None = Field(default=None, ge=0)
    lower_whisker: float | None = Field(default=None, ge=0)
    p25: float | None = Field(default=None, ge=0)
    median: float | None = Field(default=None, ge=0)
    p75: float | None = Field(default=None, ge=0)
    upper_whisker: float | None = Field(default=None, ge=0)
    outliers: tuple[float, ...] = ()


class JjwxcTrendPoint(BaseModel):
    """Synthetic or canonical daily aggregate used by the private dashboard."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    day: str = Field(pattern=r"^20[0-9]{2}-[0-9]{2}-[0-9]{2}$")
    observed_novel_count: int = Field(ge=0)
    total_review_count: int = Field(ge=0)
    total_favorite_count: int = Field(ge=0)
    total_points: int = Field(ge=0)
    total_word_count: int = Field(ge=0)
    click_coverage_count: int = Field(ge=0)
    mean_non_v_chapter_click_count: float | None = Field(default=None, ge=0)
    v_click_coverage_count: int = Field(default=0, ge=0)
    mean_v_chapter_click_count: float | None = Field(default=None, ge=0)
    metric_distributions: dict[
        Literal["reviews", "favorites", "points", "words", "clicks", "v_clicks"],
        JjwxcDistributionSummary,
    ] = Field(default_factory=dict)
