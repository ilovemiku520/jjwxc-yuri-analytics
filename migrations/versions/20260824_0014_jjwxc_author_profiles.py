"""Add immutable public author-column snapshots.

Revision ID: 20260824_0014
Revises: 20260824_0013
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260824_0014"
down_revision: str | None = "20260824_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "ingest"


def upgrade() -> None:
    op.create_table(
        "jjwxc_author_snapshots",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "author_record_id",
            sa.BigInteger(),
            sa.ForeignKey(f"{SCHEMA}.jjwxc_authors.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("author_favorite_count", sa.BigInteger(), nullable=False),
        sa.Column("nonlocked_work_count", sa.Integer(), nullable=False),
        sa.Column("locked_work_count", sa.Integer(), nullable=False),
        sa.Column("total_word_count", sa.BigInteger(), nullable=False),
        sa.Column("total_points", sa.BigInteger(), nullable=False),
        sa.Column("candidate_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "author_favorite_count >= 0 AND nonlocked_work_count >= 0 "
            "AND locked_work_count >= 0 AND total_word_count >= 0 AND total_points >= 0",
            name="nonnegative_jjwxc_author_snapshot_metrics",
        ),
        sa.CheckConstraint(
            "length(candidate_sha256) = 64",
            name="jjwxc_author_candidate_sha256_length",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_jjwxc_author_snapshots_author_time",
        "jjwxc_author_snapshots",
        ["author_record_id", "observed_at"],
        schema=SCHEMA,
    )
    op.create_index(
        "uq_jjwxc_author_snapshots_author_time",
        "jjwxc_author_snapshots",
        ["author_record_id", "observed_at"],
        unique=True,
        schema=SCHEMA,
    )
    op.create_index(
        "uq_jjwxc_author_snapshots_candidate",
        "jjwxc_author_snapshots",
        ["candidate_sha256"],
        unique=True,
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("jjwxc_author_snapshots", schema=SCHEMA)
