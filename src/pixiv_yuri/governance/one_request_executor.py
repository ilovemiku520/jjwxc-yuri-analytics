"""Consume one confirmed capability around exactly one injected Provider fetch."""

from __future__ import annotations

import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, NoReturn

from pixiv_yuri.acquisition.base import AcquisitionProvider
from pixiv_yuri.acquisition.models import AcquisitionRequest, RawResponse
from pixiv_yuri.governance.first_request_gate import (
    MAX_CONFIRMATION_TTL_SECONDS,
    MIN_CONFIRMATION_TTL_SECONDS,
    ConfirmationResult,
    OneUseConfirmation,
)

_CAPABILITY_ISSUER = object()


class CapabilityUnavailableError(RuntimeError):
    """Report an unusable capability without exposing confirmation details."""


class ConfirmedOneRequestCapability:
    """A process-local, concurrency-safe capability that can be consumed once."""

    __slots__ = (
        "_consumed",
        "_expires_at",
        "_lock",
        "_provider",
        "_request_key",
    )

    def __init__(
        self,
        expires_at: datetime,
        provider: AcquisitionProvider,
        request: AcquisitionRequest,
        *,
        _issuer: object,
    ) -> None:
        if _issuer is not _CAPABILITY_ISSUER:
            raise CapabilityUnavailableError("Capability must come from a confirmed gate.")
        _validate_aware(expires_at, "Capability expiry")
        self._expires_at = expires_at.astimezone(UTC)
        self._provider = provider
        self._request_key = request.key
        self._consumed = False
        self._lock = threading.Lock()

    @property
    def consumed(self) -> bool:
        """Return a safe use-state snapshot."""
        with self._lock:
            return self._consumed

    @property
    def expires_at(self) -> datetime:
        """Return the non-secret expiry inherited from operator confirmation."""
        return self._expires_at

    def consume(self, *, now: datetime | None = None) -> None:
        """Burn the capability atomically before validating its expiry."""
        checked_at = now or datetime.now(UTC)
        with self._lock:
            if self._consumed:
                raise CapabilityUnavailableError("Capability was already consumed.")
            self._consumed = True
        _validate_aware(checked_at, "Capability consumption time")
        if checked_at.astimezone(UTC) >= self._expires_at:
            raise CapabilityUnavailableError("Capability is no longer active.")

    def matches(self, provider: AcquisitionProvider, request: AcquisitionRequest) -> bool:
        """Match only the exact injected Provider instance and logical request key."""
        return provider is self._provider and request.key == self._request_key

    def __reduce__(self) -> NoReturn:
        """Prevent a capability from being serialized or copied across processes."""
        raise TypeError("One-request capabilities cannot be serialized.")


@dataclass(frozen=True, slots=True)
class OneRequestExecutionResult:
    """A payload-free execution summary safe for logs and reports."""

    status: str
    planned_requests: int
    attempted_requests: int
    completed_requests: int
    capability_consumed: bool
    entity_type: str | None
    response_status_code: int | None
    external_network_used: bool
    violations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LiveOneRequestConfirmationResult:
    """Safe evidence for an explicit live-network confirmation attempt."""

    status: str
    mode: Literal["live_one_request"]
    planned_requests: int
    expires_at: datetime | None
    confirmed_at: datetime | None
    challenge_consumed: bool
    external_network_used: bool
    violations: tuple[str, ...]


def confirm_live_one_request_capability(
    provider: AcquisitionProvider,
    requests: tuple[AcquisitionRequest, ...],
    *,
    ttl_seconds: int,
    reader: Callable[[str], str],
    phrase_factory: Callable[[], str] | None = None,
    now: Callable[[], datetime] | None = None,
) -> tuple[LiveOneRequestConfirmationResult, ConfirmedOneRequestCapability | None]:
    """Explicitly confirm one live request and mint the existing opaque capability."""
    planned_requests = len(requests)
    if planned_requests != 1:
        return _blocked_live_confirmation(
            planned_requests, "planned_requests_must_equal_one"
        ), None
    if not MIN_CONFIRMATION_TTL_SECONDS <= ttl_seconds <= MAX_CONFIRMATION_TTL_SECONDS:
        return _blocked_live_confirmation(1, "confirmation_ttl_out_of_range"), None

    clock = now or (lambda: datetime.now(UTC))
    issued_at = clock()
    _validate_aware(issued_at, "Live confirmation issue time")
    phrase = (phrase_factory or _new_live_phrase)()
    challenge = OneUseConfirmation(
        phrase,
        issued_at=issued_at,
        ttl_seconds=ttl_seconds,
    )
    try:
        candidate = reader(
            "LIVE REQUEST: this will contact the reviewed source exactly once. "
            f"Type this one-use phrase to continue: {phrase}\nConfirmation: "
        )
    except (EOFError, KeyboardInterrupt):
        candidate = ""
    finally:
        phrase = ""

    confirmed_at = clock()
    _validate_aware(confirmed_at, "Live confirmation time")
    accepted = challenge.confirm(candidate, now=confirmed_at)
    candidate = ""
    if not accepted:
        return (
            LiveOneRequestConfirmationResult(
                status="blocked",
                mode="live_one_request",
                planned_requests=1,
                expires_at=challenge.expires_at,
                confirmed_at=None,
                challenge_consumed=challenge.consumed,
                external_network_used=False,
                violations=("operator_live_confirmation_missing_or_invalid",),
            ),
            None,
        )
    return (
        LiveOneRequestConfirmationResult(
            status="passed",
            mode="live_one_request",
            planned_requests=1,
            expires_at=challenge.expires_at,
            confirmed_at=confirmed_at.astimezone(UTC),
            challenge_consumed=True,
            external_network_used=False,
            violations=(),
        ),
        ConfirmedOneRequestCapability(
            challenge.expires_at,
            provider,
            requests[0],
            _issuer=_CAPABILITY_ISSUER,
        ),
    )


def confirm_one_request_capability(
    provider: AcquisitionProvider,
    requests: tuple[AcquisitionRequest, ...],
    *,
    ttl_seconds: int,
    reader: Callable[[str], str],
    phrase_factory: Callable[[], str] | None = None,
    now: Callable[[], datetime] | None = None,
) -> tuple[ConfirmationResult, ConfirmedOneRequestCapability | None]:
    """Confirm and mint an opaque bound capability in the same call stack."""
    from pixiv_yuri.governance.first_request_gate import run_confirmation_gate

    clock = now or (lambda: datetime.now(UTC))
    confirmation = run_confirmation_gate(
        planned_requests=len(requests),
        ttl_seconds=ttl_seconds,
        reader=reader,
        phrase_factory=phrase_factory,
        now=clock,
    )
    if confirmation.status != "passed" or len(requests) != 1:
        return confirmation, None
    if confirmation.expires_at is None:
        raise CapabilityUnavailableError("Operator confirmation is not eligible.")
    try:
        expires_at = datetime.fromisoformat(confirmation.expires_at)
        _validate_aware(expires_at, "Operator confirmation expiry")
    except ValueError:
        raise CapabilityUnavailableError("Operator confirmation is not eligible.") from None
    return (
        confirmation,
        ConfirmedOneRequestCapability(
            expires_at,
            provider,
            requests[0],
            _issuer=_CAPABILITY_ISSUER,
        ),
    )


def execute_exactly_one_provider_request(
    capability: ConfirmedOneRequestCapability,
    provider: AcquisitionProvider,
    requests: tuple[AcquisitionRequest, ...],
    *,
    now: datetime | None = None,
    external_network_used: bool = False,
) -> OneRequestExecutionResult:
    """Burn the capability, then call the injected Provider's ``fetch`` exactly once."""
    planned_requests = len(requests)
    try:
        capability.consume(now=now)
    except (CapabilityUnavailableError, ValueError):
        return _blocked(
            planned_requests,
            capability.consumed,
            "capability_unavailable",
            external_network_used=False,
        )
    if planned_requests != 1:
        return _blocked(
            planned_requests,
            True,
            "planned_requests_must_equal_one",
            external_network_used=False,
        )
    if external_network_used or provider.external_network_enabled:
        return _blocked(
            planned_requests,
            True,
            "network_execution_not_enabled",
            external_network_used=False,
        )

    request = requests[0]
    if not capability.matches(provider, request):
        return _blocked(
            planned_requests,
            True,
            "capability_binding_mismatch",
            external_network_used=False,
        )
    try:
        response = provider.fetch(request)
    except Exception:  # Provider failures cross this boundary only as a safe code.
        return _blocked(
            planned_requests,
            True,
            "provider_request_failed",
            attempted_requests=1,
            external_network_used=False,
        )
    if not _response_matches_request(response, request):
        return _blocked(
            planned_requests,
            True,
            "provider_response_identity_mismatch",
            attempted_requests=1,
            external_network_used=False,
        )
    if response.status_code < 200 or response.status_code >= 300:
        return _blocked(
            planned_requests,
            True,
            "provider_non_success_response",
            attempted_requests=1,
            external_network_used=False,
        )
    return OneRequestExecutionResult(
        status="passed",
        planned_requests=1,
        attempted_requests=1,
        completed_requests=1,
        capability_consumed=True,
        entity_type=request.entity_type.value,
        response_status_code=response.status_code,
        external_network_used=False,
        violations=(),
    )


def confirm_and_execute_exactly_one(
    provider: AcquisitionProvider,
    requests: tuple[AcquisitionRequest, ...],
    *,
    ttl_seconds: int,
    reader: Callable[[str], str],
    phrase_factory: Callable[[], str] | None = None,
    now: Callable[[], datetime] | None = None,
) -> OneRequestExecutionResult:
    """Confirm and execute without accepting a serializable authorization result."""
    clock = now or (lambda: datetime.now(UTC))
    _confirmation, capability = confirm_one_request_capability(
        provider,
        requests,
        ttl_seconds=ttl_seconds,
        reader=reader,
        phrase_factory=phrase_factory,
        now=clock,
    )
    if capability is None:
        return _blocked(len(requests), False, "confirmation_not_eligible")
    return execute_exactly_one_provider_request(
        capability,
        provider,
        requests,
        now=clock(),
    )


def _response_matches_request(response: RawResponse, request: AcquisitionRequest) -> bool:
    return (
        response.entity_type == request.entity_type
        and response.source_id == request.source_id
    )


def _blocked(
    planned_requests: int,
    capability_consumed: bool,
    violation: str,
    *,
    attempted_requests: int = 0,
    external_network_used: bool = False,
) -> OneRequestExecutionResult:
    return OneRequestExecutionResult(
        status="blocked",
        planned_requests=planned_requests,
        attempted_requests=attempted_requests,
        completed_requests=0,
        capability_consumed=capability_consumed,
        entity_type=None,
        response_status_code=None,
        external_network_used=external_network_used,
        violations=(violation,),
    )


def _blocked_live_confirmation(
    planned_requests: int, violation: str
) -> LiveOneRequestConfirmationResult:
    return LiveOneRequestConfirmationResult(
        status="blocked",
        mode="live_one_request",
        planned_requests=planned_requests,
        expires_at=None,
        confirmed_at=None,
        challenge_consumed=False,
        external_network_used=False,
        violations=(violation,),
    )


def _new_live_phrase() -> str:
    return f"CONFIRM-LIVE-ONE-{secrets.token_hex(6).upper()}"


def _validate_aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must include a timezone.")
