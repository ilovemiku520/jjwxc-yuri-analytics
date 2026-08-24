"""Add resumable catalog discovery, compact rankings, and chapter click snapshots.

Revision ID: 20260824_0012
Revises: 20260823_0011
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260824_0012"
down_revision: str | None = "20260823_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "ingest"


def upgrade() -> None:
    op.add_column(
        "jjwxc_novel_snapshots",
        sa.Column("average_v_chapter_click_count", sa.BigInteger(), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "jjwxc_novel_snapshots",
        sa.Column("non_v_chapter_count", sa.Integer(), server_default="0", nullable=False),
        schema=SCHEMA,
    )
    op.add_column(
        "jjwxc_novel_snapshots",
        sa.Column("v_chapter_count", sa.Integer(), server_default="0", nullable=False),
        schema=SCHEMA,
    )
    op.add_column(
        "jjwxc_novel_snapshots",
        sa.Column("chapter_click_coverage_count", sa.Integer(), server_default="0", nullable=False),
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "nonnegative_jjwxc_snapshot_v_clicks",
        "jjwxc_novel_snapshots",
        "average_v_chapter_click_count IS NULL OR average_v_chapter_click_count >= 0",
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "nonnegative_jjwxc_snapshot_chapter_counts",
        "jjwxc_novel_snapshots",
        "non_v_chapter_count >= 0 AND v_chapter_count >= 0 "
        "AND chapter_click_coverage_count >= 0",
        schema=SCHEMA,
    )

    op.create_table(
        "jjwxc_channel_ranking_snapshots",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("ranking_key", sa.String(length=32), nullable=False),
        sa.Column("observation_day", sa.Date(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("novel_id", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("source_rank_id", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("rank >= 1 AND rank <= 100", name="valid_jjwxc_channel_rank"),
        schema=SCHEMA,
    )
    op.create_index(
        "uq_jjwxc_channel_ranking_day_position",
        "jjwxc_channel_ranking_snapshots",
        ["ranking_key", "observation_day", "rank"],
        unique=True,
        schema=SCHEMA,
    )
    op.create_index(
        "uq_jjwxc_channel_ranking_day_novel",
        "jjwxc_channel_ranking_snapshots",
        ["ranking_key", "observation_day", "novel_id"],
        unique=True,
        schema=SCHEMA,
    )
    op.create_index(
        "ix_jjwxc_channel_ranking_novel_time",
        "jjwxc_channel_ranking_snapshots",
        ["novel_id", "observation_day"],
        schema=SCHEMA,
    )

    op.create_table(
        "jjwxc_discovery_queue",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("novel_id", sa.String(length=32), nullable=False),
        sa.Column("source_kind", sa.String(length=32), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("next_fetch_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error_code", sa.String(length=80), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending','running','completed','failed')",
            name="valid_jjwxc_discovery_state",
        ),
        sa.CheckConstraint("priority >= 0", name="nonnegative_jjwxc_discovery_priority"),
        sa.CheckConstraint("attempt_count >= 0", name="nonnegative_jjwxc_discovery_attempts"),
        schema=SCHEMA,
    )
    op.create_index(
        "uq_jjwxc_discovery_novel",
        "jjwxc_discovery_queue",
        ["novel_id"],
        unique=True,
        schema=SCHEMA,
    )
    op.create_index(
        "ix_jjwxc_discovery_schedule",
        "jjwxc_discovery_queue",
        ["status", "next_fetch_at", "priority"],
        schema=SCHEMA,
    )

    op.create_table(
        "jjwxc_chapter_snapshots",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "novel_record_id",
            sa.BigInteger(),
            sa.ForeignKey(f"{SCHEMA}.jjwxc_novels.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("chapter_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("is_vip", sa.Boolean(), nullable=False),
        sa.Column("word_count", sa.Integer(), nullable=False),
        sa.Column("click_count", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("chapter_id >= 1", name="positive_jjwxc_chapter_id"),
        sa.CheckConstraint("position >= 1", name="positive_jjwxc_chapter_position"),
        sa.CheckConstraint("word_count >= 0", name="nonnegative_jjwxc_chapter_words"),
        sa.CheckConstraint(
            "click_count IS NULL OR click_count >= 0", name="nonnegative_jjwxc_chapter_clicks"
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "uq_jjwxc_chapter_observation",
        "jjwxc_chapter_snapshots",
        ["novel_record_id", "observed_at", "chapter_id"],
        unique=True,
        schema=SCHEMA,
    )
    op.create_index(
        "ix_jjwxc_chapter_novel_time",
        "jjwxc_chapter_snapshots",
        ["novel_record_id", "observed_at"],
        schema=SCHEMA,
    )

    # Substring search stays fast as the catalog grows. Railway PostgreSQL supports pg_trgm.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_index(
        "ix_jjwxc_novels_title_trgm",
        "jjwxc_novels",
        ["title"],
        schema=SCHEMA,
        postgresql_using="gin",
        postgresql_ops={"title": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_jjwxc_authors_display_name_trgm",
        "jjwxc_authors",
        ["display_name"],
        schema=SCHEMA,
        postgresql_using="gin",
        postgresql_ops={"display_name": "gin_trgm_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_jjwxc_authors_display_name_trgm", table_name="jjwxc_authors", schema=SCHEMA)
    op.drop_index("ix_jjwxc_novels_title_trgm", table_name="jjwxc_novels", schema=SCHEMA)
    op.drop_table("jjwxc_chapter_snapshots", schema=SCHEMA)
    op.drop_table("jjwxc_discovery_queue", schema=SCHEMA)
    op.drop_table("jjwxc_channel_ranking_snapshots", schema=SCHEMA)
    op.drop_constraint(
        "nonnegative_jjwxc_snapshot_chapter_counts",
        "jjwxc_novel_snapshots",
        schema=SCHEMA,
        type_="check",
    )
    op.drop_constraint(
        "nonnegative_jjwxc_snapshot_v_clicks",
        "jjwxc_novel_snapshots",
        schema=SCHEMA,
        type_="check",
    )
    op.drop_column("jjwxc_novel_snapshots", "chapter_click_coverage_count", schema=SCHEMA)
    op.drop_column("jjwxc_novel_snapshots", "v_chapter_count", schema=SCHEMA)
    op.drop_column("jjwxc_novel_snapshots", "non_v_chapter_count", schema=SCHEMA)
    op.drop_column("jjwxc_novel_snapshots", "average_v_chapter_click_count", schema=SCHEMA)
