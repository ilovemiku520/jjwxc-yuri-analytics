"""Create the Phase 0 ingest ledger.

Revision ID: 20260822_0001
Revises: None
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260822_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "ingest"


def upgrade() -> None:
    """Create source, task, observation, schema and quarantine tables."""
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")

    op.create_table(
        "source_records",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("source_system", sa.String(64), nullable=False),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("source_id", sa.String(255), nullable=False),
        sa.Column("source_url", sa.Text()),
        sa.Column("current_availability", sa.String(32), server_default="unknown", nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "entity_type IN ('work','author','tag_page','search_page')",
            name="valid_entity_type",
        ),
        sa.CheckConstraint(
            "current_availability IN ('available','missing','restricted','removed','unknown')",
            name="valid_current_availability",
        ),
        sa.UniqueConstraint(
            "source_system",
            "entity_type",
            "source_id",
            name="uq_source_records_source_identity",
        ),
        schema=SCHEMA,
    )

    op.create_table(
        "crawl_runs",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("run_type", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("status", sa.String(32), server_default="pending", nullable=False),
        sa.Column("config_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("budget_limit", sa.Numeric(14, 4)),
        sa.Column("budget_used", sa.Numeric(14, 4), server_default="0", nullable=False),
        sa.Column("budget_currency", sa.String(3), server_default="USD", nullable=False),
        sa.Column("requested_by", sa.String(255), server_default="offline-cli", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("stop_reason", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN "
            "('pending','running','completed','completed_with_errors','failed','cancelled')",
            name="valid_status",
        ),
        sa.CheckConstraint(
            "budget_limit IS NULL OR budget_limit >= 0",
            name="nonnegative_budget_limit",
        ),
        sa.CheckConstraint("budget_used >= 0", name="nonnegative_budget_used"),
        schema=SCHEMA,
    )

    op.create_table(
        "crawl_tasks",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "run_id",
            sa.BigInteger(),
            sa.ForeignKey(f"{SCHEMA}.crawl_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_record_id",
            sa.BigInteger(),
            sa.ForeignKey(f"{SCHEMA}.source_records.id", ondelete="SET NULL"),
        ),
        sa.Column("task_type", sa.String(64), nullable=False),
        sa.Column("logical_target", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("priority", sa.Integer(), server_default="0", nullable=False),
        sa.Column("status", sa.String(32), server_default="pending", nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error_code", sa.String(100)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending','running','succeeded','failed','cancelled')",
            name="valid_status",
        ),
        sa.CheckConstraint("priority >= 0", name="nonnegative_priority"),
        sa.CheckConstraint(
            "attempt_count >= 0", name="nonnegative_attempt_count"
        ),
        sa.UniqueConstraint("run_id", "idempotency_key", name="uq_crawl_tasks_run_key"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_crawl_tasks_pending_dispatch",
        "crawl_tasks",
        ["available_at", "priority"],
        unique=False,
        schema=SCHEMA,
        postgresql_where=sa.text("status = 'pending'"),
    )

    op.create_table(
        "task_attempts",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "task_id",
            sa.BigInteger(),
            sa.ForeignKey(f"{SCHEMA}.crawl_tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), server_default="running", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("http_status", sa.Integer()),
        sa.Column("error_code", sa.String(100)),
        sa.Column("retry_after", sa.DateTime(timezone=True)),
        sa.Column("cost", sa.Numeric(14, 6)),
        sa.Column("bytes_received", sa.BigInteger()),
        sa.Column("trace_id", sa.String(64), nullable=False),
        sa.CheckConstraint(
            "status IN ('running','succeeded','failed')", name="valid_status"
        ),
        sa.CheckConstraint(
            "http_status IS NULL OR (http_status >= 100 AND http_status <= 599)",
            name="valid_http_status",
        ),
        sa.CheckConstraint("cost IS NULL OR cost >= 0", name="nonnegative_cost"),
        sa.CheckConstraint(
            "bytes_received IS NULL OR bytes_received >= 0",
            name="nonnegative_bytes_received",
        ),
        sa.UniqueConstraint("task_id", "attempt_no", name="uq_task_attempts_task_number"),
        schema=SCHEMA,
    )

    op.create_table(
        "schema_definitions",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("definition", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("sample_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("status", sa.String(32), server_default="discovered", nullable=False),
        sa.Column("compatible_parser_min", sa.String(100)),
        sa.Column("compatible_parser_max", sa.String(100)),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "entity_type IN ('work','author','tag_page','search_page')",
            name="valid_entity_type",
        ),
        sa.CheckConstraint(
            "status IN ('discovered','approved','rejected')",
            name="valid_status",
        ),
        sa.CheckConstraint(
            "sample_count >= 0", name="nonnegative_sample_count"
        ),
        sa.UniqueConstraint(
            "entity_type", "fingerprint", name="uq_schema_definitions_entity_fingerprint"
        ),
        schema=SCHEMA,
    )

    op.create_table(
        "raw_observations",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "source_record_id",
            sa.BigInteger(),
            sa.ForeignKey(f"{SCHEMA}.source_records.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "task_attempt_id",
            sa.BigInteger(),
            sa.ForeignKey(f"{SCHEMA}.task_attempts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("content_type", sa.String(255), nullable=False),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("payload_object_key", sa.Text(), nullable=False),
        sa.Column("payload_bytes", sa.BigInteger(), nullable=False),
        sa.Column("schema_fingerprint", sa.String(64), nullable=False),
        sa.Column("parser_version", sa.String(100)),
        sa.Column("validation_status", sa.String(32), server_default="pending", nullable=False),
        sa.Column("retention_until", sa.DateTime(timezone=True)),
        sa.Column(
            "observation_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status_code >= 100 AND status_code <= 599",
            name="valid_status_code",
        ),
        sa.CheckConstraint(
            "payload_bytes >= 0", name="nonnegative_payload_bytes"
        ),
        sa.CheckConstraint(
            "validation_status IN ('pending','valid','invalid','quarantined')",
            name="valid_validation_status",
        ),
        sa.UniqueConstraint(
            "source_record_id",
            "payload_sha256",
            "observed_at",
            name="uq_raw_observations_source_payload_time",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_raw_observations_source_time",
        "raw_observations",
        ["source_record_id", "observed_at"],
        unique=False,
        schema=SCHEMA,
    )

    op.create_table(
        "quarantine_records",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "raw_observation_id",
            sa.BigInteger(),
            sa.ForeignKey(f"{SCHEMA}.raw_observations.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "task_attempt_id",
            sa.BigInteger(),
            sa.ForeignKey(f"{SCHEMA}.task_attempts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("source_id", sa.String(255), nullable=False),
        sa.Column("error_code", sa.String(100), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), server_default="open", nullable=False),
        sa.Column("resolution", sa.Text()),
        sa.Column("first_failed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_failed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_by", sa.String(255)),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "entity_type IN ('work','author','tag_page','search_page')",
            name="valid_entity_type",
        ),
        sa.CheckConstraint(
            "status IN ('open','resolved','ignored')",
            name="valid_status",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_quarantine_records_open",
        "quarantine_records",
        ["first_failed_at"],
        unique=False,
        schema=SCHEMA,
        postgresql_where=sa.text("status = 'open'"),
    )

    op.create_table(
        "discovery_checkpoints",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("discovery_scope", sa.String(255), nullable=False),
        sa.Column("seed_version", sa.String(100), nullable=False),
        sa.Column("cursor", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True)),
        sa.Column("window_end", sa.DateTime(timezone=True)),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "provider",
            "discovery_scope",
            "seed_version",
            name="uq_discovery_checkpoints_provider_scope_seed",
        ),
        schema=SCHEMA,
    )


def downgrade() -> None:
    """Remove the Phase 0 ingest ledger."""
    op.drop_table("discovery_checkpoints", schema=SCHEMA)
    op.drop_index("ix_quarantine_records_open", table_name="quarantine_records", schema=SCHEMA)
    op.drop_table("quarantine_records", schema=SCHEMA)
    op.drop_index("ix_raw_observations_source_time", table_name="raw_observations", schema=SCHEMA)
    op.drop_table("raw_observations", schema=SCHEMA)
    op.drop_table("schema_definitions", schema=SCHEMA)
    op.drop_table("task_attempts", schema=SCHEMA)
    op.drop_index("ix_crawl_tasks_pending_dispatch", table_name="crawl_tasks", schema=SCHEMA)
    op.drop_table("crawl_tasks", schema=SCHEMA)
    op.drop_table("crawl_runs", schema=SCHEMA)
    op.drop_table("source_records", schema=SCHEMA)
    op.execute(f"DROP SCHEMA IF EXISTS {SCHEMA}")
