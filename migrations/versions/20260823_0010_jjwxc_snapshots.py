"""Add minimized JJWXC current projections and immutable snapshots.

Revision ID: 20260823_0010
Revises: 20260823_0009
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "20260823_0010"
down_revision: str | None = "20260823_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "ingest"


def upgrade() -> None:
    """Create current author/novel projections and append-only metric history."""
    op.create_table(
        "jjwxc_authors",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("author_id", sa.String(length=32), nullable=False),
        sa.Column("display_name", sa.String(length=80), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        schema=SCHEMA,
    )
    op.create_index(
        "uq_jjwxc_authors_author_id",
        "jjwxc_authors",
        ["author_id"],
        unique=True,
        schema=SCHEMA,
    )
    op.create_index(
        "ix_jjwxc_authors_display_name",
        "jjwxc_authors",
        ["display_name"],
        schema=SCHEMA,
    )
    op.create_table(
        "jjwxc_novels",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("novel_id", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column(
            "author_record_id",
            sa.BigInteger(),
            sa.ForeignKey(f"{SCHEMA}.jjwxc_authors.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("novel_type", sa.String(length=100), nullable=False),
        sa.Column("perspective", sa.String(length=30)),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("tags", JSONB(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("latest_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('连载','完结','暂停','锁定','未知')",
            name="valid_jjwxc_novel_status",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "uq_jjwxc_novels_novel_id",
        "jjwxc_novels",
        ["novel_id"],
        unique=True,
        schema=SCHEMA,
    )
    op.create_index(
        "ix_jjwxc_novels_author",
        "jjwxc_novels",
        ["author_record_id"],
        schema=SCHEMA,
    )
    op.create_index("ix_jjwxc_novels_title", "jjwxc_novels", ["title"], schema=SCHEMA)
    op.create_table(
        "jjwxc_novel_snapshots",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "novel_record_id",
            sa.BigInteger(),
            sa.ForeignKey(f"{SCHEMA}.jjwxc_novels.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("word_count", sa.BigInteger(), nullable=False),
        sa.Column("review_count", sa.BigInteger(), nullable=False),
        sa.Column("favorite_count", sa.BigInteger(), nullable=False),
        sa.Column("points", sa.BigInteger(), nullable=False),
        sa.Column("average_non_v_chapter_click_count", sa.BigInteger()),
        sa.Column("synopsis_char_count", sa.Integer()),
        sa.Column("synopsis_sentence_count", sa.Integer()),
        sa.Column("synopsis_theme_terms", JSONB(), nullable=False),
        sa.Column("source_mode", sa.String(length=32), nullable=False),
        sa.Column("candidate_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("word_count >= 0", name="nonnegative_jjwxc_snapshot_words"),
        sa.CheckConstraint("review_count >= 0", name="nonnegative_jjwxc_snapshot_reviews"),
        sa.CheckConstraint("favorite_count >= 0", name="nonnegative_jjwxc_snapshot_favorites"),
        sa.CheckConstraint("points >= 0", name="nonnegative_jjwxc_snapshot_points"),
        sa.CheckConstraint(
            "average_non_v_chapter_click_count IS NULL OR average_non_v_chapter_click_count >= 0",
            name="nonnegative_jjwxc_snapshot_clicks",
        ),
        sa.CheckConstraint(
            "synopsis_char_count IS NULL OR synopsis_char_count >= 0",
            name="nonnegative_jjwxc_synopsis_chars",
        ),
        sa.CheckConstraint(
            "synopsis_sentence_count IS NULL OR synopsis_sentence_count >= 0",
            name="nonnegative_jjwxc_synopsis_sentences",
        ),
        sa.CheckConstraint(
            "source_mode IN ('synthetic_fixture','public_candidate')",
            name="valid_jjwxc_source_mode",
        ),
        sa.CheckConstraint("length(candidate_sha256) = 64", name="jjwxc_candidate_sha256_length"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_jjwxc_snapshots_novel_time",
        "jjwxc_novel_snapshots",
        ["novel_record_id", "observed_at"],
        schema=SCHEMA,
    )
    op.create_index(
        "uq_jjwxc_snapshots_candidate",
        "jjwxc_novel_snapshots",
        ["candidate_sha256"],
        unique=True,
        schema=SCHEMA,
    )
    op.create_index(
        "uq_jjwxc_snapshots_novel_time",
        "jjwxc_novel_snapshots",
        ["novel_record_id", "observed_at"],
        unique=True,
        schema=SCHEMA,
    )


def downgrade() -> None:
    """Remove JJWXC snapshot storage without touching legacy catalog data."""
    op.drop_table("jjwxc_novel_snapshots", schema=SCHEMA)
    op.drop_table("jjwxc_novels", schema=SCHEMA)
    op.drop_table("jjwxc_authors", schema=SCHEMA)
