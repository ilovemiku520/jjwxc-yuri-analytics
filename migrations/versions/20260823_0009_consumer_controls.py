"""Add minimized shared consumer rate limiting and access audit tables.

Revision ID: 20260823_0009
Revises: 20260823_0008
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260823_0009"
down_revision: str | None = "20260823_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "ingest"


def upgrade() -> None:
    """Create bounded shared counters and append-only minimized access evidence."""
    op.create_table(
        "api_consumer_rate_limit_windows",
        sa.Column("consumer_key", sa.String(length=64), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_count", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(consumer_key) = 64", name="consumer_key_sha256_length"),
        sa.CheckConstraint("request_count >= 1", name="positive_request_count"),
        sa.PrimaryKeyConstraint("consumer_key"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_api_consumer_rate_limit_windows_updated",
        "api_consumer_rate_limit_windows",
        ["updated_at"],
        schema=SCHEMA,
    )
    op.create_table(
        "api_consumer_access_audits",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retention_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("consumer_key", sa.String(length=64), nullable=True),
        sa.Column("method", sa.String(length=16), nullable=False),
        sa.Column("route_template", sa.String(length=255), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("auth_outcome", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "consumer_key IS NULL OR length(consumer_key) = 64",
            name="consumer_key_sha256_length",
        ),
        sa.CheckConstraint(
            "status_code >= 100 AND status_code <= 599", name="valid_status_code"
        ),
        sa.CheckConstraint("retention_until > occurred_at", name="future_retention"),
        sa.PrimaryKeyConstraint("id"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_api_consumer_access_audits_occurred",
        "api_consumer_access_audits",
        ["occurred_at", "id"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_api_consumer_access_audits_retention",
        "api_consumer_access_audits",
        ["retention_until"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    """Remove consumer-control state."""
    op.drop_index(
        "ix_api_consumer_access_audits_retention",
        table_name="api_consumer_access_audits",
        schema=SCHEMA,
    )
    op.drop_index(
        "ix_api_consumer_access_audits_occurred",
        table_name="api_consumer_access_audits",
        schema=SCHEMA,
    )
    op.drop_table("api_consumer_access_audits", schema=SCHEMA)
    op.drop_index(
        "ix_api_consumer_rate_limit_windows_updated",
        table_name="api_consumer_rate_limit_windows",
        schema=SCHEMA,
    )
    op.drop_table("api_consumer_rate_limit_windows", schema=SCHEMA)
