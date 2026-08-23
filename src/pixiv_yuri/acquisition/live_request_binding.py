"""Versioned, unambiguous identity for one exact live metadata request."""

from __future__ import annotations

import json
import string
import unicodedata
from hashlib import sha256
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

from pixiv_yuri.acquisition.models import AcquisitionRequest, EntityType
from pixiv_yuri.acquisition.transport_contract import normalize_exact_dns_host

_HEX = frozenset(string.hexdigits)
_UNRESERVED = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
)


class CanonicalLiveRequestBinding(BaseModel):
    """Immutable v1 binding whose canonical JSON is safe to hash durably."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    version: Literal[1] = 1
    approval_fingerprint: str
    provider_id: str = Field(min_length=1, max_length=100)
    entity_type: EntityType
    source_id: str = Field(min_length=1, max_length=255)
    canonical_url: str = Field(min_length=12, max_length=1200)

    @field_validator("approval_fingerprint")
    @classmethod
    def validate_approval_fingerprint(cls, value: str) -> str:
        if len(value) != 64 or not value.isascii() or value != value.lower():
            raise ValueError("Approval fingerprint must be lowercase SHA-256 text.")
        try:
            bytes.fromhex(value)
        except ValueError:
            raise ValueError("Approval fingerprint must be lowercase SHA-256 text.") from None
        return value

    @field_validator("provider_id")
    @classmethod
    def validate_provider_id(cls, value: str) -> str:
        if (
            not value.isascii()
            or not value[0].islower()
            or any(
                character not in string.ascii_lowercase + string.digits + "._-"
                for character in value
            )
        ):
            raise ValueError("Provider identifier must be stable lowercase ASCII text.")
        return value

    @field_validator("source_id")
    @classmethod
    def normalize_source_id(cls, value: str) -> str:
        normalized = unicodedata.normalize("NFC", value)
        if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
            raise ValueError("Source identifier cannot contain control characters.")
        return normalized

    @field_validator("canonical_url")
    @classmethod
    def normalize_url_field(cls, value: str) -> str:
        return normalize_exact_https_url(value)

    @classmethod
    def from_request(
        cls,
        *,
        approval_fingerprint: str,
        provider_id: str,
        request: AcquisitionRequest,
        exact_url: str,
    ) -> CanonicalLiveRequestBinding:
        """Build a binding from an immutable acquisition request and exact URL."""
        return cls(
            approval_fingerprint=approval_fingerprint,
            provider_id=provider_id,
            entity_type=request.entity_type,
            source_id=request.source_id,
            canonical_url=exact_url,
        )

    @property
    def canonical_json(self) -> bytes:
        """Return the sole v1 hash preimage as unambiguous canonical UTF-8 JSON."""
        payload = {
            "approval_fingerprint": self.approval_fingerprint,
            "canonical_url": self.canonical_url,
            "entity_type": self.entity_type.value,
            "provider_id": self.provider_id,
            "source_id": self.source_id,
            "version": self.version,
        }
        return json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")

    @property
    def binding_hash(self) -> str:
        """Return the lowercase SHA-256 digest of canonical v1 JSON."""
        return sha256(self.canonical_json).hexdigest()

    @property
    def request_key(self) -> str:
        """Return the sole bounded key that slot, permit, and journal must hash."""
        return self.canonical_json.decode("utf-8")


def normalize_exact_https_url(url: str) -> str:
    """Normalize one exact DNS HTTPS URL while rejecting ambiguous components."""
    if not isinstance(url, str) or not url or not url.isascii():
        raise ValueError("Live request URL must be non-empty ASCII HTTPS text.")
    if any(character in url for character in ("\r", "\n", "\t", "\\")):
        raise ValueError("Live request URL contains an ambiguous character.")
    try:
        parsed = urlsplit(url)
        port = parsed.port
        host = normalize_exact_dns_host(parsed.hostname or "")
    except (TypeError, UnicodeError, ValueError):
        raise ValueError("Live request URL must use one exact HTTPS origin.") from None
    if (
        parsed.scheme.lower() != "https"
        or port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
        or bool(parsed.query)
        or bool(parsed.fragment)
    ):
        raise ValueError("Live request URL must use one exact HTTPS origin.")

    path = _normalize_ascii_path(parsed.path or "/")
    if any(segment in {".", ".."} for segment in path.split("/")):
        raise ValueError("Live request URL cannot contain dot path segments.")
    return urlunsplit(("https", host, path, "", ""))


def _normalize_ascii_path(path: str) -> str:
    if not path.startswith("/"):
        raise ValueError("Live request URL path must be absolute.")
    normalized: list[str] = []
    index = 0
    while index < len(path):
        character = path[index]
        if ord(character) < 32 or ord(character) == 127:
            raise ValueError("Live request URL path contains a control character.")
        if character != "%":
            normalized.append(character)
            index += 1
            continue
        if index + 2 >= len(path) or any(
            digit not in _HEX for digit in path[index + 1 : index + 3]
        ):
            raise ValueError("Live request URL contains invalid percent encoding.")
        encoded = path[index + 1 : index + 3].upper()
        decoded = chr(int(encoded, 16))
        normalized.append(decoded if decoded in _UNRESERVED else f"%{encoded}")
        index += 3
    return "".join(normalized)
