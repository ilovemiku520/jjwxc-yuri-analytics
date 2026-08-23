"""Typed acquisition values shared by fixtures and future approved providers."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EntityType(StrEnum):
    """Source record types supported by the Phase 0 probe."""

    WORK = "work"
    AUTHOR = "author"
    TAG_PAGE = "tag_page"
    SEARCH_PAGE = "search_page"


class AcquisitionRequest(BaseModel):
    """A stable logical request, independent of transport details."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entity_type: EntityType
    source_id: str = Field(min_length=1, max_length=255)

    @property
    def key(self) -> tuple[EntityType, str]:
        """Return the request's provider-local identity."""
        return self.entity_type, self.source_id


class RawResponse(BaseModel):
    """An immutable raw source observation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str = Field(min_length=1, max_length=100)
    entity_type: EntityType
    source_id: str = Field(min_length=1, max_length=255)
    observed_at: datetime
    status_code: int = Field(ge=100, le=599)
    content_type: str = Field(min_length=1, max_length=255)
    body: bytes
    source_url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("observed_at")
    @classmethod
    def observed_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        """Reject ambiguous local timestamps."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at must include a timezone")
        return value

    @property
    def payload_sha256(self) -> str:
        """Return a stable content hash without changing the payload."""
        return hashlib.sha256(self.body).hexdigest()

    def json_value(self) -> Any:
        """Decode an UTF-8 JSON fixture payload."""
        if "json" not in self.content_type.lower():
            raise ValueError(f"Unsupported content type for schema probe: {self.content_type}")
        return json.loads(self.body.decode("utf-8"))

