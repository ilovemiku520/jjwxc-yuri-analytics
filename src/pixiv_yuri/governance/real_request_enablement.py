"""Offline-only explicit enablement state for exactly one real request."""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from threading import Lock
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator

MAX_ENABLEMENT_TTL = timedelta(seconds=120)
EXPLICIT_ACKNOWLEDGEMENT: Literal[
    "ENABLE_EXACTLY_ONE_REAL_REQUEST"
] = "ENABLE_EXACTLY_ONE_REAL_REQUEST"


class RealRequestEnablementConfig(BaseModel):
    """Non-secret, expiring configuration whose default is an inert denial."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    mode: Literal["disabled", "first_real_request"] = "disabled"
    planned_requests: Literal[1] = 1
    approval_fingerprint: str | None = None
    run_id: int | None = None
    request_key_hash: str | None = None
    enabled_at: datetime | None = None
    expires_at: datetime | None = None
    acknowledgement: Literal["ENABLE_EXACTLY_ONE_REAL_REQUEST"] | None = None

    @model_validator(mode="after")
    def validate_fail_closed_configuration(self) -> Self:
        bindings = (
            self.approval_fingerprint,
            self.run_id,
            self.request_key_hash,
            self.enabled_at,
            self.expires_at,
            self.acknowledgement,
        )
        if self.mode == "disabled":
            if any(value is not None for value in bindings):
                raise ValueError("Disabled enablement cannot carry an armed binding.")
            return self

        if any(value is None for value in bindings):
            raise ValueError("Real-request enablement requires a complete binding.")
        assert self.approval_fingerprint is not None
        assert self.request_key_hash is not None
        assert self.run_id is not None
        assert self.enabled_at is not None
        assert self.expires_at is not None
        _validate_sha256(self.approval_fingerprint, "Approval fingerprint")
        _validate_sha256(self.request_key_hash, "Request key hash")
        if self.run_id < 1:
            raise ValueError("Run identifier must be positive.")
        enabled_at = _aware_utc(self.enabled_at)
        expires_at = _aware_utc(self.expires_at)
        if not enabled_at < expires_at <= enabled_at + MAX_ENABLEMENT_TTL:
            raise ValueError("Real-request enablement must expire within 120 seconds.")
        return self


class RealRequestEnablementState(StrEnum):
    """One-way runtime states; no state can transition back to armed."""

    DISABLED = "disabled"
    ARMED = "armed"
    CONSUMED = "consumed"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class RealRequestDeniedReason(StrEnum):
    """Safe denial reasons that disclose no request identity."""

    NOT_ARMED = "not_armed"
    NOT_ACTIVE_YET = "not_active_yet"
    EXPIRED = "expired"
    BINDING_MISMATCH = "binding_mismatch"
    ALREADY_TERMINAL = "already_terminal"


class RealRequestDeniedError(RuntimeError):
    """Fail-closed denial raised before any caller may initiate transport."""

    def __init__(self, reason: RealRequestDeniedReason) -> None:
        self.reason = reason
        super().__init__(f"Real request denied: {reason.value}")


@dataclass(frozen=True, slots=True)
class EnablementConsumptionReceipt:
    """Safe audit evidence; this receipt is not an authorization capability."""

    state: Literal["consumed"]
    planned_requests: Literal[1]
    consumed_at: datetime


@dataclass(frozen=True, slots=True)
class RealRequestEnablementSnapshot:
    """Non-secret state suitable for reports and tests."""

    state: RealRequestEnablementState
    planned_requests: Literal[1]
    expires_at: datetime | None


class ExplicitRealRequestEnablement:
    """Atomically burn one explicit policy latch before a real request.

    This class performs no I/O and is not an authorization capability: its
    serializable configuration can be reconstructed. Its consumption receipt
    is evidence only. Real authorization remains the responsibility of the
    same-stack opaque confirmation capability and the persistent unique slot.
    """

    def __init__(self, config: RealRequestEnablementConfig | None = None) -> None:
        self._config = config or RealRequestEnablementConfig()
        self._state = (
            RealRequestEnablementState.DISABLED
            if self._config.mode == "disabled"
            else RealRequestEnablementState.ARMED
        )
        self._lock = Lock()

    def snapshot(self, *, now: datetime | None = None) -> RealRequestEnablementSnapshot:
        """Return safe state, applying expiry without consuming an armed request."""
        checked_at = _aware_utc(now or datetime.now(UTC))
        with self._lock:
            self._expire_if_needed(checked_at)
            return RealRequestEnablementSnapshot(
                state=self._state,
                planned_requests=1,
                expires_at=self._config.expires_at,
            )

    def consume(
        self,
        *,
        approval_fingerprint: str,
        run_id: int,
        request_key_hash: str,
        now: datetime | None = None,
    ) -> EnablementConsumptionReceipt:
        """Consume once after exact binding checks; a mismatch burns the state."""
        checked_at = _aware_utc(now or datetime.now(UTC))
        with self._lock:
            self._expire_if_needed(checked_at)
            if self._state == RealRequestEnablementState.DISABLED:
                raise RealRequestDeniedError(RealRequestDeniedReason.NOT_ARMED)
            if self._state == RealRequestEnablementState.EXPIRED:
                raise RealRequestDeniedError(RealRequestDeniedReason.EXPIRED)
            if self._state != RealRequestEnablementState.ARMED:
                raise RealRequestDeniedError(RealRequestDeniedReason.ALREADY_TERMINAL)

            enabled_at = self._config.enabled_at
            assert enabled_at is not None
            if checked_at < _aware_utc(enabled_at):
                self._state = RealRequestEnablementState.REJECTED
                raise RealRequestDeniedError(RealRequestDeniedReason.NOT_ACTIVE_YET)

            if not self._binding_matches(
                approval_fingerprint, run_id, request_key_hash
            ):
                self._state = RealRequestEnablementState.REJECTED
                raise RealRequestDeniedError(RealRequestDeniedReason.BINDING_MISMATCH)

            self._state = RealRequestEnablementState.CONSUMED
            return EnablementConsumptionReceipt(
                state="consumed",
                planned_requests=1,
                consumed_at=checked_at,
            )

    def cancel(self, *, now: datetime | None = None) -> None:
        """Burn an armed configuration without authorizing a request."""
        checked_at = _aware_utc(now or datetime.now(UTC))
        with self._lock:
            self._expire_if_needed(checked_at)
            if self._state != RealRequestEnablementState.ARMED:
                reason = (
                    RealRequestDeniedReason.EXPIRED
                    if self._state == RealRequestEnablementState.EXPIRED
                    else RealRequestDeniedReason.NOT_ARMED
                    if self._state == RealRequestEnablementState.DISABLED
                    else RealRequestDeniedReason.ALREADY_TERMINAL
                )
                raise RealRequestDeniedError(reason)
            self._state = RealRequestEnablementState.CANCELLED

    def _binding_matches(
        self, approval_fingerprint: str, run_id: int, request_key_hash: str
    ) -> bool:
        expected_fingerprint = self._config.approval_fingerprint
        expected_request_hash = self._config.request_key_hash
        expected_run_id = self._config.run_id
        assert expected_fingerprint is not None
        assert expected_request_hash is not None
        assert expected_run_id is not None
        if (
            not isinstance(approval_fingerprint, str)
            or isinstance(run_id, bool)
            or not isinstance(run_id, int)
            or not isinstance(request_key_hash, str)
        ):
            return False
        if not _is_lower_sha256(approval_fingerprint) or not _is_lower_sha256(
            request_key_hash
        ):
            return False
        return (
            hmac.compare_digest(expected_fingerprint, approval_fingerprint)
            and expected_run_id == run_id
            and hmac.compare_digest(expected_request_hash, request_key_hash)
        )

    def _expire_if_needed(self, checked_at: datetime) -> None:
        expires_at = self._config.expires_at
        if (
            self._state == RealRequestEnablementState.ARMED
            and expires_at is not None
            and checked_at >= _aware_utc(expires_at)
        ):
            self._state = RealRequestEnablementState.EXPIRED


def _validate_sha256(value: str, label: str) -> None:
    if len(value) != 64:
        raise ValueError(f"{label} must be a 64-character SHA-256 value.")
    try:
        bytes.fromhex(value)
    except ValueError:
        raise ValueError(f"{label} must be hexadecimal.") from None
    if value != value.lower():
        raise ValueError(f"{label} must use lowercase hexadecimal.")


def _is_lower_sha256(value: str) -> bool:
    if len(value) != 64 or not value.isascii() or value != value.lower():
        return False
    try:
        bytes.fromhex(value)
    except ValueError:
        return False
    return True


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Real-request enablement timestamps must include a timezone.")
    return value.astimezone(UTC)
