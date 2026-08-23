"""Provider-neutral consumer authorization boundary for read APIs."""

from __future__ import annotations

import hashlib
import hmac
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from fastapi import Request

ANALYTICS_READ_SCOPE = "analytics:read"
_PROXY_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_SUBJECT_PATTERN = re.compile(r"^[A-Za-z0-9._:@/-]{1,255}$")
_SCOPE_PATTERN = re.compile(r"^[A-Za-z0-9:._-]{1,100}$")
_TIMESTAMP_PATTERN = re.compile(r"^[0-9]{1,12}$")
_SIGNATURE_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_ASSERTION_HEADERS = {
    "proxy_id": "X-Pyuri-Proxy-ID",
    "subject": "X-Pyuri-Subject",
    "scopes": "X-Pyuri-Scopes",
    "issued_at": "X-Pyuri-Issued-At",
    "signature": "X-Pyuri-Signature",
}
EpochClock = Callable[[], float]


@dataclass(frozen=True, slots=True)
class ConsumerIdentity:
    """Verified external identity reduced to a subject and immutable scopes."""

    subject: str
    scopes: frozenset[str]

    def __post_init__(self) -> None:
        if not self.subject or len(self.subject) > 255:
            raise ValueError("consumer subject must be 1-255 characters")
        if any(not scope or len(scope) > 100 for scope in self.scopes):
            raise ValueError("consumer scopes must be 1-100 characters")


class ConsumerAuthenticationError(RuntimeError):
    """Known authentication failure safe to reduce to a fixed response code."""


class ConsumerAuthorizer(Protocol):
    """Adapter implemented by a future reviewed OIDC or trusted-proxy integration."""

    def authorize(self, request: Request) -> ConsumerIdentity:
        """Authenticate one request without returning or persisting bearer material."""
        ...


class TrustedHmacProxyAuthorizer:
    """Verify a short-lived assertion issued by one pinned identity-aware proxy."""

    def __init__(
        self,
        *,
        proxy_id: str,
        secret: bytes,
        maximum_age_seconds: int = 30,
        clock: EpochClock = time.time,
    ) -> None:
        if _PROXY_ID_PATTERN.fullmatch(proxy_id) is None:
            raise ValueError("trusted proxy ID is invalid")
        if len(secret) < 32:
            raise ValueError("trusted proxy HMAC secret must contain at least 32 bytes")
        if maximum_age_seconds < 1 or maximum_age_seconds > 300:
            raise ValueError("trusted proxy maximum age must be between 1 and 300 seconds")
        self._proxy_id = proxy_id
        self._secret = secret
        self._maximum_age_seconds = maximum_age_seconds
        self._clock = clock

    def authorize(self, request: Request) -> ConsumerIdentity:
        assertion = _single_assertion_headers(request)
        if assertion["proxy_id"] != self._proxy_id:
            raise ConsumerAuthenticationError
        subject = assertion["subject"]
        if _SUBJECT_PATTERN.fullmatch(subject) is None:
            raise ConsumerAuthenticationError
        scopes = _parse_scopes(assertion["scopes"])
        issued_at_text = assertion["issued_at"]
        if _TIMESTAMP_PATTERN.fullmatch(issued_at_text) is None:
            raise ConsumerAuthenticationError
        issued_at = int(issued_at_text)
        age = self._clock() - issued_at
        if age < -5 or age > self._maximum_age_seconds:
            raise ConsumerAuthenticationError
        signature = assertion["signature"]
        if _SIGNATURE_PATTERN.fullmatch(signature) is None:
            raise ConsumerAuthenticationError
        expected = build_trusted_proxy_signature(
            secret=self._secret,
            proxy_id=self._proxy_id,
            method=request.method,
            path=request.url.path,
            subject=subject,
            scopes=scopes,
            issued_at=issued_at,
        )
        if not hmac.compare_digest(signature, expected):
            raise ConsumerAuthenticationError
        return ConsumerIdentity(subject=subject, scopes=scopes)


def build_trusted_proxy_signature(
    *,
    secret: bytes,
    proxy_id: str,
    method: str,
    path: str,
    subject: str,
    scopes: frozenset[str],
    issued_at: int,
) -> str:
    """Build the versioned assertion MAC used by a reviewed trusted proxy."""
    canonical = "\n".join(
        (
            "pyuri-trusted-proxy-v1",
            proxy_id,
            method.upper(),
            path,
            subject,
            " ".join(sorted(scopes)),
            str(issued_at),
        )
    ).encode("utf-8")
    return hmac.new(secret, canonical, hashlib.sha256).hexdigest()


def trusted_proxy_headers(
    *,
    secret: bytes,
    proxy_id: str,
    method: str,
    path: str,
    subject: str,
    scopes: frozenset[str],
    issued_at: int,
) -> Mapping[str, str]:
    """Return a complete assertion for proxy integration tests and adapters."""
    scope_text = " ".join(sorted(scopes))
    signature = build_trusted_proxy_signature(
        secret=secret,
        proxy_id=proxy_id,
        method=method,
        path=path,
        subject=subject,
        scopes=scopes,
        issued_at=issued_at,
    )
    return {
        _ASSERTION_HEADERS["proxy_id"]: proxy_id,
        _ASSERTION_HEADERS["subject"]: subject,
        _ASSERTION_HEADERS["scopes"]: scope_text,
        _ASSERTION_HEADERS["issued_at"]: str(issued_at),
        _ASSERTION_HEADERS["signature"]: signature,
    }


def _single_assertion_headers(request: Request) -> dict[str, str]:
    values: dict[str, str] = {}
    for key, header in _ASSERTION_HEADERS.items():
        candidates = request.headers.getlist(header)
        if len(candidates) != 1 or not candidates[0]:
            raise ConsumerAuthenticationError
        values[key] = candidates[0]
    return values


def _parse_scopes(value: str) -> frozenset[str]:
    parts = value.split(" ")
    if (
        not parts
        or len(parts) > 16
        or any(_SCOPE_PATTERN.fullmatch(part) is None for part in parts)
        or len(set(parts)) != len(parts)
        or parts != sorted(parts)
    ):
        raise ConsumerAuthenticationError
    return frozenset(parts)
