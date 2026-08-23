"""Add a one-way live execution journal.

Revision ID: 20260822_0005
Revises: 20260822_0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260822_0005"
down_revision: str | None = "20260822_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "ingest"
TABLE = "acquisition_live_execution_journals"


def upgrade() -> None:
    """Create durable evidence that can never authorize a recovery resend."""
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
        sa.Column(
            "slot_id",
            sa.BigInteger(),
            sa.ForeignKey(
                f"{SCHEMA}.acquisition_first_request_slots.id",
                ondelete="RESTRICT",
            ),
            nullable=False,
        ),
        sa.Column("request_binding_hash", sa.String(64), nullable=False),
        sa.Column(
            "permit_id",
            sa.String(36),
            sa.ForeignKey(
                f"{SCHEMA}.acquisition_request_permits.permit_id",
                ondelete="RESTRICT",
            ),
        ),
        sa.Column("status", sa.String(32), server_default="claimed", nullable=False),
        sa.Column("failure_code", sa.String(64)),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("send_started_at", sa.DateTime(timezone=True)),
        sa.Column("settled_at", sa.DateTime(timezone=True)),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer(), server_default="0", nullable=False),
        sa.CheckConstraint(
            "status IN "
            "('claimed','send_started','settled','completed','failed','indeterminate')",
            name="valid_live_execution_journal_status",
        ),
        sa.CheckConstraint("version >= 0", name="nonnegative_live_execution_version"),
        sa.CheckConstraint(
            "(status = 'claimed' AND permit_id IS NULL AND send_started_at IS NULL "
            "AND settled_at IS NULL AND resolved_at IS NULL AND failure_code IS NULL) OR "
            "(status = 'send_started' AND permit_id IS NOT NULL "
            "AND send_started_at IS NOT NULL AND settled_at IS NULL "
            "AND resolved_at IS NULL AND failure_code IS NULL) OR "
            "(status = 'settled' AND permit_id IS NOT NULL "
            "AND send_started_at IS NOT NULL AND settled_at IS NOT NULL "
            "AND resolved_at IS NULL AND failure_code IS NULL) OR "
            "(status = 'completed' AND permit_id IS NOT NULL "
            "AND send_started_at IS NOT NULL AND settled_at IS NOT NULL "
            "AND resolved_at IS NOT NULL AND failure_code IS NULL) OR "
            "(status = 'failed' AND resolved_at IS NOT NULL "
            "AND failure_code IS NOT NULL AND "
            "((permit_id IS NULL AND send_started_at IS NULL AND settled_at IS NULL) OR "
            "(permit_id IS NOT NULL AND send_started_at IS NOT NULL "
            "AND settled_at IS NOT NULL))) OR "
            "(status = 'indeterminate' AND permit_id IS NOT NULL "
            "AND send_started_at IS NOT NULL AND settled_at IS NULL "
            "AND resolved_at IS NOT NULL AND failure_code IS NOT NULL)",
            name="valid_live_execution_journal_shape",
        ),
        sa.UniqueConstraint("slot_id", name="uq_live_execution_journal_slot"),
        sa.UniqueConstraint("permit_id", name="uq_live_execution_journal_permit"),
        schema=SCHEMA,
    )


def downgrade() -> None:
    """Remove live execution journal evidence."""
    op.drop_table(TABLE, schema=SCHEMA)
