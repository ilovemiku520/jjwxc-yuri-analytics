"""Report contracts for schema discovery and drift review."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from pixiv_yuri.acquisition.models import EntityType


class JsonType(StrEnum):
    """JSON value types with integers separated from other numbers."""

    NULL = "null"
    BOOLEAN = "boolean"
    INTEGER = "integer"
    NUMBER = "number"
    STRING = "string"
    OBJECT = "object"
    ARRAY = "array"


class Stability(StrEnum):
    """Simple field stability classification for human review."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class SampleProfile(BaseModel):
    """One source sample and its deterministic fingerprints."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: str
    payload_sha256: str
    schema_fingerprint: str


class FieldProfile(BaseModel):
    """Aggregated availability and types for one JSON path."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str
    availability: float = Field(ge=0, le=1)
    present_count: int = Field(ge=0)
    sample_count: int = Field(gt=0)
    types: tuple[JsonType, ...]
    required: bool
    nullable: bool
    stability: Stability
    examples: tuple[str, ...] = ()


class EntitySchemaReport(BaseModel):
    """Aggregate schema evidence for one source entity type."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entity_type: EntityType
    sample_count: int = Field(gt=0)
    samples: tuple[SampleProfile, ...]
    fields: tuple[FieldProfile, ...]


class ProbeError(BaseModel):
    """A skipped fixture and its stable error category."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entity_type: EntityType
    source_id: str
    code: str
    detail: str


class SchemaReport(BaseModel):
    """Versioned result of an offline probe run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    report_version: int = 1
    generated_at: datetime
    provider: str
    entity_reports: tuple[EntitySchemaReport, ...]
    errors: tuple[ProbeError, ...] = ()


class FieldChange(BaseModel):
    """One reviewable schema change."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entity_type: EntityType
    path: str
    change: str
    before: str | float | None = None
    after: str | float | None = None
    severity: str


class SchemaDiff(BaseModel):
    """Deterministic comparison between two schema reports."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    diff_version: int = 1
    baseline_generated_at: datetime
    candidate_generated_at: datetime
    changes: tuple[FieldChange, ...]
    breaking_change_count: int = Field(ge=0)

