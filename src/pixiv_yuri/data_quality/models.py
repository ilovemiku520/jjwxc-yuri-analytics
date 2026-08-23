"""Strict contracts for offline schema decisions and validation reports."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pixiv_yuri.acquisition.models import EntityType


class SchemaDecision(StrEnum):
    """Human decision for one exact structural fingerprint."""

    APPROVED = "approved"
    REJECTED = "rejected"


class ValidationState(StrEnum):
    """Whether an observation may proceed to parser output."""

    VALID = "valid"
    QUARANTINED = "quarantined"


class SchemaPolicyEntry(BaseModel):
    """One exact schema decision and optional parser route."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entity_type: EntityType
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision: SchemaDecision
    parser_id: str | None = Field(default=None, min_length=1, max_length=100)
    parser_version: str | None = Field(default=None, min_length=1, max_length=100)
    note: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def parser_route_matches_decision(self) -> Self:
        has_parser = self.parser_id is not None and self.parser_version is not None
        has_partial_parser = (self.parser_id is None) != (self.parser_version is None)
        if has_partial_parser:
            raise ValueError("parser_id and parser_version must be provided together.")
        if self.decision == SchemaDecision.APPROVED and not has_parser:
            raise ValueError("Approved schemas require an exact parser route.")
        if self.decision == SchemaDecision.REJECTED and has_parser:
            raise ValueError("Rejected schemas cannot route to a parser.")
        return self


class SchemaPolicy(BaseModel):
    """Fixture-only allow/reject list; it is not production G1 approval."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    policy_version: int = Field(default=1, ge=1)
    scope: Literal["offline_fixture"]
    provider: str = Field(min_length=1, max_length=100)
    entries: tuple[SchemaPolicyEntry, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def entries_must_be_unique(self) -> Self:
        keys = [(entry.entity_type, entry.fingerprint) for entry in self.entries]
        if len(keys) != len(set(keys)):
            raise ValueError("Schema policy entries must have unique entity/fingerprint keys.")
        return self

    def find(self, entity_type: EntityType, fingerprint: str) -> SchemaPolicyEntry | None:
        """Return an exact policy entry without wildcard fallback."""
        return next(
            (
                entry
                for entry in self.entries
                if entry.entity_type == entity_type and entry.fingerprint == fingerprint
            ),
            None,
        )


class ValidationItem(BaseModel):
    """Redacted outcome for one fixture observation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entity_type: EntityType
    source_id: str
    state: ValidationState
    code: str
    detail: str
    payload_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    schema_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    parser_id: str | None = None
    parser_version: str | None = None


class ValidationReport(BaseModel):
    """Machine-readable result of applying one exact fixture policy."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    report_version: int = 1
    generated_at: datetime
    provider: str
    policy_version: int
    policy_scope: Literal["offline_fixture"] = "offline_fixture"
    valid_count: int = Field(ge=0)
    quarantined_count: int = Field(ge=0)
    items: tuple[ValidationItem, ...]
