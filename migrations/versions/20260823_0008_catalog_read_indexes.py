"""Add catalog detail and ranking read indexes.

Revision ID: 20260823_0008
Revises: 20260822_0007
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260823_0008"
down_revision: str | None = "20260822_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "ingest"


def upgrade() -> None:
    """Add bounded detail lookup and composite metric ranking indexes."""
    op.create_index(
        "ix_catalog_authors_author_id",
        "catalog_authors",
        ["author_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_catalog_works_work_id", "catalog_works", ["work_id"], schema=SCHEMA
    )
    for name, column in (
        ("ix_catalog_works_like_rank", "public_like_count"),
        ("ix_catalog_works_bookmark_rank", "public_bookmark_count"),
        ("ix_catalog_works_view_rank", "public_view_count"),
    ):
        op.create_index(name, "catalog_works", [column, "id"], schema=SCHEMA)


def downgrade() -> None:
    """Remove detail lookup and composite metric ranking indexes."""
    for name in (
        "ix_catalog_works_view_rank",
        "ix_catalog_works_bookmark_rank",
        "ix_catalog_works_like_rank",
        "ix_catalog_works_work_id",
    ):
        op.drop_index(name, table_name="catalog_works", schema=SCHEMA)
    op.drop_index(
        "ix_catalog_authors_author_id", table_name="catalog_authors", schema=SCHEMA
    )
