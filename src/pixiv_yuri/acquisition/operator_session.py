"""No-echo, runtime-only operator session values with bounded lifetime."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from getpass import getpass
from typing import Literal

from pixiv_yuri.acquisition.runtime_session_lease import (
    AgeRating,
    RuntimeSessionLease,
    RuntimeSessionLeaseError,
)


class RuntimeSessionError(RuntimeError):
    """Raised without session details when a runtime lease is invalid."""


class RuntimeSession:
    """Callable cookie supplier backed by a best-effort zeroizable bytearray."""

    __slots__ = ("_buffer", "_closed", "_expires_at", "_runtime_session_lease")

    def __init__(
        self,
        buffer: bytearray,
        expires_at: datetime,
        *,
        established_at: datetime | None = None,
        content_visibility: Literal["authenticated_public"] = "authenticated_public",
        allowed_age_ratings: frozenset[AgeRating] = frozenset(
            {"all_ages", "r18", "r18g"}
        ),
    ) -> None:
        if not buffer:
            raise ValueError("Runtime session value cannot be empty.")
        if expires_at.tzinfo is None or expires_at.utcoffset() is None:
            raise ValueError("Runtime session expiry must include a timezone.")
        self._buffer = buffer
        self._expires_at = expires_at.astimezone(UTC)
        self._closed = False
        established = established_at or datetime.now(UTC)
        self._runtime_session_lease = RuntimeSessionLease(
            established_at=established,
            expires_at=self._expires_at,
            content_visibility=content_visibility,
            allowed_age_ratings=allowed_age_ratings,
        )

    @property
    def expires_at(self) -> datetime:
        """Return only the non-secret expiry timestamp."""
        return self._expires_at

    @property
    def closed(self) -> bool:
        """Report whether the mutable session buffer has been cleared."""
        return self._closed

    @property
    def runtime_session_lease(self) -> RuntimeSessionLease:
        """Expose only the non-secret lease identity bound to this buffer."""
        return self._runtime_session_lease

    def reveal_for_request(
        self,
        *,
        now: datetime | None = None,
        required_visibility: Literal["authenticated_public"] = "authenticated_public",
        required_age_ratings: frozenset[AgeRating] | None = None,
    ) -> str:
        """Decode a short-lived request copy after checking closure and expiry."""
        checked_at = now or datetime.now(UTC)
        if checked_at.tzinfo is None or checked_at.utcoffset() is None:
            raise ValueError("Runtime session check time must include a timezone.")
        checked_at = checked_at.astimezone(UTC)
        if self._closed:
            raise RuntimeSessionError("Runtime session is closed.")
        try:
            self._runtime_session_lease.consume(
                now=checked_at,
                required_visibility=required_visibility,
                required_age_ratings=(
                    required_age_ratings
                    if required_age_ratings is not None
                    else self._runtime_session_lease.allowed_age_ratings
                ),
            )
        except RuntimeSessionLeaseError as exc:
            if checked_at >= self._expires_at:
                self.close()
                raise RuntimeSessionError("Runtime session has expired.") from None
            raise RuntimeSessionError("Runtime session is unavailable.") from exc
        if checked_at >= self._expires_at:
            self.close()
            raise RuntimeSessionError("Runtime session has expired.")
        return self._buffer.decode("utf-8")

    def __call__(self) -> str:
        """Supply one request-scoped immutable copy to an authenticated broker."""
        return self.reveal_for_request()

    def close(self) -> None:
        """Overwrite the mutable buffer and prevent subsequent use."""
        if self._closed:
            return
        for index in range(len(self._buffer)):
            self._buffer[index] = 0
        self._runtime_session_lease.burn()
        self._closed = True

    def __enter__(self) -> RuntimeSession:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def __repr__(self) -> str:
        return (
            "RuntimeSession(value=[REDACTED], "
            f"expires_at={self._expires_at.isoformat()}, closed={self._closed})"
        )


class OperatorSessionFactory:
    """Read a session value only through an injected or no-echo terminal reader."""

    def __init__(self, reader: Callable[[str], str] | None = None) -> None:
        self._reader = reader or getpass

    def open(
        self,
        *,
        ttl_minutes: int,
        now: datetime | None = None,
        prompt: str = "Paste the session cookie/header locally (input hidden; never stored): ",
        allowed_age_ratings: frozenset[AgeRating] = frozenset(
            {"all_ages", "r18", "r18g"}
        ),
    ) -> RuntimeSession:
        """Create one runtime lease without environment, argument, or file fallback."""
        if not 1 <= ttl_minutes <= 60:
            raise ValueError("Runtime session TTL must be between 1 and 60 minutes.")
        created_at = now or datetime.now(UTC)
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError("Runtime session creation time must include a timezone.")
        if not prompt or len(prompt) > 200:
            raise ValueError("Runtime session prompt is invalid.")
        raw_value = self._reader(prompt)
        try:
            encoded = raw_value.encode("utf-8")
        finally:
            raw_value = ""
        if not encoded or len(encoded) > 8192 or b"\r" in encoded or b"\n" in encoded:
            temporary = bytearray(encoded)
            for index in range(len(temporary)):
                temporary[index] = 0
            raise RuntimeSessionError("Runtime session value is missing or invalid.")
        return RuntimeSession(
            bytearray(encoded),
            created_at.astimezone(UTC) + timedelta(minutes=ttl_minutes),
            established_at=created_at,
            allowed_age_ratings=allowed_age_ratings,
        )
