"""Add logical request idempotency to persistent permits.

Revision ID: 20260822_0003
Revises: 20260822_0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260822_0003"
down_revision: str | None = "20260822_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "ingest"
TABLE = "acquisition_request_permits"


def upgrade() -> None:
    """Backfill historical permits, then enforce one key per run."""
    op.add_column(
        TABLE,
        sa.Column("request_key_hash", sa.String(64), nullable=True),
        schema=SCHEMA,
    )
    op.execute(
        sa.text(
            "UPDATE ingest.acquisition_request_permits "
            "SET request_key_hash = md5(permit_id) || md5(permit_id || '-legacy') "
            "WHERE request_key_hash IS NULL"
        )
    )
    op.alter_column(TABLE, "request_key_hash", nullable=False, schema=SCHEMA)
    op.create_unique_constraint(
        "uq_acquisition_request_permit_logical_key",
        TABLE,
        ["run_budget_id", "request_key_hash"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    """Remove logical request idempotency metadata."""
    op.drop_constraint(
        "uq_acquisition_request_permit_logical_key",
        TABLE,
        type_="unique",
        schema=SCHEMA,
    )
    op.drop_column(TABLE, "request_key_hash", schema=SCHEMA)
