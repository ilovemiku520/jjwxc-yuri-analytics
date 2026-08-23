"""Normalized current state and immutable snapshots for JJWXC metadata."""

from __future__ import annotations

from datetime import date as DateValue
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from pixiv_yuri.ingest.models import INGEST_SCHEMA
from pixiv_yuri.shared.database import PRIMARY_KEY_TYPE, Base, utc_now

JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")
NOVEL_STATUSES = "'连载','完结','暂停','锁定','未知'"
SOURCE_MODES = "'synthetic_fixture','public_candidate'"


class JjwxcAuthorRecord(Base):
    """Current public author identity without profile text or account data."""

    __tablename__ = "jjwxc_authors"
    __table_args__ = (
        Index("uq_jjwxc_authors_author_id", "author_id", unique=True),
        Index("ix_jjwxc_authors_display_name", "display_name"),
        {"schema": INGEST_SCHEMA},
    )

    id: Mapped[int] = mapped_column(PRIMARY_KEY_TYPE, primary_key=True, autoincrement=True)
    author_id: Mapped[str] = mapped_column(String(32), nullable=False)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class JjwxcNovelRecord(Base):
    """Current minimized novel projection updated only by newer snapshots."""

    __tablename__ = "jjwxc_novels"
    __table_args__ = (
        CheckConstraint(f"status IN ({NOVEL_STATUSES})", name="valid_jjwxc_novel_status"),
        Index("uq_jjwxc_novels_novel_id", "novel_id", unique=True),
        Index("ix_jjwxc_novels_author", "author_record_id"),
        Index("ix_jjwxc_novels_title", "title"),
        {"schema": INGEST_SCHEMA},
    )

    id: Mapped[int] = mapped_column(PRIMARY_KEY_TYPE, primary_key=True, autoincrement=True)
    novel_id: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    author_record_id: Mapped[int] = mapped_column(
        ForeignKey(f"{INGEST_SCHEMA}.jjwxc_authors.id", ondelete="RESTRICT"), nullable=False
    )
    novel_type: Mapped[str] = mapped_column(String(100), nullable=False)
    perspective: Mapped[str | None] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    tags: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, nullable=False, default=list)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    latest_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class JjwxcNovelSnapshot(Base):
    """Immutable aggregate metrics and non-reconstructable synopsis features."""

    __tablename__ = "jjwxc_novel_snapshots"
    __table_args__ = (
        CheckConstraint("word_count >= 0", name="nonnegative_jjwxc_snapshot_words"),
        CheckConstraint("review_count >= 0", name="nonnegative_jjwxc_snapshot_reviews"),
        CheckConstraint("favorite_count >= 0", name="nonnegative_jjwxc_snapshot_favorites"),
        CheckConstraint("points >= 0", name="nonnegative_jjwxc_snapshot_points"),
        CheckConstraint(
            "average_non_v_chapter_click_count IS NULL OR average_non_v_chapter_click_count >= 0",
            name="nonnegative_jjwxc_snapshot_clicks",
        ),
        CheckConstraint(
            "synopsis_char_count IS NULL OR synopsis_char_count >= 0",
            name="nonnegative_jjwxc_synopsis_chars",
        ),
        CheckConstraint(
            "synopsis_sentence_count IS NULL OR synopsis_sentence_count >= 0",
            name="nonnegative_jjwxc_synopsis_sentences",
        ),
        CheckConstraint(f"source_mode IN ({SOURCE_MODES})", name="valid_jjwxc_source_mode"),
        CheckConstraint("length(candidate_sha256) = 64", name="jjwxc_candidate_sha256_length"),
        Index("ix_jjwxc_snapshots_novel_time", "novel_record_id", "observed_at"),
        Index("uq_jjwxc_snapshots_candidate", "candidate_sha256", unique=True),
        Index(
            "uq_jjwxc_snapshots_novel_time",
            "novel_record_id",
            "observed_at",
            unique=True,
        ),
        {"schema": INGEST_SCHEMA},
    )

    id: Mapped[int] = mapped_column(PRIMARY_KEY_TYPE, primary_key=True, autoincrement=True)
    novel_record_id: Mapped[int] = mapped_column(
        ForeignKey(f"{INGEST_SCHEMA}.jjwxc_novels.id", ondelete="CASCADE"), nullable=False
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    word_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    review_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    favorite_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    points: Mapped[int] = mapped_column(BigInteger, nullable=False)
    average_non_v_chapter_click_count: Mapped[int | None] = mapped_column(BigInteger)
    synopsis_char_count: Mapped[int | None] = mapped_column(Integer)
    synopsis_sentence_count: Mapped[int | None] = mapped_column(Integer)
    synopsis_theme_terms: Mapped[list[str]] = mapped_column(
        JSON_DOCUMENT, nullable=False, default=list
    )
    source_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    candidate_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class JjwxcRankingSnapshot(Base):
    """One daily position from a fixed allowlisted public ranking."""

    __tablename__ = "jjwxc_ranking_snapshots"
    __table_args__ = (
        CheckConstraint("rank >= 1 AND rank <= 200", name="valid_jjwxc_ranking_position"),
        CheckConstraint("word_count >= 0", name="nonnegative_jjwxc_ranking_words"),
        CheckConstraint("points >= 0", name="nonnegative_jjwxc_ranking_points"),
        Index(
            "uq_jjwxc_ranking_day_novel",
            "ranking_key",
            "observation_day",
            "novel_id",
            unique=True,
        ),
        Index(
            "uq_jjwxc_ranking_day_position",
            "ranking_key",
            "observation_day",
            "rank",
            unique=True,
        ),
        Index("ix_jjwxc_ranking_novel_time", "novel_id", "observation_day"),
        {"schema": INGEST_SCHEMA},
    )

    id: Mapped[int] = mapped_column(PRIMARY_KEY_TYPE, primary_key=True, autoincrement=True)
    ranking_key: Mapped[str] = mapped_column(String(64), nullable=False)
    observation_day: Mapped[DateValue] = mapped_column(Date, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    novel_id: Mapped[str] = mapped_column(String(32), nullable=False)
    author_id: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    author_display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    novel_type: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    word_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    points: Mapped[int] = mapped_column(BigInteger, nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
