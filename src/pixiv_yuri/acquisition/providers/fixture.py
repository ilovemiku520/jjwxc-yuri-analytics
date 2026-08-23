"""A deterministic, network-free provider backed by approved JSON fixtures."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from pixiv_yuri.acquisition.base import AcquisitionProvider
from pixiv_yuri.acquisition.models import AcquisitionRequest, EntityType, RawResponse


class FixtureProviderError(ValueError):
    """Raised for an invalid fixture manifest or fixture payload."""


class FixtureRecord(BaseModel):
    """One raw response described by a manifest."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entity_type: EntityType
    source_id: str = Field(min_length=1, max_length=255)
    observed_at: datetime
    path: Path
    status_code: int = Field(default=200, ge=100, le=599)
    content_type: str = "application/json"
    source_url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, str | int | float | bool | None] = Field(default_factory=dict)

    @field_validator("path")
    @classmethod
    def fixture_path_must_be_relative_json(cls, value: Path) -> Path:
        """Reject absolute paths, traversal and non-JSON fixture types early."""
        if value.is_absolute() or ".." in value.parts:
            raise ValueError("Fixture paths must be relative and cannot contain '..'.")
        if value.suffix.lower() != ".json":
            raise ValueError("Fixture payloads must use the .json suffix.")
        return value

    @field_validator("observed_at")
    @classmethod
    def observed_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        """Reject ambiguous fixture timestamps before a RawResponse is built."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at must include a timezone")
        return value


class FixtureManifest(BaseModel):
    """Versioned collection of deterministic fixture records."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: int = Field(default=1, ge=1)
    provider: str = Field(default="fixture", min_length=1, max_length=100)
    records: tuple[FixtureRecord, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def reject_duplicate_keys(self) -> FixtureManifest:
        """Ensure a request resolves to exactly one fixture."""
        keys = [(record.entity_type, record.source_id) for record in self.records]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate (entity_type, source_id) fixture records are not allowed.")
        return self


class FixtureProvider(AcquisitionProvider):
    """Read synthetic or approved JSON files without importing a network client."""

    def __init__(self, manifest_path: Path | str) -> None:
        self._manifest_path = Path(manifest_path).resolve()
        self._root = self._manifest_path.parent
        self._manifest = self._load_manifest()
        self._records = {
            (record.entity_type, record.source_id): record for record in self._manifest.records
        }

    @property
    def name(self) -> str:
        """Return the manifest's stable provider name."""
        return self._manifest.provider

    def list_requests(
        self, entity_type: EntityType | None = None
    ) -> tuple[AcquisitionRequest, ...]:
        """List records in manifest order, optionally restricted by entity type."""
        return tuple(
            AcquisitionRequest(entity_type=record.entity_type, source_id=record.source_id)
            for record in self._manifest.records
            if entity_type is None or record.entity_type == entity_type
        )

    def fetch(self, request: AcquisitionRequest) -> RawResponse:
        """Read and validate one JSON fixture inside the manifest directory."""
        record = self._records.get(request.key)
        if record is None:
            raise FixtureProviderError(
                f"Unknown fixture request: {request.entity_type.value}/{request.source_id}"
            )

        fixture_path = (self._root / record.path).resolve()
        if not fixture_path.is_relative_to(self._root):
            raise FixtureProviderError(f"Fixture escaped manifest directory: {record.path}")
        if not fixture_path.is_file():
            raise FixtureProviderError(f"Fixture does not exist: {record.path}")

        try:
            body = fixture_path.read_bytes()
            json.loads(body.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise FixtureProviderError(f"Invalid JSON fixture {record.path}: {exc}") from exc

        return RawResponse(
            provider=self.name,
            entity_type=record.entity_type,
            source_id=record.source_id,
            observed_at=record.observed_at,
            status_code=record.status_code,
            content_type=record.content_type,
            body=body,
            source_url=record.source_url,
            headers=record.headers,
            metadata={**record.metadata, "fixture_path": record.path.as_posix()},
        )

    def _load_manifest(self) -> FixtureManifest:
        """Load a strict UTF-8 JSON manifest."""
        try:
            raw = json.loads(self._manifest_path.read_text(encoding="utf-8"))
            return FixtureManifest.model_validate(raw)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValidationError) as exc:
            raise FixtureProviderError(
                f"Cannot load fixture manifest {self._manifest_path}: {exc}"
            ) from exc
