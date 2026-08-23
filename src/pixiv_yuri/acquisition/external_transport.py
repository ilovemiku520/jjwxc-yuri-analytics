"""Permit-guarded HTTPS transport with exact host pins and runtime credentials."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal, Protocol, cast
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, OpenerDirector, Request, build_opener

from pixiv_yuri.acquisition.auth import SessionCapability
from pixiv_yuri.acquisition.operator_session import RuntimeSession
from pixiv_yuri.acquisition.persistent_safety import PersistentAcquisitionSafety
from pixiv_yuri.acquisition.runtime_session_lease import (
    RuntimeSessionLease,
    require_same_runtime_session_lease,
)
from pixiv_yuri.acquisition.transport_contract import (
    derive_transport_request_key,
    normalize_exact_dns_host,
)

_SENSITIVE_HEADER_FRAGMENTS = (
    "authenticate",
    "authorization",
    "cookie",
    "secret",
    "token",
)
_SENSITIVE_HEADER_NAMES = frozenset({"location", "refresh"})
_MAX_TIMEOUT_SECONDS = 30.0


class ExternalTransportError(RuntimeError):
    """Fail-closed transport error whose message never includes URL or credentials."""


class _ResponsePolicyError(RuntimeError):
    """Private marker for response-policy messages authored in this module."""


@dataclass(frozen=True, slots=True)
class SanitizedExternalResponse:
    """Bounded response with credential-bearing and redirect headers removed."""

    status_code: int
    content_type: str
    body: bytes
    headers: Mapping[str, str]


class _HeaderCollection(Protocol):
    def items(self) -> list[tuple[str, str]]: ...


class _ResponseStream(Protocol):
    @property
    def status(self) -> int: ...

    @property
    def headers(self) -> _HeaderCollection: ...

    def read(self, amount: int = -1) -> bytes: ...

    def close(self) -> None: ...

    def __enter__(self) -> _ResponseStream: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object,
    ) -> None: ...


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(  # type: ignore[no-untyped-def]
        self, request, file_pointer, code, message, headers, new_url
    ):
        return None


class ExternalSessionBroker:
    """Make one host-pinned request using an ephemeral credential supplier."""

    def __init__(
        self,
        capability: SessionCapability,
        credential_supplier: Callable[[], str],
        *,
        allowed_hosts: frozenset[str],
        credential_header: Literal["Cookie", "Authorization"] = "Cookie",
        max_body_bytes: int = 1_000_000,
        open_request: Callable[[Request, float], _ResponseStream] | None = None,
    ) -> None:
        if max_body_bytes < 1:
            raise ValueError("Maximum body size must be positive.")
        if not allowed_hosts:
            raise ValueError("At least one exact HTTPS host pin is required.")
        self._allowed_hosts = frozenset(
            normalize_exact_dns_host(host) for host in allowed_hosts
        )
        self._capability = capability
        self._credential_supplier = credential_supplier
        self._runtime_session_lease = (
            credential_supplier.runtime_session_lease
            if isinstance(credential_supplier, RuntimeSession)
            else None
        )
        self._credential_header = credential_header
        self._max_body_bytes = max_body_bytes
        self._opener: OpenerDirector | None = None
        self._open_request: Callable[[Request, float], _ResponseStream]
        if open_request is None:
            self._opener = build_opener(_NoRedirectHandler())
            self._open_request = self._default_open
        else:
            self._open_request = open_request

    @property
    def external_network_enabled(self) -> bool:
        """Only the default opener can reach the host network."""
        return self._opener is not None

    @property
    def runtime_session_lease(self) -> RuntimeSessionLease | None:
        """Return the exact lease owned by a RuntimeSession supplier, if present."""
        return self._runtime_session_lease

    def fetch(
        self,
        url: str,
        *,
        timeout_seconds: float,
        now: datetime | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> SanitizedExternalResponse:
        """Fetch one approved HTTPS URL without retaining a runtime credential.

        ``clock`` is called independently for the session and immediately-before-send
        checks. ``now`` remains only as a deterministic compatibility hook for older
        offline tests; callers must not pass both.
        """
        phase_clock = _select_phase_clock(now=now, clock=clock)
        failure: ExternalTransportError | None
        try:
            session_checked_at = _read_phase_time(phase_clock)
            self._capability.ensure_active(session_checked_at)
            _validate_external_url(url, self._allowed_hosts)
            if not 0 < timeout_seconds <= _MAX_TIMEOUT_SECONDS:
                raise ValueError("Transport timeout must be between 0 and 30 seconds.")
        except ExternalTransportError as caught:
            failure = ExternalTransportError(str(caught))
        except Exception:
            failure = ExternalTransportError("External HTTPS session is unavailable.")
        else:
            failure = None
        if failure is not None:
            raise failure from None

        try:
            if isinstance(self._credential_supplier, RuntimeSession):
                assert self._runtime_session_lease is not None
                require_same_runtime_session_lease(
                    self._runtime_session_lease,
                    self._credential_supplier.runtime_session_lease,
                )
                credential = self._credential_supplier.reveal_for_request(
                    now=session_checked_at,
                    required_visibility=self._capability.content_visibility,
                    required_age_ratings=self._capability.allowed_age_ratings,
                )
            else:
                credential = self._credential_supplier()
        except Exception:
            credential = ""
            failure = ExternalTransportError("Runtime credential is unavailable.")
        else:
            failure = None
        if failure is not None:
            raise failure from None
        try:
            credential_is_valid = (
                isinstance(credential, str)
                and bool(credential)
                and len(credential.encode("utf-8")) <= 8192
                and "\r" not in credential
                and "\n" not in credential
            )
        except UnicodeError:
            credential_is_valid = False
        if not credential_is_valid:
            credential = ""
            raise ExternalTransportError("Runtime credential is missing or invalid.") from None

        try:
            request = Request(
                url,
                headers={
                    "Accept": "application/json",
                    self._credential_header: credential,
                    "User-Agent": "pixiv-yuri-analytics-approved-metadata/0.1",
                },
                method="GET",
            )
            send_checked_at = _read_phase_time(phase_clock)
            self._capability.ensure_active(send_checked_at)
        except Exception:
            credential = ""
            failure = ExternalTransportError("External HTTPS send was not permitted.")
        else:
            failure = None
        if failure is not None:
            raise failure from None
        credential = ""

        response: _ResponseStream | None = None
        try:
            response = self._open_request(request, timeout_seconds)
            status_code = response.status
        except HTTPError as caught:
            response = cast(_ResponseStream, caught)
            status_code = caught.code
        except Exception:
            failure = ExternalTransportError("External HTTPS transport failed.")
        else:
            failure = None
        if failure is not None:
            raise failure from None
        assert response is not None
        sanitized, read_failure = self._consume_response(response, status_code)
        if read_failure is not None:
            raise read_failure from None
        assert sanitized is not None
        return sanitized

    def validate_origin(self, origin: str) -> None:
        """Validate an exact allowlisted HTTPS origin without reading credentials."""
        _validate_external_url(origin, self._allowed_hosts)

    def _default_open(self, request: Request, timeout_seconds: float) -> _ResponseStream:
        assert self._opener is not None
        return cast(_ResponseStream, self._opener.open(request, timeout=timeout_seconds))

    def _read_response(
        self,
        status_code: int,
        header_items: list[tuple[str, str]],
        body: bytes,
    ) -> SanitizedExternalResponse:
        if not 100 <= status_code <= 599:
            raise _ResponsePolicyError("External response status is invalid.")
        if len(body) > self._max_body_bytes:
            raise _ResponsePolicyError(
                "External response exceeded the approved size limit."
            )
        sanitized_headers = {
            key: value
            for key, value in header_items
            if not _is_sensitive_response_header(key)
        }
        content_type = next(
            (
                value
                for key, value in sanitized_headers.items()
                if key.lower() == "content-type"
            ),
            "application/octet-stream",
        )
        return SanitizedExternalResponse(
            status_code=status_code,
            content_type=content_type,
            body=body,
            headers=sanitized_headers,
        )

    def _consume_response(
        self,
        response: _ResponseStream,
        status_code: int,
    ) -> tuple[SanitizedExternalResponse | None, ExternalTransportError | None]:
        """Read and close a response without retaining a sensitive exception context."""
        sanitized: SanitizedExternalResponse | None = None
        failure: ExternalTransportError | None = None
        try:
            sanitized = self._read_response(
                status_code,
                response.headers.items(),
                response.read(self._max_body_bytes + 1),
            )
        except _ResponsePolicyError as caught:
            failure = ExternalTransportError(str(caught))
        except Exception:
            failure = ExternalTransportError("External HTTPS response could not be read.")
        try:
            response.close()
        except Exception:
            sanitized = None
            failure = ExternalTransportError("External HTTPS response could not be closed.")
        return sanitized, failure

    def __repr__(self) -> str:
        return (
            "ExternalSessionBroker("
            f"allowed_hosts={sorted(self._allowed_hosts)!r}, "
            f"credential_header={self._credential_header!r}, "
            "credential=[REDACTED])"
        )


class PermitGuardedExternalTransport:
    """Reserve and consume one persistent permit around every external call."""

    def __init__(
        self,
        safety: PersistentAcquisitionSafety,
        broker: ExternalSessionBroker,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._safety = safety
        self._broker = broker
        self._clock = clock or (lambda: datetime.now(UTC))

    @property
    def transport_kind(self) -> Literal["exact_https_dns"]:
        """Identify the only origin mode accepted by the external broker."""
        return "exact_https_dns"

    @property
    def external_network_enabled(self) -> bool:
        """Expose whether the broker owns a real network opener."""
        return self._broker.external_network_enabled

    @property
    def runtime_session_lease(self) -> RuntimeSessionLease | None:
        """Expose only the broker's non-secret opaque lease identity."""
        return self._broker.runtime_session_lease

    def validate_origin(self, origin: str) -> None:
        """Reject origins outside the broker's exact host pins at construction time."""
        self._broker.validate_origin(origin)

    def fetch(
        self,
        url: str,
        *,
        timeout_seconds: float,
        estimated_cost: Decimal = Decimal("0"),
        now: datetime | None = None,
    ) -> SanitizedExternalResponse:
        """Authorize first, execute once, and consume the permit even on failure."""
        phase_clock = _select_phase_clock(
            now=now,
            clock=None if now is not None else self._clock,
        )
        failure: ExternalTransportError | None
        try:
            authorized_at = _read_phase_time(phase_clock)
        except Exception:
            failure = ExternalTransportError(
                "External HTTPS authorization time is unavailable."
            )
        else:
            failure = None
        if failure is not None:
            raise failure from None
        permit = self._safety.authorize_request(
            request_key=derive_transport_request_key(url),
            now=authorized_at,
            estimated_cost=estimated_cost,
        )
        try:
            response = self._broker.fetch(
                url,
                timeout_seconds=timeout_seconds,
                clock=phase_clock,
            )
        except Exception as caught:
            failure = _sanitize_transport_failure(caught)
        else:
            failure = None
        if failure is not None:
            settlement_failure = self._settle_transport_failure(
                permit.permit_id,
                phase_clock,
            )
            if settlement_failure is not None:
                raise settlement_failure from None
            raise failure from None
        settlement_failure = self._settle_response(
            permit.permit_id,
            response.status_code,
            phase_clock,
        )
        if settlement_failure is not None:
            raise settlement_failure from None
        return response

    def _settle_transport_failure(
        self,
        permit_id: str,
        phase_clock: Callable[[], datetime],
    ) -> ExternalTransportError | None:
        try:
            settled_at = _read_phase_time(phase_clock)
            self._safety.record_transport_failure(permit_id, now=settled_at)
        except Exception:
            return ExternalTransportError("External HTTPS permit settlement failed.")
        return None

    def _settle_response(
        self,
        permit_id: str,
        status_code: int,
        phase_clock: Callable[[], datetime],
    ) -> ExternalTransportError | None:
        try:
            settled_at = _read_phase_time(phase_clock)
            self._safety.record_response(permit_id, status_code, now=settled_at)
        except Exception:
            return ExternalTransportError("External HTTPS permit settlement failed.")
        return None

    def signal_schema_drift(self, *, now: datetime | None = None) -> None:
        """Expose the persistent Schema Drift kill switch to a parsing Provider."""
        self._safety.signal_schema_drift(now=now)

    def __repr__(self) -> str:
        return "PermitGuardedExternalTransport(safety=[BOUND], broker=[REDACTED])"


def _validate_external_url(url: str, allowed_hosts: frozenset[str]) -> None:
    if (
        not isinstance(url, str)
        or not url
        or any(character in url for character in ("\r", "\n", "\t"))
    ):
        raise ExternalTransportError("External URL is not permitted.")
    try:
        parsed = urlsplit(url)
        port = parsed.port
        host = normalize_exact_dns_host(parsed.hostname or "")
    except (UnicodeError, ValueError):
        raise ExternalTransportError("External URL is not permitted.") from None
    if (
        parsed.scheme != "https"
        or host not in allowed_hosts
        or port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
        or bool(parsed.query)
        or bool(parsed.fragment)
    ):
        raise ExternalTransportError("External URL is not permitted.")

def _is_sensitive_response_header(name: str) -> bool:
    lowered = name.lower()
    return lowered in _SENSITIVE_HEADER_NAMES or any(
        fragment in lowered for fragment in _SENSITIVE_HEADER_FRAGMENTS
    )


def _select_phase_clock(
    *,
    now: datetime | None,
    clock: Callable[[], datetime] | None,
) -> Callable[[], datetime]:
    if now is not None and clock is not None:
        raise ValueError("Pass either now or clock, not both.")
    if now is not None:
        return lambda: now
    return clock or (lambda: datetime.now(UTC))


def _read_phase_time(clock: Callable[[], datetime]) -> datetime:
    value = clock()
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Transport phase time must include a timezone.")
    return value.astimezone(UTC)


def _sanitize_transport_failure(caught: Exception) -> ExternalTransportError:
    if isinstance(caught, ExternalTransportError):
        return ExternalTransportError(str(caught))
    return ExternalTransportError("External HTTPS transport failed.")
