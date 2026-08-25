"""Remove unsupported recommendation and bomb-ticket counters.

Revision ID: 20260825_0016
Revises: 20260825_0015
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260825_0016"
down_revision: str | None = "20260825_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "ingest"
TABLE = "jjwxc_novel_snapshots"


def upgrade() -> None:
    op.drop_constraint(
        "nonnegative_jjwxc_snapshot_recommendations",
        TABLE,
        schema=SCHEMA,
        type_="check",
    )
    op.drop_constraint(
        "nonnegative_jjwxc_snapshot_bomb_tickets",
        TABLE,
        schema=SCHEMA,
        type_="check",
    )
    op.drop_column(TABLE, "recommendation_count", schema=SCHEMA)
    op.drop_column(TABLE, "bomb_ticket_count", schema=SCHEMA)


def downgrade() -> None:
    op.add_column(
        TABLE,
        sa.Column("recommendation_count", sa.BigInteger(), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        TABLE,
        sa.Column("bomb_ticket_count", sa.BigInteger(), nullable=True),
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "nonnegative_jjwxc_snapshot_recommendations",
        TABLE,
        "recommendation_count IS NULL OR recommendation_count >= 0",
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "nonnegative_jjwxc_snapshot_bomb_tickets",
        TABLE,
        "bomb_ticket_count IS NULL OR bomb_ticket_count >= 0",
        schema=SCHEMA,
    )
