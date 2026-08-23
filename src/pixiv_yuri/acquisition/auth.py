"""Credential-free session capabilities for approved authenticated acquisition."""

from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import AbstractContextManager, nullcontext
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SessionCapabilityError(RuntimeError):
    """Raised when an authenticated session cannot satisfy the approved scope."""


class SessionCapability(BaseModel):
    """Non-secret proof of session scope; it never contains cookies or credentials."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    established_at: datetime
    expires_at: datetime
    content_visibility: Literal["authenticated_public"] = "authenticated_public"
    allowed_age_ratings: frozenset[Literal["all_ages", "r18", "r18g"]] = Field(
        min_length=1
    )

    @field_validator("established_at", "expires_at")
    @classmethod
    def timestamps_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Session timestamps must include a timezone.")
        return value

    @model_validator(mode="after")
    def expiry_must_follow_establishment(self) -> SessionCapability:
        if self.expires_at <= self.established_at:
            raise ValueError("Session expiry must be after establishment.")
        return self

    def ensure_active(self, checked_at: datetime) -> None:
        """Fail closed when the capability is not active at the requested time."""
        if checked_at.tzinfo is None or checked_at.utcoffset() is None:
            raise ValueError("Session check time must include a timezone.")
        if not (self.established_at <= checked_at < self.expires_at):
            raise SessionCapabilityError("Authenticated session is inactive.")


class SessionBroker(ABC):
    """Own session establishment while exposing only a non-secret capability."""

    @abstractmethod
    def open_session(self) -> AbstractContextManager[SessionCapability]:
        """Open one bounded session without returning credentials to the Provider."""
        raise NotImplementedError


class OfflineSessionBroker(SessionBroker):
    """Network-free broker for fixtures and tests; it accepts no secret material."""

    def __init__(self, capability: SessionCapability) -> None:
        self._capability = capability

    def open_session(self) -> AbstractContextManager[SessionCapability]:
        """Return the configured non-secret capability for an offline operation."""
        return nullcontext(self._capability)
