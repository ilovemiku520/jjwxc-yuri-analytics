"""Machine-verifiable G0 approval contract for future live acquisition."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

REQUIRED_STOP_CONDITIONS = frozenset(
    {
        "repeated_403",
        "repeated_429",
        "schema_drift",
        "daily_request_cap",
        "daily_cost_cap",
        "monthly_cost_cap",
        "complaint_or_takedown",
        "incident_owner_request",
    }
)


def _default_access_methods() -> set[
    Literal["browser_current_work", "pixiv_app_api"]
]:
    return {"browser_current_work"}


class SourceScope(BaseModel):
    """Conservative source, visibility, rating, and field boundary."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    page_types: set[Literal["public_work", "public_author", "public_tag"]] = Field(
        min_length=1
    )
    access_methods: set[Literal["browser_current_work", "pixiv_app_api"]] = Field(
        default_factory=_default_access_methods, min_length=1
    )
    allowed_fields: set[str] = Field(min_length=1)
    prohibited_fields: set[str] = Field(min_length=1)
    authentication_mode: Literal["none", "user_managed_session"]
    content_visibility: Literal["unauthenticated_public", "authenticated_public"]
    allowed_age_ratings: set[Literal["all_ages", "r18", "r18g"]] = Field(min_length=1)
    password_collection_allowed: Literal[False]
    secret_persistence_allowed: Literal[False]
    secret_logging_allowed: Literal[False]
    private_content_allowed: Literal[False]
    deleted_content_allowed: Literal[False]
    access_control_bypass_allowed: Literal[False]
    media_storage_allowed: Literal[False]

    @model_validator(mode="after")
    def fields_must_not_overlap(self) -> SourceScope:
        overlap = self.allowed_fields & self.prohibited_fields
        if overlap:
            raise ValueError(f"Allowed and prohibited fields overlap: {sorted(overlap)}")
        authenticated = self.authentication_mode == "user_managed_session"
        if authenticated != (self.content_visibility == "authenticated_public"):
            raise ValueError(
                "A user-managed session is required exactly for authenticated-public scope."
            )
        if {"r18", "r18g"} & self.allowed_age_ratings and not authenticated:
            raise ValueError("Age-restricted ratings require a user-managed session.")
        return self


class TrafficLimits(BaseModel):
    """Hard ceilings for the initial approved representative sample."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    requests_per_minute: int = Field(ge=1, le=30)
    concurrency: int = Field(ge=1, le=2)
    daily_request_cap: int = Field(ge=1, le=1000)
    per_run_request_cap: int = Field(ge=1, le=250)
    request_timeout_seconds: int = Field(ge=1, le=30)

    @model_validator(mode="after")
    def run_cap_must_fit_daily_cap(self) -> TrafficLimits:
        if self.per_run_request_cap > self.daily_request_cap:
            raise ValueError("Per-run request cap cannot exceed the daily cap.")
        return self


class CostLimits(BaseModel):
    """Hard monetary limits for a future paid provider."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    currency: Literal["CNY", "USD"]
    daily_cap: float = Field(gt=0, le=50)
    monthly_cap: float = Field(gt=0, le=500)

    @model_validator(mode="after")
    def monthly_cap_must_cover_daily_cap(self) -> CostLimits:
        if self.monthly_cap < self.daily_cap:
            raise ValueError("Monthly cost cap cannot be lower than the daily cap.")
        return self


class RetentionPolicy(BaseModel):
    """Data minimization boundary for the initial live sample."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    raw_metadata_days: int = Field(ge=1, le=30)
    audit_metadata_days: int = Field(ge=30, le=3650)
    store_raw_payloads_in_database: Literal[False]
    publication_mode: Literal["private_research"]


class G0Approval(BaseModel):
    """Complete, bounded, expiring approval required before live access."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: Literal[2]
    status: Literal["approved"]
    purpose: str = Field(min_length=10, max_length=500)
    accountable_owner: str = Field(min_length=2, max_length=100)
    approved_by: str = Field(min_length=2, max_length=100)
    incident_contact_role: str = Field(min_length=2, max_length=100)
    approved_at: datetime
    expires_at: datetime
    terms_reviewed_at: datetime
    terms_reference: str = Field(min_length=5, max_length=500)
    source_scope: SourceScope
    traffic_limits: TrafficLimits
    cost_limits: CostLimits
    retention: RetentionPolicy
    stop_conditions: set[str] = Field(min_length=len(REQUIRED_STOP_CONDITIONS))

    @model_validator(mode="after")
    def validate_decision_window_and_stops(self) -> G0Approval:
        for field_name, value in (
            ("approved_at", self.approved_at),
            ("expires_at", self.expires_at),
            ("terms_reviewed_at", self.terms_reviewed_at),
        ):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{field_name} must include a timezone.")
        if self.terms_reviewed_at > self.approved_at:
            raise ValueError("Terms review cannot occur after approval.")
        if self.expires_at <= self.approved_at:
            raise ValueError("Approval expiry must be after approval time.")
        if self.expires_at - self.approved_at > timedelta(days=90):
            raise ValueError("Initial G0 approval cannot remain valid for more than 90 days.")
        missing_stops = REQUIRED_STOP_CONDITIONS - self.stop_conditions
        if missing_stops:
            raise ValueError(f"Missing required stop conditions: {sorted(missing_stops)}")
        return self


def load_active_g0_approval(path: Path, *, now: datetime | None = None) -> G0Approval:
    """Load a complete approval and reject expired or not-yet-active decisions."""
    approval = G0Approval.model_validate_json(path.read_text(encoding="utf-8"))
    checked_at = now or datetime.now(UTC)
    if checked_at.tzinfo is None or checked_at.utcoffset() is None:
        raise ValueError("Approval check time must include a timezone.")
    if checked_at < approval.approved_at:
        raise ValueError("G0 approval is not active yet.")
    if checked_at >= approval.expires_at:
        raise ValueError("G0 approval has expired.")
    return approval


def approval_fingerprint(approval: G0Approval) -> str:
    """Return a stable fingerprint for audit and deployment binding."""
    canonical = _canonicalize(approval.model_dump(mode="json"))
    encoded = json.dumps(canonical, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _canonicalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _canonicalize(child) for key, child in sorted(value.items())}
    if isinstance(value, list):
        children = [_canonicalize(child) for child in value]
        return sorted(children, key=lambda child: json.dumps(child, sort_keys=True))
    return value
