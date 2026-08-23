"""Permit-guarded authenticated transport restricted to numeric loopback hosts."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from pixiv_yuri.acquisition.auth import SessionCapability
from pixiv_yuri.acquisition.persistent_safety import PersistentAcquisitionSafety
from pixiv_yuri.acquisition.transport_contract import derive_transport_request_key

_SENSITIVE_HEADER_FRAGMENTS = ("authorization", "cookie", "secret", "token")
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1"})


class LoopbackTransportError(RuntimeError):
    """Raised without URL or secret details when local transport fails closed."""


@dataclass(frozen=True, slots=True)
class SanitizedTransportResponse:
    """Bounded response with authentication and cookie headers removed."""

    status_code: int
    content_type: str
    body: bytes
    headers: Mapping[str, str]


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(  # type: ignore[no-untyped-def]
        self, request, file_pointer, code, message, headers, new_url
    ):
        return None


class LoopbackSessionBroker:
    """Apply one runtime cookie to loopback requests without persisting it."""

    def __init__(
        self,
        capability: SessionCapability,
        cookie_supplier: Callable[[], str],
        *,
        max_body_bytes: int = 1_000_000,
    ) -> None:
        if max_body_bytes < 1:
            raise ValueError("Maximum body size must be positive.")
        self._capability = capability
        self._cookie_supplier = cookie_supplier
        self._max_body_bytes = max_body_bytes
        # A numeric-loopback-only broker must never inherit process or system proxies.
        self._opener = build_opener(ProxyHandler({}), _NoRedirectHandler())

    def fetch(
        self,
        url: str,
        *,
        timeout_seconds: float,
        now: datetime | None = None,
    ) -> SanitizedTransportResponse:
        """Fetch a numeric-loopback URL and return no credential-bearing headers."""
        checked_at = now or datetime.now(UTC)
        self._capability.ensure_active(checked_at)
        _validate_loopback_url(url)
        if not 0 < timeout_seconds <= 30:
            raise ValueError("Transport timeout must be between 0 and 30 seconds.")

        cookie = self._cookie_supplier()
        if not cookie or "\r" in cookie or "\n" in cookie:
            raise LoopbackTransportError("Runtime session value is missing or invalid.")
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "Cookie": cookie,
                "User-Agent": "pixiv-yuri-analytics-local-safety-probe/0.1",
            },
            method="GET",
        )
        try:
            with self._opener.open(request, timeout=timeout_seconds) as response:
                return self._read_response(
                    response.status,
                    dict(response.headers.items()),
                    response.read(self._max_body_bytes + 1),
                )
        except HTTPError as response:
            return self._read_response(
                response.code,
                dict(response.headers.items()),
                response.read(self._max_body_bytes + 1),
            )
        except (TimeoutError, URLError, OSError) as exc:
            raise LoopbackTransportError("Local transport failed.") from exc

    def validate_origin(self, origin: str) -> None:
        """Validate a loopback origin without obtaining a runtime credential."""
        _validate_loopback_url(origin)

    def _read_response(
        self, status_code: int, headers: Mapping[str, str], body: bytes
    ) -> SanitizedTransportResponse:
        if len(body) > self._max_body_bytes:
            raise LoopbackTransportError("Local response exceeded the approved size limit.")
        sanitized_headers = {
            key: value
            for key, value in headers.items()
            if not any(fragment in key.lower() for fragment in _SENSITIVE_HEADER_FRAGMENTS)
        }
        return SanitizedTransportResponse(
            status_code=status_code,
            content_type=sanitized_headers.get("Content-Type", "application/octet-stream"),
            body=body,
            headers=sanitized_headers,
        )


class PermitGuardedLoopbackTransport:
    """Require a committed persistent permit around every local transport call."""

    def __init__(
        self,
        safety: PersistentAcquisitionSafety,
        broker: LoopbackSessionBroker,
    ) -> None:
        self._safety = safety
        self._broker = broker

    @property
    def transport_kind(self) -> Literal["numeric_http_loopback"]:
        """Identify the only origin mode accepted by the loopback broker."""
        return "numeric_http_loopback"

    @property
    def external_network_enabled(self) -> bool:
        """Numeric loopback is never an external network source."""
        return False

    def validate_origin(self, origin: str) -> None:
        """Reject non-loopback origins during Provider construction."""
        self._broker.validate_origin(origin)

    def fetch(
        self,
        url: str,
        *,
        timeout_seconds: float,
        estimated_cost: Decimal = Decimal("0"),
        now: datetime | None = None,
    ) -> SanitizedTransportResponse:
        """Reserve, execute, then consume exactly one persistent permit."""
        checked_at = now or datetime.now(UTC)
        permit = self._safety.authorize_request(
            request_key=derive_transport_request_key(url, include_query=True),
            now=checked_at,
            estimated_cost=estimated_cost,
        )
        try:
            response = self._broker.fetch(
                url,
                timeout_seconds=timeout_seconds,
                now=checked_at,
            )
        except Exception:
            self._safety.record_transport_failure(permit.permit_id, now=checked_at)
            raise
        self._safety.record_response(
            permit.permit_id,
            response.status_code,
            now=checked_at,
        )
        return response

    def signal_schema_drift(self, *, now: datetime | None = None) -> None:
        """Expose the persistent Schema Drift kill switch to a parsing Provider."""
        self._safety.signal_schema_drift(now=now)


def _validate_loopback_url(url: str) -> None:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in _LOOPBACK_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise LoopbackTransportError("Only numeric HTTP loopback URLs are permitted.")
