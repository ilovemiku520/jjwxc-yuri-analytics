"""Parser boundary between immutable observations and future domain models."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from pixiv_yuri.acquisition.models import EntityType, RawResponse


class ParserError(ValueError):
    """Raised when an approved parser cannot safely parse one response."""


class ParsedEnvelope(BaseModel):
    """Transient parser output; it is not a production catalog schema."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    parser_id: str
    parser_version: str
    entity_type: EntityType
    source_id: str
    observed_at: datetime
    schema_fingerprint: str
    document: dict[str, Any]


class PayloadParser(ABC):
    """Parse one policy-approved response without performing source access."""

    @property
    @abstractmethod
    def parser_id(self) -> str:
        """Return a stable parser implementation identifier."""
        raise NotImplementedError

    @property
    @abstractmethod
    def version(self) -> str:
        """Return the exact parser version used for provenance."""
        raise NotImplementedError

    @property
    @abstractmethod
    def supported_entity_types(self) -> frozenset[EntityType]:
        """Return source entity types this parser accepts."""
        raise NotImplementedError

    @abstractmethod
    def parse(self, response: RawResponse) -> ParsedEnvelope:
        """Parse an immutable response into a transient typed envelope."""
        raise NotImplementedError
