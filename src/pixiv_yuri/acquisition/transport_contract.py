"""Structural contract shared by permit-guarded metadata transports."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
from ipaddress import ip_address
from re import fullmatch
from typing import Literal, Protocol
from urllib.parse import urlsplit, urlunsplit

MetadataTransportKind = Literal["numeric_http_loopback", "exact_https_dns"]


class MetadataTransportResponse(Protocol):
    """Minimum sanitized response surface consumed by a metadata Provider."""

    @property
    def status_code(self) -> int: ...

    @property
    def body(self) -> bytes: ...

    @property
    def headers(self) -> Mapping[str, str]: ...


class PermitGuardedMetadataTransport(Protocol):
    """Transport that binds every attempt to one stable persistent request key."""

    @property
    def transport_kind(self) -> MetadataTransportKind: ...

    @property
    def external_network_enabled(self) -> bool: ...

    def validate_origin(self, origin: str) -> None:
        """Reject an origin that is not pinned by this transport."""
        ...

    def fetch(
        self,
        url: str,
        *,
        timeout_seconds: float,
        estimated_cost: Decimal = Decimal("0"),
        now: datetime | None = None,
    ) -> MetadataTransportResponse: ...

    def signal_schema_drift(self, *, now: datetime | None = None) -> None: ...


def normalize_pinned_metadata_origin(origin: str) -> str:
    """Accept one numeric HTTP loopback or exact DNS HTTPS/443 origin."""
    try:
        parsed = urlsplit(origin)
        port = parsed.port
    except (TypeError, ValueError):
        raise ValueError("Pinned metadata origin is invalid.") from None
    if (
        parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path
    ):
        raise ValueError("Pinned metadata origin is invalid.")

    if parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "::1"}:
        host = f"[{parsed.hostname}]" if parsed.hostname == "::1" else parsed.hostname
        port_suffix = f":{port}" if port is not None else ""
        return f"http://{host}{port_suffix}"

    if parsed.scheme == "https" and port in (None, 443):
        try:
            host = normalize_exact_dns_host(parsed.hostname or "")
        except ValueError:
            raise ValueError("Pinned metadata origin is invalid.") from None
        return f"https://{host}"

    raise ValueError("Pinned metadata origin is invalid.")


def pinned_metadata_origin_kind(origin: str) -> MetadataTransportKind:
    """Return the required transport kind for an already normalized origin."""
    if origin.startswith("http://"):
        return "numeric_http_loopback"
    if origin.startswith("https://"):
        return "exact_https_dns"
    raise ValueError("Pinned metadata origin is invalid.")


def derive_transport_request_key(url: str, *, include_query: bool = False) -> str:
    """Derive one non-secret key without trusting a caller-provided identity."""
    canonical = _best_effort_canonical_url(url, include_query=include_query)
    digest = sha256(canonical.encode("utf-8", errors="surrogatepass")).hexdigest()
    return f"metadata_url:{digest}"


def normalize_exact_dns_host(host: str) -> str:
    """Normalize one exact ASCII DNS name while rejecting IPs and wildcards."""
    normalized = host.lower()
    if not normalized or len(normalized) > 253 or not normalized.isascii():
        raise ValueError("Host pins must be non-empty ASCII DNS names.")
    try:
        ip_address(normalized)
    except ValueError:
        pass
    else:
        raise ValueError("External host pins must be DNS names, not IP addresses.")
    labels = normalized.split(".")
    if any(
        not label
        or len(label) > 63
        or fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", label) is None
        for label in labels
    ):
        raise ValueError("Host pins must be exact DNS names.")
    return normalized


def _best_effort_canonical_url(url: str, *, include_query: bool) -> str:
    """Canonicalize valid URLs while retaining a deterministic invalid-url fallback."""
    if not isinstance(url, str):
        return "invalid-url-type"
    try:
        parsed = urlsplit(url)
        port = parsed.port
        host = (parsed.hostname or "").lower()
    except (TypeError, UnicodeError, ValueError):
        return url
    if not parsed.scheme or not host:
        return url
    if ":" in host:
        host = f"[{host}]"
    default_port = (parsed.scheme == "http" and port == 80) or (
        parsed.scheme == "https" and port == 443
    )
    if port is not None and not default_port:
        host = f"{host}:{port}"
    path = parsed.path or "/"
    query = parsed.query if include_query else ""
    return urlunsplit((parsed.scheme.lower(), host, path, query, ""))
