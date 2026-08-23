"""Persistent minimized controls for private consumer API access."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from pixiv_yuri.ingest.models import INGEST_SCHEMA
from pixiv_yuri.shared.database import PRIMARY_KEY_TYPE, Base, utc_now


class ApiConsumerRateLimitWindow(Base):
    """One bounded fixed-window counter keyed only by a subject digest."""

    __tablename__ = "api_consumer_rate_limit_windows"
    __table_args__ = (
        CheckConstraint("length(consumer_key) = 64", name="consumer_key_sha256_length"),
        CheckConstraint("request_count >= 1", name="positive_request_count"),
        Index("ix_api_consumer_rate_limit_windows_updated", "updated_at"),
        {"schema": INGEST_SCHEMA},
    )

    consumer_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    request_count: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class ApiConsumerAccessAudit(Base):
    """Append-only access decision without raw identity or request target data."""

    __tablename__ = "api_consumer_access_audits"
    __table_args__ = (
        CheckConstraint(
            "consumer_key IS NULL OR length(consumer_key) = 64",
            name="consumer_key_sha256_length",
        ),
        CheckConstraint(
            "status_code >= 100 AND status_code <= 599", name="valid_status_code"
        ),
        CheckConstraint("retention_until > occurred_at", name="future_retention"),
        Index("ix_api_consumer_access_audits_occurred", "occurred_at", "id"),
        Index("ix_api_consumer_access_audits_retention", "retention_until"),
        {"schema": INGEST_SCHEMA},
    )

    id: Mapped[int] = mapped_column(PRIMARY_KEY_TYPE, primary_key=True, autoincrement=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    retention_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    consumer_key: Mapped[str | None] = mapped_column(String(64))
    method: Mapped[str] = mapped_column(String(16), nullable=False)
    route_template: Mapped[str] = mapped_column(String(255), nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    auth_outcome: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
