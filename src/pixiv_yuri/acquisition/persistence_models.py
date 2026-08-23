"""Persistent, non-secret acquisition safety state for PostgreSQL."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from pixiv_yuri.ingest.models import INGEST_SCHEMA
from pixiv_yuri.shared.database import PRIMARY_KEY_TYPE, Base, utc_now

PERMIT_STATUSES = "'authorized','consumed','transport_failed','cancelled'"
STOP_TRIGGER_SOURCES = "'system','operator','response','schema','budget','approval'"
FIRST_REQUEST_SLOT_STATUSES = "'claimed','completed','failed'"
LIVE_EXECUTION_JOURNAL_STATUSES = (
    "'claimed','send_started','settled','completed','failed','indeterminate'"
)


class AcquisitionDailyBudget(Base):
    """Authoritative daily request and estimated-cost budget per G0 fingerprint."""

    __tablename__ = "acquisition_daily_budgets"
    __table_args__ = (
        UniqueConstraint(
            "approval_fingerprint", "budget_day", name="uq_acquisition_daily_budget_scope"
        ),
        CheckConstraint("request_count >= 0", name="nonnegative_request_count"),
        CheckConstraint("estimated_cost >= 0", name="nonnegative_estimated_cost"),
        CheckConstraint("version >= 0", name="nonnegative_version"),
        {"schema": INGEST_SCHEMA},
    )

    id: Mapped[int] = mapped_column(PRIMARY_KEY_TYPE, primary_key=True, autoincrement=True)
    approval_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    budget_day: Mapped[date] = mapped_column(Date, nullable=False)
    request_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    estimated_cost: Mapped[Decimal] = mapped_column(
        Numeric(14, 6), nullable=False, default=Decimal("0"), server_default="0"
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class AcquisitionRunBudget(Base):
    """Per-run counters and circuit-breaker state bound to one crawl run."""

    __tablename__ = "acquisition_run_budgets"
    __table_args__ = (
        UniqueConstraint("run_id", name="uq_acquisition_run_budget_run"),
        CheckConstraint("request_count >= 0", name="nonnegative_request_count"),
        CheckConstraint("in_flight_count >= 0", name="nonnegative_in_flight_count"),
        CheckConstraint("consecutive_403 >= 0", name="nonnegative_consecutive_403"),
        CheckConstraint("consecutive_429 >= 0", name="nonnegative_consecutive_429"),
        CheckConstraint("version >= 0", name="nonnegative_version"),
        {"schema": INGEST_SCHEMA},
    )

    id: Mapped[int] = mapped_column(PRIMARY_KEY_TYPE, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey(f"{INGEST_SCHEMA}.crawl_runs.id", ondelete="CASCADE"), nullable=False
    )
    approval_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    request_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    in_flight_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    consecutive_403: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    consecutive_429: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    stop_reason: Mapped[str | None] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class AcquisitionRequestPermit(Base):
    """Durable one-use permit reservation created before transport."""

    __tablename__ = "acquisition_request_permits"
    __table_args__ = (
        UniqueConstraint("permit_id", name="uq_acquisition_request_permit_id"),
        UniqueConstraint(
            "run_budget_id", "sequence", name="uq_acquisition_request_permit_sequence"
        ),
        UniqueConstraint(
            "run_budget_id",
            "request_key_hash",
            name="uq_acquisition_request_permit_logical_key",
        ),
        CheckConstraint("sequence >= 1", name="positive_sequence"),
        CheckConstraint("estimated_cost >= 0", name="nonnegative_estimated_cost"),
        CheckConstraint(f"status IN ({PERMIT_STATUSES})", name="valid_status"),
        CheckConstraint(
            "response_status IS NULL OR (response_status >= 100 AND response_status <= 599)",
            name="valid_response_status",
        ),
        {"schema": INGEST_SCHEMA},
    )

    id: Mapped[int] = mapped_column(PRIMARY_KEY_TYPE, primary_key=True, autoincrement=True)
    permit_id: Mapped[str] = mapped_column(String(36), nullable=False)
    run_budget_id: Mapped[int] = mapped_column(
        ForeignKey(f"{INGEST_SCHEMA}.acquisition_run_budgets.id", ondelete="CASCADE"),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    request_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    approval_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    estimated_cost: Mapped[Decimal] = mapped_column(Numeric(14, 6), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="authorized", server_default="authorized"
    )
    authorized_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    response_status: Mapped[int | None] = mapped_column(Integer)


class AcquisitionStopEvent(Base):
    """Append-only, non-secret evidence for every persistent stop transition."""

    __tablename__ = "acquisition_stop_events"
    __table_args__ = (
        CheckConstraint(
            f"trigger_source IN ({STOP_TRIGGER_SOURCES})", name="valid_trigger_source"
        ),
        {"schema": INGEST_SCHEMA},
    )

    id: Mapped[int] = mapped_column(PRIMARY_KEY_TYPE, primary_key=True, autoincrement=True)
    approval_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    run_id: Mapped[int | None] = mapped_column(
        ForeignKey(f"{INGEST_SCHEMA}.crawl_runs.id", ondelete="SET NULL")
    )
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    trigger_source: Mapped[str] = mapped_column(String(32), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class AcquisitionFirstRequestSlot(Base):
    """Permanent one-attempt slot for the first request under one G0 approval."""

    __tablename__ = "acquisition_first_request_slots"
    __table_args__ = (
        UniqueConstraint(
            "approval_fingerprint", name="uq_acquisition_first_request_slot_approval"
        ),
        CheckConstraint(
            f"status IN ({FIRST_REQUEST_SLOT_STATUSES})",
            name="valid_first_request_slot_status",
        ),
        CheckConstraint(
            "(status = 'claimed' AND resolved_at IS NULL) OR "
            "(status IN ('completed','failed') AND resolved_at IS NOT NULL)",
            name="valid_first_request_slot_resolution",
        ),
        {"schema": INGEST_SCHEMA},
    )

    id: Mapped[int] = mapped_column(PRIMARY_KEY_TYPE, primary_key=True, autoincrement=True)
    approval_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    run_id: Mapped[int] = mapped_column(
        ForeignKey(f"{INGEST_SCHEMA}.crawl_runs.id", ondelete="RESTRICT"), nullable=False
    )
    request_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="claimed", server_default="claimed"
    )
    claimed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AcquisitionLiveExecutionJournal(Base):
    """Durable one-way evidence around the only live send attempt."""

    __tablename__ = "acquisition_live_execution_journals"
    __table_args__ = (
        UniqueConstraint("slot_id", name="uq_live_execution_journal_slot"),
        UniqueConstraint("permit_id", name="uq_live_execution_journal_permit"),
        CheckConstraint(
            f"status IN ({LIVE_EXECUTION_JOURNAL_STATUSES})",
            name="valid_live_execution_journal_status",
        ),
        CheckConstraint("version >= 0", name="nonnegative_live_execution_version"),
        CheckConstraint(
            "(status = 'claimed' AND permit_id IS NULL AND send_started_at IS NULL "
            "AND settled_at IS NULL AND resolved_at IS NULL AND failure_code IS NULL) OR "
            "(status = 'send_started' AND permit_id IS NOT NULL "
            "AND send_started_at IS NOT NULL AND settled_at IS NULL "
            "AND resolved_at IS NULL AND failure_code IS NULL) OR "
            "(status = 'settled' AND permit_id IS NOT NULL "
            "AND send_started_at IS NOT NULL AND settled_at IS NOT NULL "
            "AND resolved_at IS NULL AND failure_code IS NULL) OR "
            "(status = 'completed' AND permit_id IS NOT NULL "
            "AND send_started_at IS NOT NULL AND settled_at IS NOT NULL "
            "AND resolved_at IS NOT NULL AND failure_code IS NULL) OR "
            "(status = 'failed' AND resolved_at IS NOT NULL "
            "AND failure_code IS NOT NULL AND "
            "((permit_id IS NULL AND send_started_at IS NULL AND settled_at IS NULL) OR "
            "(permit_id IS NOT NULL AND send_started_at IS NOT NULL "
            "AND settled_at IS NOT NULL))) OR "
            "(status = 'indeterminate' AND permit_id IS NOT NULL "
            "AND send_started_at IS NOT NULL AND settled_at IS NULL "
            "AND resolved_at IS NOT NULL AND failure_code IS NOT NULL)",
            name="valid_live_execution_journal_shape",
        ),
        {"schema": INGEST_SCHEMA},
    )

    id: Mapped[int] = mapped_column(PRIMARY_KEY_TYPE, primary_key=True, autoincrement=True)
    approval_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    run_id: Mapped[int] = mapped_column(
        ForeignKey(f"{INGEST_SCHEMA}.crawl_runs.id", ondelete="RESTRICT"), nullable=False
    )
    slot_id: Mapped[int] = mapped_column(
        ForeignKey(
            f"{INGEST_SCHEMA}.acquisition_first_request_slots.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    request_binding_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    permit_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey(
            f"{INGEST_SCHEMA}.acquisition_request_permits.permit_id",
            ondelete="RESTRICT",
        ),
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="claimed", server_default="claimed"
    )
    failure_code: Mapped[str | None] = mapped_column(String(64))
    claimed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    send_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
