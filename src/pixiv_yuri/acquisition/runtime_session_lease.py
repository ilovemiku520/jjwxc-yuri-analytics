"""Opaque, credential-free identity for one future runtime session send."""

from __future__ import annotations

import threading
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal, NoReturn
from uuid import uuid4

AgeRating = Literal["all_ages", "r18", "r18g"]
ContentVisibility = Literal["authenticated_public"]
_VALID_AGE_RATINGS = frozenset({"all_ages", "r18", "r18g"})


class RuntimeSessionLeaseError(RuntimeError):
    """Safe rejection that contains no session material."""


class RuntimeSessionLeaseState(StrEnum):
    """One-way in-process lease states."""

    ACTIVE = "active"
    CONSUMED = "consumed"
    BURNED = "burned"


@dataclass(frozen=True, slots=True)
class RuntimeSessionLeaseConsumption:
    """Non-authorizing evidence emitted after a successful atomic consume."""

    lease_id: str
    consumed_at: datetime
    expires_at: datetime


class RuntimeSessionLease:
    """Random-identity lease whose scope and expiry cannot be changed or copied."""

    __slots__ = (
        "_allowed_age_ratings",
        "_content_visibility",
        "_established_at",
        "_expires_at",
        "_lease_id",
        "_lock",
        "_state",
    )

    def __init__(
        self,
        *,
        established_at: datetime,
        expires_at: datetime,
        content_visibility: ContentVisibility = "authenticated_public",
        allowed_age_ratings: Iterable[AgeRating],
    ) -> None:
        established = _aware_utc(established_at)
        expires = _aware_utc(expires_at)
        if expires <= established:
            raise ValueError("Runtime session lease expiry must follow establishment.")
        ratings = _normalize_ratings(allowed_age_ratings)
        if content_visibility != "authenticated_public":
            raise ValueError("Runtime session lease visibility is unsupported.")
        self._lease_id = str(uuid4())
        self._established_at = established
        self._expires_at = expires
        self._content_visibility = content_visibility
        self._allowed_age_ratings = ratings
        self._state = RuntimeSessionLeaseState.ACTIVE
        self._lock = threading.Lock()

    @property
    def lease_id(self) -> str:
        """Return a random non-secret correlation identifier."""
        return self._lease_id

    @property
    def established_at(self) -> datetime:
        return self._established_at

    @property
    def expires_at(self) -> datetime:
        """Return the single expiry shared by readiness and the future broker."""
        return self._expires_at

    @property
    def content_visibility(self) -> ContentVisibility:
        return self._content_visibility

    @property
    def allowed_age_ratings(self) -> frozenset[AgeRating]:
        """Return deeply immutable approved rating scope."""
        return self._allowed_age_ratings

    @property
    def state(self) -> RuntimeSessionLeaseState:
        with self._lock:
            return self._state

    def ensure_active(self, *, now: datetime) -> None:
        """Check readiness without consuming; invalid wall-clock windows burn the lease."""
        checked_at = _aware_utc(now)
        with self._lock:
            if self._state != RuntimeSessionLeaseState.ACTIVE:
                raise RuntimeSessionLeaseError("Runtime session lease is unavailable.")
            if not self._established_at <= checked_at < self._expires_at:
                self._state = RuntimeSessionLeaseState.BURNED
                raise RuntimeSessionLeaseError("Runtime session lease is inactive.")

    def consume(
        self,
        *,
        now: datetime,
        required_visibility: ContentVisibility = "authenticated_public",
        required_age_ratings: Iterable[AgeRating],
    ) -> RuntimeSessionLeaseConsumption:
        """Atomically burn the only send opportunity before validating its scope."""
        checked_at = _aware_utc(now)
        required_ratings = _normalize_ratings(required_age_ratings)
        with self._lock:
            if self._state != RuntimeSessionLeaseState.ACTIVE:
                raise RuntimeSessionLeaseError("Runtime session lease is unavailable.")
            self._state = RuntimeSessionLeaseState.BURNED
            if not self._established_at <= checked_at < self._expires_at:
                raise RuntimeSessionLeaseError("Runtime session lease is inactive.")
            if (
                required_visibility != self._content_visibility
                or not required_ratings.issubset(self._allowed_age_ratings)
            ):
                raise RuntimeSessionLeaseError("Runtime session lease scope is insufficient.")
            self._state = RuntimeSessionLeaseState.CONSUMED
            return RuntimeSessionLeaseConsumption(
                lease_id=self._lease_id,
                consumed_at=checked_at,
                expires_at=self._expires_at,
            )

    def burn(self) -> None:
        """Idempotently remove an unused lease without enabling a send."""
        with self._lock:
            if self._state == RuntimeSessionLeaseState.ACTIVE:
                self._state = RuntimeSessionLeaseState.BURNED

    def __copy__(self) -> NoReturn:
        raise TypeError("Runtime session leases cannot be copied.")

    def __deepcopy__(self, memo: object) -> NoReturn:
        del memo
        raise TypeError("Runtime session leases cannot be copied.")

    def __reduce__(self) -> NoReturn:
        raise TypeError("Runtime session leases cannot be serialized.")

    def __repr__(self) -> str:
        return (
            "RuntimeSessionLease(lease_id="
            f"{self._lease_id!r}, state={self.state.value!r}, "
            f"expires_at={self._expires_at.isoformat()!r}, material=[ABSENT])"
        )


def require_same_runtime_session_lease(
    readiness_lease: RuntimeSessionLease,
    broker_lease: RuntimeSessionLease,
) -> RuntimeSessionLease:
    """Require exact object identity; equal public fields never substitute a lease."""
    if readiness_lease is not broker_lease or (
        readiness_lease.lease_id != broker_lease.lease_id
    ):
        raise RuntimeSessionLeaseError("Runtime session lease identity does not match.")
    return readiness_lease


def _normalize_ratings(values: Iterable[AgeRating]) -> frozenset[AgeRating]:
    try:
        ratings = frozenset(values)
    except TypeError:
        raise ValueError("Runtime session lease ratings are invalid.") from None
    if not ratings or not ratings.issubset(_VALID_AGE_RATINGS):
        raise ValueError("Runtime session lease ratings are invalid.")
    return ratings


def _aware_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Runtime session lease timestamps must include a timezone.")
    return value.astimezone(UTC)
