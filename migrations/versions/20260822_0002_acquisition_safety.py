"""Persist acquisition budgets, permits, and stop events.

Revision ID: 20260822_0002
Revises: 20260822_0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260822_0002"
down_revision: str | None = "20260822_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "ingest"


def upgrade() -> None:
    """Create non-secret persistent safety state."""
    op.create_table(
        "acquisition_daily_budgets",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("approval_fingerprint", sa.String(64), nullable=False),
        sa.Column("budget_day", sa.Date(), nullable=False),
        sa.Column("request_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("estimated_cost", sa.Numeric(14, 6), server_default="0", nullable=False),
        sa.Column("version", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("request_count >= 0", name="nonnegative_request_count"),
        sa.CheckConstraint("estimated_cost >= 0", name="nonnegative_estimated_cost"),
        sa.CheckConstraint("version >= 0", name="nonnegative_version"),
        sa.UniqueConstraint(
            "approval_fingerprint", "budget_day", name="uq_acquisition_daily_budget_scope"
        ),
        schema=SCHEMA,
    )
    op.create_table(
        "acquisition_run_budgets",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "run_id",
            sa.BigInteger(),
            sa.ForeignKey(f"{SCHEMA}.crawl_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("approval_fingerprint", sa.String(64), nullable=False),
        sa.Column("request_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("in_flight_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("consecutive_403", sa.Integer(), server_default="0", nullable=False),
        sa.Column("consecutive_429", sa.Integer(), server_default="0", nullable=False),
        sa.Column("stop_reason", sa.String(64)),
        sa.Column("version", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("request_count >= 0", name="nonnegative_request_count"),
        sa.CheckConstraint("in_flight_count >= 0", name="nonnegative_in_flight_count"),
        sa.CheckConstraint("consecutive_403 >= 0", name="nonnegative_consecutive_403"),
        sa.CheckConstraint("consecutive_429 >= 0", name="nonnegative_consecutive_429"),
        sa.CheckConstraint("version >= 0", name="nonnegative_version"),
        sa.UniqueConstraint("run_id", name="uq_acquisition_run_budget_run"),
        schema=SCHEMA,
    )
    op.create_table(
        "acquisition_request_permits",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("permit_id", sa.String(36), nullable=False),
        sa.Column(
            "run_budget_id",
            sa.BigInteger(),
            sa.ForeignKey(f"{SCHEMA}.acquisition_run_budgets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("approval_fingerprint", sa.String(64), nullable=False),
        sa.Column("estimated_cost", sa.Numeric(14, 6), nullable=False),
        sa.Column("status", sa.String(32), server_default="authorized", nullable=False),
        sa.Column("authorized_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column("response_status", sa.Integer()),
        sa.CheckConstraint("sequence >= 1", name="positive_sequence"),
        sa.CheckConstraint("estimated_cost >= 0", name="nonnegative_estimated_cost"),
        sa.CheckConstraint(
            "status IN ('authorized','consumed','transport_failed','cancelled')",
            name="valid_status",
        ),
        sa.CheckConstraint(
            "response_status IS NULL OR (response_status >= 100 AND response_status <= 599)",
            name="valid_response_status",
        ),
        sa.UniqueConstraint("permit_id", name="uq_acquisition_request_permit_id"),
        sa.UniqueConstraint(
            "run_budget_id", "sequence", name="uq_acquisition_request_permit_sequence"
        ),
        schema=SCHEMA,
    )
    op.create_table(
        "acquisition_stop_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("approval_fingerprint", sa.String(64), nullable=False),
        sa.Column(
            "run_id",
            sa.BigInteger(),
            sa.ForeignKey(f"{SCHEMA}.crawl_runs.id", ondelete="SET NULL"),
        ),
        sa.Column("reason", sa.String(64), nullable=False),
        sa.Column("trigger_source", sa.String(32), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "trigger_source IN ('system','operator','response','schema','budget','approval')",
            name="valid_trigger_source",
        ),
        schema=SCHEMA,
    )


def downgrade() -> None:
    """Remove persistent acquisition safety state."""
    op.drop_table("acquisition_stop_events", schema=SCHEMA)
    op.drop_table("acquisition_request_permits", schema=SCHEMA)
    op.drop_table("acquisition_run_budgets", schema=SCHEMA)
    op.drop_table("acquisition_daily_budgets", schema=SCHEMA)
