"""Add immutable work metric history.

Revision ID: 20260822_0007
Revises: 20260822_0006
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260822_0007"
down_revision: str | None = "20260822_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "ingest"
TABLE = "catalog_work_metric_snapshots"


def upgrade() -> None:
    """Create observation-bound, append-only public metric snapshots."""
    op.create_table(
        TABLE,
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "work_id",
            sa.BigInteger(),
            sa.ForeignKey(f"{SCHEMA}.catalog_works.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_observation_id",
            sa.BigInteger(),
            sa.ForeignKey(f"{SCHEMA}.raw_observations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("public_view_count", sa.BigInteger()),
        sa.Column("public_bookmark_count", sa.BigInteger()),
        sa.Column("public_like_count", sa.BigInteger()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "public_view_count IS NULL OR public_view_count >= 0",
            name="nonnegative_catalog_snapshot_views",
        ),
        sa.CheckConstraint(
            "public_bookmark_count IS NULL OR public_bookmark_count >= 0",
            name="nonnegative_catalog_snapshot_bookmarks",
        ),
        sa.CheckConstraint(
            "public_like_count IS NULL OR public_like_count >= 0",
            name="nonnegative_catalog_snapshot_likes",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_catalog_metric_snapshots_work_time",
        TABLE,
        ["work_id", "observed_at"],
        schema=SCHEMA,
    )
    op.create_index(
        "uq_catalog_metric_snapshots_observation",
        TABLE,
        ["source_observation_id"],
        unique=True,
        schema=SCHEMA,
    )


def downgrade() -> None:
    """Remove immutable work metric history."""
    op.drop_index(
        "uq_catalog_metric_snapshots_observation", table_name=TABLE, schema=SCHEMA
    )
    op.drop_index(
        "ix_catalog_metric_snapshots_work_time", table_name=TABLE, schema=SCHEMA
    )
    op.drop_table(TABLE, schema=SCHEMA)
