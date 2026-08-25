"""Add nullable reader-input and first-chapter conversion metrics.

Revision ID: 20260825_0015
Revises: 20260824_0014
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260825_0015"
down_revision: str | None = "20260824_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "ingest"
TABLE = "jjwxc_novel_snapshots"


def upgrade() -> None:
    constraints = {
        "nutrition_count": "nonnegative_jjwxc_snapshot_nutrition",
        "recommendation_count": "nonnegative_jjwxc_snapshot_recommendations",
        "bomb_ticket_count": "nonnegative_jjwxc_snapshot_bomb_tickets",
        "first_chapter_click_count": "nonnegative_jjwxc_snapshot_first_clicks",
    }
    for name, constraint_name in constraints.items():
        op.add_column(TABLE, sa.Column(name, sa.BigInteger(), nullable=True), schema=SCHEMA)
        op.create_check_constraint(
            constraint_name,
            TABLE,
            f"{name} IS NULL OR {name} >= 0",
            schema=SCHEMA,
        )
    op.execute(
        sa.text(
            f"""
            UPDATE {SCHEMA}.{TABLE} AS snapshot
            SET first_chapter_click_count = chapter.click_count
            FROM {SCHEMA}.jjwxc_chapter_snapshots AS chapter
            WHERE chapter.novel_record_id = snapshot.novel_record_id
              AND chapter.observed_at = snapshot.observed_at
              AND chapter.position = 1
              AND chapter.click_count IS NOT NULL
            """
        )
    )


def downgrade() -> None:
    for name in reversed(
        (
            "nutrition_count",
            "recommendation_count",
            "bomb_ticket_count",
            "first_chapter_click_count",
        )
    ):
        op.drop_column(TABLE, name, schema=SCHEMA)
