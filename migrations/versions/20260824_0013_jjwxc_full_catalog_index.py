"""Add the lightweight full-site yuri catalog index.

Revision ID: 20260824_0013
Revises: 20260824_0012
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260824_0013"
down_revision: str | None = "20260824_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "ingest"


def upgrade() -> None:
    op.create_table(
        "jjwxc_catalog_index",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("novel_id", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("author_id", sa.String(length=32), nullable=False),
        sa.Column("author_display_name", sa.String(length=80), nullable=False),
        sa.Column("novel_type", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("word_count", sa.BigInteger(), nullable=False),
        sa.Column("points", sa.BigInteger(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_page", sa.Integer(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('连载','完结','暂停','锁定','未知')",
            name="valid_jjwxc_catalog_status",
        ),
        sa.CheckConstraint("word_count >= 0", name="nonnegative_jjwxc_catalog_words"),
        sa.CheckConstraint("points >= 0", name="nonnegative_jjwxc_catalog_points"),
        sa.CheckConstraint("source_page >= 1", name="positive_jjwxc_catalog_source_page"),
        schema=SCHEMA,
    )
    op.create_index(
        "uq_jjwxc_catalog_index_novel",
        "jjwxc_catalog_index",
        ["novel_id"],
        unique=True,
        schema=SCHEMA,
    )
    op.create_index(
        "ix_jjwxc_catalog_index_title",
        "jjwxc_catalog_index",
        ["title"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_jjwxc_catalog_index_author_name",
        "jjwxc_catalog_index",
        ["author_display_name"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_jjwxc_catalog_index_title_trgm",
        "jjwxc_catalog_index",
        ["title"],
        postgresql_using="gin",
        postgresql_ops={"title": "gin_trgm_ops"},
        schema=SCHEMA,
    )
    op.create_index(
        "ix_jjwxc_catalog_index_author_trgm",
        "jjwxc_catalog_index",
        ["author_display_name"],
        postgresql_using="gin",
        postgresql_ops={"author_display_name": "gin_trgm_ops"},
        schema=SCHEMA,
    )
    op.execute(
        sa.text(
            f"""
            INSERT INTO {SCHEMA}.jjwxc_catalog_index (
                novel_id, title, author_id, author_display_name, novel_type, status,
                word_count, points, published_at, source_page, first_seen_at, last_seen_at
            )
            SELECT n.novel_id, n.title, a.author_id, a.display_name, n.novel_type, n.status,
                   s.word_count, s.points, NULL, 1, n.first_seen_at, n.latest_observed_at
            FROM {SCHEMA}.jjwxc_novels AS n
            JOIN {SCHEMA}.jjwxc_authors AS a ON a.id = n.author_record_id
            JOIN LATERAL (
                SELECT word_count, points
                FROM {SCHEMA}.jjwxc_novel_snapshots
                WHERE novel_record_id = n.id
                ORDER BY observed_at DESC
                LIMIT 1
            ) AS s ON TRUE
            ON CONFLICT (novel_id) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    op.drop_index(
        "ix_jjwxc_catalog_index_author_trgm",
        table_name="jjwxc_catalog_index",
        schema=SCHEMA,
    )
    op.drop_index(
        "ix_jjwxc_catalog_index_title_trgm",
        table_name="jjwxc_catalog_index",
        schema=SCHEMA,
    )
    op.drop_table("jjwxc_catalog_index", schema=SCHEMA)
