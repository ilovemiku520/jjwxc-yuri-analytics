"""Add one permanent first-request slot per approval.

Revision ID: 20260822_0004
Revises: 20260822_0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260822_0004"
down_revision: str | None = "20260822_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "ingest"
TABLE = "acquisition_first_request_slots"


def upgrade() -> None:
    """Create a non-releasable approval-scoped first-request slot."""
    op.create_table(
        TABLE,
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("approval_fingerprint", sa.String(64), nullable=False),
        sa.Column(
            "run_id",
            sa.BigInteger(),
            sa.ForeignKey(f"{SCHEMA}.crawl_runs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("request_key_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), server_default="claimed", nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('claimed','completed','failed')",
            name="valid_first_request_slot_status",
        ),
        sa.CheckConstraint(
            "(status = 'claimed' AND resolved_at IS NULL) OR "
            "(status IN ('completed','failed') AND resolved_at IS NOT NULL)",
            name="valid_first_request_slot_resolution",
        ),
        sa.UniqueConstraint(
            "approval_fingerprint",
            name="uq_acquisition_first_request_slot_approval",
        ),
        schema=SCHEMA,
    )


def downgrade() -> None:
    """Remove first-request slots."""
    op.drop_table(TABLE, schema=SCHEMA)
