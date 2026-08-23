"""Minimal normalized catalog constrained to reviewed metadata fields."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from pixiv_yuri.ingest.models import INGEST_SCHEMA
from pixiv_yuri.shared.database import PRIMARY_KEY_TYPE, Base, utc_now


class CatalogAuthor(Base):
    """One normalized author identity without profile or credential data."""

    __tablename__ = "catalog_authors"
    id: Mapped[int] = mapped_column(PRIMARY_KEY_TYPE, primary_key=True, autoincrement=True)
    source_system: Mapped[str] = mapped_column(String(64), nullable=False)
    author_id: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    latest_observation_id: Mapped[int] = mapped_column(
        ForeignKey(f"{INGEST_SCHEMA}.raw_observations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_catalog_authors_display_name", "display_name"),
        Index("ix_catalog_authors_author_id", "author_id"),
        Index(
            "uq_catalog_authors_source_identity",
            "source_system",
            "author_id",
            unique=True,
        ),
        {"schema": INGEST_SCHEMA},
    )


class CatalogWork(Base):
    """One current work projection containing only reviewed public metadata."""

    __tablename__ = "catalog_works"
    __table_args__ = (
        CheckConstraint("page_count >= 1", name="positive_catalog_work_page_count"),
        CheckConstraint("width IS NULL OR width >= 1", name="positive_catalog_work_width"),
        CheckConstraint("height IS NULL OR height >= 1", name="positive_catalog_work_height"),
        CheckConstraint(
            "public_view_count IS NULL OR public_view_count >= 0",
            name="nonnegative_catalog_work_views",
        ),
        CheckConstraint(
            "public_bookmark_count IS NULL OR public_bookmark_count >= 0",
            name="nonnegative_catalog_work_bookmarks",
        ),
        CheckConstraint(
            "public_like_count IS NULL OR public_like_count >= 0",
            name="nonnegative_catalog_work_likes",
        ),
        Index("ix_catalog_works_created_at", "created_at"),
        Index("ix_catalog_works_author", "author_id"),
        Index("ix_catalog_works_title", "title"),
        Index("ix_catalog_works_work_id", "work_id"),
        Index("ix_catalog_works_like_rank", "public_like_count", "id"),
        Index("ix_catalog_works_bookmark_rank", "public_bookmark_count", "id"),
        Index("ix_catalog_works_view_rank", "public_view_count", "id"),
        Index(
            "uq_catalog_works_source_identity", "source_system", "work_id", unique=True
        ),
        {"schema": INGEST_SCHEMA},
    )

    id: Mapped[int] = mapped_column(PRIMARY_KEY_TYPE, primary_key=True, autoincrement=True)
    source_system: Mapped[str] = mapped_column(String(64), nullable=False)
    work_id: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    author_id: Mapped[int] = mapped_column(
        ForeignKey(f"{INGEST_SCHEMA}.catalog_authors.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    public_view_count: Mapped[int | None] = mapped_column(BigInteger)
    public_bookmark_count: Mapped[int | None] = mapped_column(BigInteger)
    public_like_count: Mapped[int | None] = mapped_column(BigInteger)
    latest_observation_id: Mapped[int] = mapped_column(
        ForeignKey(f"{INGEST_SCHEMA}.raw_observations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class CatalogTag(Base):
    """One normalized public tag and optional public translation."""

    __tablename__ = "catalog_tags"
    __table_args__ = (
        Index("ix_catalog_tags_name", "tag_name"),
        Index(
            "uq_catalog_tags_source_name", "source_system", "tag_name", unique=True
        ),
        {"schema": INGEST_SCHEMA},
    )

    id: Mapped[int] = mapped_column(PRIMARY_KEY_TYPE, primary_key=True, autoincrement=True)
    source_system: Mapped[str] = mapped_column(String(64), nullable=False)
    tag_name: Mapped[str] = mapped_column(String(255), nullable=False)
    tag_translation: Mapped[str | None] = mapped_column(String(255))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class CatalogWorkMetricSnapshot(Base):
    """Immutable public work metrics tied to one validated observation."""

    __tablename__ = "catalog_work_metric_snapshots"
    __table_args__ = (
        CheckConstraint(
            "public_view_count IS NULL OR public_view_count >= 0",
            name="nonnegative_catalog_snapshot_views",
        ),
        CheckConstraint(
            "public_bookmark_count IS NULL OR public_bookmark_count >= 0",
            name="nonnegative_catalog_snapshot_bookmarks",
        ),
        CheckConstraint(
            "public_like_count IS NULL OR public_like_count >= 0",
            name="nonnegative_catalog_snapshot_likes",
        ),
        Index("ix_catalog_metric_snapshots_work_time", "work_id", "observed_at"),
        Index(
            "uq_catalog_metric_snapshots_observation", "source_observation_id", unique=True
        ),
        {"schema": INGEST_SCHEMA},
    )

    id: Mapped[int] = mapped_column(PRIMARY_KEY_TYPE, primary_key=True, autoincrement=True)
    work_id: Mapped[int] = mapped_column(
        ForeignKey(f"{INGEST_SCHEMA}.catalog_works.id", ondelete="CASCADE"), nullable=False
    )
    source_observation_id: Mapped[int] = mapped_column(
        ForeignKey(f"{INGEST_SCHEMA}.raw_observations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    public_view_count: Mapped[int | None] = mapped_column(BigInteger)
    public_bookmark_count: Mapped[int | None] = mapped_column(BigInteger)
    public_like_count: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class CatalogWorkTag(Base):
    """Ordered many-to-many relationship between normalized works and tags."""

    __tablename__ = "catalog_work_tags"
    __table_args__ = (
        CheckConstraint("position >= 0", name="nonnegative_catalog_work_tag_position"),
        Index("ix_catalog_work_tags_tag", "tag_id"),
        {"schema": INGEST_SCHEMA},
    )

    work_id: Mapped[int] = mapped_column(
        ForeignKey(f"{INGEST_SCHEMA}.catalog_works.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[int] = mapped_column(
        ForeignKey(f"{INGEST_SCHEMA}.catalog_tags.id", ondelete="RESTRICT"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
