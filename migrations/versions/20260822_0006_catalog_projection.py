"""Add the normalized Phase 2 catalog projection.

Revision ID: 20260822_0006
Revises: 20260822_0005
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260822_0006"
down_revision: str | None = "20260822_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "ingest"


def upgrade() -> None:
    """Create normalized author, work, tag and work-tag tables."""
    op.create_table(
        "catalog_authors",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("source_system", sa.String(64), nullable=False),
        sa.Column("author_id", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column(
            "latest_observation_id",
            sa.BigInteger(),
            sa.ForeignKey(f"{SCHEMA}.raw_observations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        schema=SCHEMA,
    )
    op.create_index(
        "uq_catalog_authors_source_identity",
        "catalog_authors",
        ["source_system", "author_id"],
        unique=True,
        schema=SCHEMA,
    )
    op.create_index(
        "ix_catalog_authors_display_name",
        "catalog_authors",
        ["display_name"],
        schema=SCHEMA,
    )

    op.create_table(
        "catalog_works",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("source_system", sa.String(64), nullable=False),
        sa.Column("work_id", sa.String(255), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column(
            "author_id",
            sa.BigInteger(),
            sa.ForeignKey(f"{SCHEMA}.catalog_authors.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("width", sa.Integer()),
        sa.Column("height", sa.Integer()),
        sa.Column("public_view_count", sa.BigInteger()),
        sa.Column("public_bookmark_count", sa.BigInteger()),
        sa.Column("public_like_count", sa.BigInteger()),
        sa.Column(
            "latest_observation_id",
            sa.BigInteger(),
            sa.ForeignKey(f"{SCHEMA}.raw_observations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("page_count >= 1", name="positive_catalog_work_page_count"),
        sa.CheckConstraint("width IS NULL OR width >= 1", name="positive_catalog_work_width"),
        sa.CheckConstraint(
            "height IS NULL OR height >= 1", name="positive_catalog_work_height"
        ),
        sa.CheckConstraint(
            "public_view_count IS NULL OR public_view_count >= 0",
            name="nonnegative_catalog_work_views",
        ),
        sa.CheckConstraint(
            "public_bookmark_count IS NULL OR public_bookmark_count >= 0",
            name="nonnegative_catalog_work_bookmarks",
        ),
        sa.CheckConstraint(
            "public_like_count IS NULL OR public_like_count >= 0",
            name="nonnegative_catalog_work_likes",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "uq_catalog_works_source_identity",
        "catalog_works",
        ["source_system", "work_id"],
        unique=True,
        schema=SCHEMA,
    )
    op.create_index(
        "ix_catalog_works_created_at", "catalog_works", ["created_at"], schema=SCHEMA
    )
    op.create_index(
        "ix_catalog_works_author", "catalog_works", ["author_id"], schema=SCHEMA
    )
    op.create_index("ix_catalog_works_title", "catalog_works", ["title"], schema=SCHEMA)

    op.create_table(
        "catalog_tags",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("source_system", sa.String(64), nullable=False),
        sa.Column("tag_name", sa.String(255), nullable=False),
        sa.Column("tag_translation", sa.String(255)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        schema=SCHEMA,
    )
    op.create_index(
        "uq_catalog_tags_source_name",
        "catalog_tags",
        ["source_system", "tag_name"],
        unique=True,
        schema=SCHEMA,
    )
    op.create_index("ix_catalog_tags_name", "catalog_tags", ["tag_name"], schema=SCHEMA)

    op.create_table(
        "catalog_work_tags",
        sa.Column(
            "work_id",
            sa.BigInteger(),
            sa.ForeignKey(f"{SCHEMA}.catalog_works.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "tag_id",
            sa.BigInteger(),
            sa.ForeignKey(f"{SCHEMA}.catalog_tags.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "position >= 0", name="nonnegative_catalog_work_tag_position"
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_catalog_work_tags_tag", "catalog_work_tags", ["tag_id"], schema=SCHEMA
    )


def downgrade() -> None:
    """Remove the Phase 2 normalized catalog projection."""
    op.drop_index(
        "ix_catalog_work_tags_tag", table_name="catalog_work_tags", schema=SCHEMA
    )
    op.drop_table("catalog_work_tags", schema=SCHEMA)
    op.drop_index("ix_catalog_tags_name", table_name="catalog_tags", schema=SCHEMA)
    op.drop_index(
        "uq_catalog_tags_source_name", table_name="catalog_tags", schema=SCHEMA
    )
    op.drop_table("catalog_tags", schema=SCHEMA)
    op.drop_index("ix_catalog_works_title", table_name="catalog_works", schema=SCHEMA)
    op.drop_index("ix_catalog_works_author", table_name="catalog_works", schema=SCHEMA)
    op.drop_index("ix_catalog_works_created_at", table_name="catalog_works", schema=SCHEMA)
    op.drop_index(
        "uq_catalog_works_source_identity", table_name="catalog_works", schema=SCHEMA
    )
    op.drop_table("catalog_works", schema=SCHEMA)
    op.drop_index(
        "ix_catalog_authors_display_name", table_name="catalog_authors", schema=SCHEMA
    )
    op.drop_index(
        "uq_catalog_authors_source_identity", table_name="catalog_authors", schema=SCHEMA
    )
    op.drop_table("catalog_authors", schema=SCHEMA)
