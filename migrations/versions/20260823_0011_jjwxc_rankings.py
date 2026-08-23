"""Add immutable daily JJWXC ranking positions.

Revision ID: 20260823_0011
Revises: 20260823_0010
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260823_0011"
down_revision: str | None = "20260823_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "ingest"


def upgrade() -> None:
    op.create_table(
        "jjwxc_ranking_snapshots",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("ranking_key", sa.String(length=64), nullable=False),
        sa.Column("observation_day", sa.Date(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("novel_id", sa.String(length=32), nullable=False),
        sa.Column("author_id", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("author_display_name", sa.String(length=80), nullable=False),
        sa.Column("novel_type", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("word_count", sa.BigInteger(), nullable=False),
        sa.Column("points", sa.BigInteger(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("rank >= 1 AND rank <= 200", name="valid_jjwxc_ranking_position"),
        sa.CheckConstraint("word_count >= 0", name="nonnegative_jjwxc_ranking_words"),
        sa.CheckConstraint("points >= 0", name="nonnegative_jjwxc_ranking_points"),
        schema=SCHEMA,
    )
    op.create_index(
        "uq_jjwxc_ranking_day_novel",
        "jjwxc_ranking_snapshots",
        ["ranking_key", "observation_day", "novel_id"],
        unique=True,
        schema=SCHEMA,
    )
    op.create_index(
        "uq_jjwxc_ranking_day_position",
        "jjwxc_ranking_snapshots",
        ["ranking_key", "observation_day", "rank"],
        unique=True,
        schema=SCHEMA,
    )
    op.create_index(
        "ix_jjwxc_ranking_novel_time",
        "jjwxc_ranking_snapshots",
        ["novel_id", "observation_day"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("jjwxc_ranking_snapshots", schema=SCHEMA)
