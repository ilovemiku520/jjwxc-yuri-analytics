"""Phase 0 ingest ledger models; independent of unverified Pixiv fields."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from pixiv_yuri.shared.database import PRIMARY_KEY_TYPE, Base, utc_now

INGEST_SCHEMA = "ingest"
JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")

ENTITY_TYPES = "'work','author','tag_page','search_page'"
AVAILABILITY_STATES = "'available','missing','restricted','removed','unknown'"
RUN_STATUSES = "'pending','running','completed','completed_with_errors','failed','cancelled'"
TASK_STATUSES = "'pending','running','succeeded','failed','cancelled'"
ATTEMPT_STATUSES = "'running','succeeded','failed'"
VALIDATION_STATUSES = "'pending','valid','invalid','quarantined'"
SCHEMA_STATUSES = "'discovered','approved','rejected'"
QUARANTINE_STATUSES = "'open','resolved','ignored'"


class SourceRecord(Base):
    """Stable registration of one source-system entity or logical page."""

    __tablename__ = "source_records"
    __table_args__ = (
        UniqueConstraint(
            "source_system",
            "entity_type",
            "source_id",
            name="uq_source_records_source_identity",
        ),
        CheckConstraint(f"entity_type IN ({ENTITY_TYPES})", name="valid_entity_type"),
        CheckConstraint(
            f"current_availability IN ({AVAILABILITY_STATES})",
            name="valid_current_availability",
        ),
        {"schema": INGEST_SCHEMA},
    )

    id: Mapped[int] = mapped_column(PRIMARY_KEY_TYPE, primary_key=True, autoincrement=True)
    source_system: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[str] = mapped_column(String(255), nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    current_availability: Mapped[str] = mapped_column(
        String(32), nullable=False, default="unknown", server_default="unknown"
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class CrawlRun(Base):
    """One auditable acquisition run with a frozen configuration snapshot."""

    __tablename__ = "crawl_runs"
    __table_args__ = (
        CheckConstraint(f"status IN ({RUN_STATUSES})", name="valid_status"),
        CheckConstraint(
            "budget_limit IS NULL OR budget_limit >= 0",
            name="nonnegative_budget_limit",
        ),
        CheckConstraint("budget_used >= 0", name="nonnegative_budget_used"),
        {"schema": INGEST_SCHEMA},
    )

    id: Mapped[int] = mapped_column(PRIMARY_KEY_TYPE, primary_key=True, autoincrement=True)
    run_type: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending", server_default="pending"
    )
    config_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT, nullable=False, default=dict
    )
    budget_limit: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    budget_used: Mapped[Decimal] = mapped_column(
        Numeric(14, 4), nullable=False, default=Decimal("0"), server_default="0"
    )
    budget_currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="USD", server_default="USD"
    )
    requested_by: Mapped[str] = mapped_column(
        String(255), nullable=False, default="offline-cli", server_default="offline-cli"
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stop_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class CrawlTask(Base):
    """Durable task state; Celery will eventually transport, not own, this fact."""

    __tablename__ = "crawl_tasks"
    __table_args__ = (
        UniqueConstraint("run_id", "idempotency_key", name="uq_crawl_tasks_run_key"),
        CheckConstraint(f"status IN ({TASK_STATUSES})", name="valid_status"),
        CheckConstraint("priority >= 0", name="nonnegative_priority"),
        CheckConstraint("attempt_count >= 0", name="nonnegative_attempt_count"),
        Index(
            "ix_crawl_tasks_pending_dispatch",
            "available_at",
            "priority",
            postgresql_where=text("status = 'pending'"),
        ),
        {"schema": INGEST_SCHEMA},
    )

    id: Mapped[int] = mapped_column(PRIMARY_KEY_TYPE, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey(f"{INGEST_SCHEMA}.crawl_runs.id", ondelete="CASCADE"), nullable=False
    )
    source_record_id: Mapped[int | None] = mapped_column(
        ForeignKey(f"{INGEST_SCHEMA}.source_records.id", ondelete="SET NULL")
    )
    task_type: Mapped[str] = mapped_column(String(64), nullable=False)
    logical_target: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending", server_default="pending"
    )
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    last_error_code: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class TaskAttempt(Base):
    """Append-only execution attempt for one durable task."""

    __tablename__ = "task_attempts"
    __table_args__ = (
        UniqueConstraint("task_id", "attempt_no", name="uq_task_attempts_task_number"),
        CheckConstraint(f"status IN ({ATTEMPT_STATUSES})", name="valid_status"),
        CheckConstraint(
            "http_status IS NULL OR (http_status >= 100 AND http_status <= 599)",
            name="valid_http_status",
        ),
        CheckConstraint("cost IS NULL OR cost >= 0", name="nonnegative_cost"),
        CheckConstraint(
            "bytes_received IS NULL OR bytes_received >= 0", name="nonnegative_bytes_received"
        ),
        {"schema": INGEST_SCHEMA},
    )

    id: Mapped[int] = mapped_column(PRIMARY_KEY_TYPE, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey(f"{INGEST_SCHEMA}.crawl_tasks.id", ondelete="CASCADE"), nullable=False
    )
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    worker_id: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="running", server_default="running"
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    http_status: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(100))
    retry_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 6))
    bytes_received: Mapped[int | None] = mapped_column(BigInteger)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False)


class RawObservation(Base):
    """Immutable observation metadata; payload bytes live outside PostgreSQL."""

    __tablename__ = "raw_observations"
    __table_args__ = (
        UniqueConstraint(
            "source_record_id",
            "payload_sha256",
            "observed_at",
            name="uq_raw_observations_source_payload_time",
        ),
        CheckConstraint(
            "status_code >= 100 AND status_code <= 599", name="valid_status_code"
        ),
        CheckConstraint("payload_bytes >= 0", name="nonnegative_payload_bytes"),
        CheckConstraint(
            f"validation_status IN ({VALIDATION_STATUSES})", name="valid_validation_status"
        ),
        Index("ix_raw_observations_source_time", "source_record_id", "observed_at"),
        {"schema": INGEST_SCHEMA},
    )

    id: Mapped[int] = mapped_column(PRIMARY_KEY_TYPE, primary_key=True, autoincrement=True)
    source_record_id: Mapped[int] = mapped_column(
        ForeignKey(f"{INGEST_SCHEMA}.source_records.id", ondelete="RESTRICT"), nullable=False
    )
    task_attempt_id: Mapped[int] = mapped_column(
        ForeignKey(f"{INGEST_SCHEMA}.task_attempts.id", ondelete="RESTRICT"), nullable=False
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_object_key: Mapped[str] = mapped_column(Text, nullable=False)
    payload_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    schema_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    parser_version: Mapped[str | None] = mapped_column(String(100))
    validation_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending", server_default="pending"
    )
    retention_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    observation_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class SchemaDefinition(Base):
    """Versioned structural descriptor discovered from raw observations."""

    __tablename__ = "schema_definitions"
    __table_args__ = (
        UniqueConstraint(
            "entity_type",
            "fingerprint",
            name="uq_schema_definitions_entity_fingerprint",
        ),
        CheckConstraint(f"entity_type IN ({ENTITY_TYPES})", name="valid_entity_type"),
        CheckConstraint(f"status IN ({SCHEMA_STATUSES})", name="valid_status"),
        CheckConstraint("sample_count >= 0", name="nonnegative_sample_count"),
        {"schema": INGEST_SCHEMA},
    )

    id: Mapped[int] = mapped_column(PRIMARY_KEY_TYPE, primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    definition: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    sample_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="discovered", server_default="discovered"
    )
    compatible_parser_min: Mapped[str | None] = mapped_column(String(100))
    compatible_parser_max: Mapped[str | None] = mapped_column(String(100))
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class QuarantineRecord(Base):
    """Review queue for fetch, schema, parse or validation failures."""

    __tablename__ = "quarantine_records"
    __table_args__ = (
        CheckConstraint(f"entity_type IN ({ENTITY_TYPES})", name="valid_entity_type"),
        CheckConstraint(f"status IN ({QUARANTINE_STATUSES})", name="valid_status"),
        Index(
            "ix_quarantine_records_open",
            "first_failed_at",
            postgresql_where=text("status = 'open'"),
        ),
        {"schema": INGEST_SCHEMA},
    )

    id: Mapped[int] = mapped_column(PRIMARY_KEY_TYPE, primary_key=True, autoincrement=True)
    raw_observation_id: Mapped[int | None] = mapped_column(
        ForeignKey(f"{INGEST_SCHEMA}.raw_observations.id", ondelete="SET NULL")
    )
    task_attempt_id: Mapped[int] = mapped_column(
        ForeignKey(f"{INGEST_SCHEMA}.task_attempts.id", ondelete="RESTRICT"), nullable=False
    )
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[str] = mapped_column(String(255), nullable=False)
    error_code: Mapped[str] = mapped_column(String(100), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="open", server_default="open"
    )
    resolution: Mapped[str | None] = mapped_column(Text)
    first_failed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    last_failed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    resolved_by: Mapped[str | None] = mapped_column(String(255))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DiscoveryCheckpoint(Base):
    """Opaque provider cursor for resumable discovery."""

    __tablename__ = "discovery_checkpoints"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "discovery_scope",
            "seed_version",
            name="uq_discovery_checkpoints_provider_scope_seed",
        ),
        {"schema": INGEST_SCHEMA},
    )

    id: Mapped[int] = mapped_column(PRIMARY_KEY_TYPE, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    discovery_scope: Mapped[str] = mapped_column(String(255), nullable=False)
    seed_version: Mapped[str] = mapped_column(String(100), nullable=False)
    cursor: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False, default=dict)
    window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )
