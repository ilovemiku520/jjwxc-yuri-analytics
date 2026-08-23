"""Independent contract for a no-login, metadata-only public source."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, Literal, Self
from urllib.parse import quote, urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pixiv_yuri.acquisition.transport_contract import normalize_exact_dns_host

AnonymousStopCondition = Literal[
    "forbidden_403",
    "rate_limited_429",
    "challenge_or_login",
    "schema_drift",
]

_REQUIRED_STOP_CONDITIONS: frozenset[AnonymousStopCondition] = frozenset(
    {"forbidden_403", "rate_limited_429", "challenge_or_login", "schema_drift"}
)
_FORBIDDEN_FIELD_FRAGMENTS = (
    "authorization",
    "cookie",
    "credential",
    "password",
    "secret",
    "session",
    "token",
    "image",
    "media",
    "thumbnail",
    "download",
    "original",
    "payload",
    "source_url",
)


class AnonymousPublicReviewEvidence(BaseModel):
    """Human-reviewed, payload-free evidence for one public source contract."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    version: Literal[1]
    status: Literal["ready"]
    access_mode: Literal["unauthenticated_public"]
    authentication_mode: Literal["none"]
    content_visibility: Literal["unauthenticated_public"]
    exact_origin: str = Field(min_length=12, max_length=255)
    path_template: str = Field(min_length=3, max_length=500)
    terms_reference: str = Field(min_length=5, max_length=500)
    terms_access_status: Literal["public_unauthenticated_metadata_allowed"]
    terms_reviewed_at: datetime
    robots_reference: str = Field(min_length=5, max_length=500)
    robots_directive_status: Literal["allowed"]
    robots_reviewed_at: datetime
    response_reviewed_at: datetime
    credentials_required: Literal[False]
    commercial_use_allowed: Literal[False]
    redistribution_allowed: Literal[False]
    representative_sample_count: int = Field(ge=1, le=3)
    observed_content_type: Literal["application/json", "text/html"]
    observed_fields: set[str] = Field(min_length=1)
    allowed_age_ratings: set[Literal["all_ages"]]
    observed_max_body_bytes: int = Field(ge=1, le=1_000_000)
    response_schema_sha256: str
    redirects_observed: Literal[False]
    query_parameters_required: Literal[False]
    media_bytes_observed: Literal[False]
    secret_shaped_fields_observed: Literal[False]
    private_or_deleted_content_observed: Literal[False]
    challenge_or_login_observed: Literal[False]

    @model_validator(mode="after")
    def validate_review_evidence(self) -> Self:
        _validate_origin(self.exact_origin)
        _validate_path_template(self.path_template)
        _validate_reference(self.terms_reference)
        _validate_reference(self.robots_reference)
        _validate_aware(self.terms_reviewed_at)
        _validate_aware(self.robots_reviewed_at)
        _validate_aware(self.response_reviewed_at)
        _validate_sha256(self.response_schema_sha256)
        _validate_fields(self.observed_fields)
        if self.allowed_age_ratings != {"all_ages"}:
            raise ValueError("Anonymous public evidence must be all-ages only.")
        return self


class AnonymousPublicSourceContract(BaseModel):
    """Executable, non-authorizing boundary for one anonymous public source."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    version: Literal[1]
    status: Literal["reviewed"]
    access_mode: Literal["unauthenticated_public"]
    authentication_mode: Literal["none"]
    content_visibility: Literal["unauthenticated_public"]
    authorizes_network: Literal[False]
    credentials_required: Literal[False]
    credential_header: Literal[None] = None
    commercial_use_allowed: Literal[False]
    redistribution_allowed: Literal[False]
    terms_reference: str = Field(min_length=5, max_length=500)
    terms_access_status: Literal["public_unauthenticated_metadata_allowed"]
    terms_reviewed_at: datetime
    robots_reference: str = Field(min_length=5, max_length=500)
    robots_directive_status: Literal["allowed"]
    robots_reviewed_at: datetime
    reviewed_at: datetime
    expires_at: datetime
    review_reference: str = Field(min_length=5, max_length=500)
    review_evidence_sha256: str
    origin: str = Field(min_length=12, max_length=255)
    path_template: str = Field(min_length=3, max_length=500)
    method: Literal["GET"] = "GET"
    accept_content_type: Literal["application/json", "text/html"]
    redirects_allowed: Literal[False] = False
    query_parameters_allowed: Literal[False] = False
    media_download_allowed: Literal[False] = False
    planned_requests: Literal[1] = 1
    initial_request_cap: Literal[1] = 1
    concurrency: Literal[1] = 1
    min_request_interval_seconds: int = Field(ge=20, le=3600)
    requests_per_minute: int = Field(ge=1, le=3)
    max_response_body_bytes: int = Field(ge=1, le=1_000_000)
    allowed_fields: set[str] = Field(min_length=1)
    allowed_age_ratings: set[Literal["all_ages"]]
    response_schema_sha256: str
    stop_conditions: set[AnonymousStopCondition]

    @model_validator(mode="after")
    def validate_contract(self) -> Self:
        _validate_origin(self.origin)
        _validate_path_template(self.path_template)
        _validate_reference(self.terms_reference)
        _validate_reference(self.robots_reference)
        _validate_aware(self.terms_reviewed_at)
        _validate_aware(self.robots_reviewed_at)
        _validate_aware(self.reviewed_at)
        _validate_aware(self.expires_at)
        _validate_sha256(self.review_evidence_sha256)
        _validate_sha256(self.response_schema_sha256)
        _validate_fields(self.allowed_fields)
        if self.allowed_age_ratings != {"all_ages"}:
            raise ValueError("Anonymous public contracts must be all-ages only.")
        if self.expires_at <= self.reviewed_at:
            raise ValueError("Anonymous public contract expiry must follow review.")
        if self.requests_per_minute > 60 // self.min_request_interval_seconds:
            raise ValueError("Request rate exceeds the minimum interval.")
        if not _REQUIRED_STOP_CONDITIONS.issubset(self.stop_conditions):
            raise ValueError("Anonymous public contract is missing a stop condition.")
        return self


def finalize_anonymous_public_contract(
    evidence: AnonymousPublicReviewEvidence,
    *,
    expires_at: datetime,
    now: datetime,
) -> AnonymousPublicSourceContract:
    """Finalize reviewed evidence without consulting G0 or authorizing a request."""
    checked_at = _validate_aware(now)
    contract_expires_at = _validate_aware(expires_at)
    review_times = (
        evidence.terms_reviewed_at,
        evidence.robots_reviewed_at,
        evidence.response_reviewed_at,
    )
    if any(_validate_aware(value) > checked_at for value in review_times):
        raise ValueError("Anonymous public evidence cannot be from the future.")
    if contract_expires_at <= checked_at:
        raise ValueError("Anonymous public contract must not be expired.")
    reviewed_at = max(_validate_aware(value) for value in review_times)
    evidence_hash = _sha256(evidence.model_dump(mode="json"))
    return AnonymousPublicSourceContract(
        version=1,
        status="reviewed",
        access_mode=evidence.access_mode,
        authentication_mode=evidence.authentication_mode,
        content_visibility=evidence.content_visibility,
        authorizes_network=False,
        credentials_required=False,
        credential_header=None,
        commercial_use_allowed=False,
        redistribution_allowed=False,
        terms_reference=evidence.terms_reference,
        terms_access_status=evidence.terms_access_status,
        terms_reviewed_at=_validate_aware(evidence.terms_reviewed_at),
        robots_reference=evidence.robots_reference,
        robots_directive_status=evidence.robots_directive_status,
        robots_reviewed_at=_validate_aware(evidence.robots_reviewed_at),
        reviewed_at=reviewed_at,
        expires_at=contract_expires_at,
        review_reference=(
            f"terms:{evidence.terms_reference};robots:{evidence.robots_reference};"
            f"response-schema-sha256:{evidence.response_schema_sha256}"
        ),
        review_evidence_sha256=evidence_hash,
        origin=evidence.exact_origin,
        path_template=evidence.path_template,
        accept_content_type=evidence.observed_content_type,
        max_response_body_bytes=evidence.observed_max_body_bytes,
        allowed_fields=set(evidence.observed_fields),
        allowed_age_ratings={"all_ages"},
        response_schema_sha256=evidence.response_schema_sha256,
        stop_conditions=set(_REQUIRED_STOP_CONDITIONS),
        min_request_interval_seconds=20,
        requests_per_minute=3,
    )


def render_anonymous_public_url(
    contract: AnonymousPublicSourceContract, source_id: str
) -> str:
    """Render one path-only URL; no query or credential material is accepted."""
    if not isinstance(source_id, str) or not 1 <= len(source_id) <= 255:
        raise ValueError("Source identifier must contain between 1 and 255 characters.")
    encoded_id = quote(source_id, safe="")
    url = contract.origin + contract.path_template.replace("{source_id}", encoded_id)
    parsed = urlsplit(url)
    if parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise ValueError("Anonymous public URL must be path-only.")
    return url


def schema_fingerprint(payload: Mapping[str, Any]) -> str:
    """Hash field names and JSON value shapes without hashing payload values."""
    shape = _shape(payload)
    encoded = json.dumps(shape, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(encoded.encode("utf-8")).hexdigest()


def _shape(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _shape(child)
            for key, child in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, list):
        shapes = {
            json.dumps(_shape(child), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            for child in value
        }
        return {"array": [json.loads(item) for item in sorted(shapes)]}
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    raise TypeError("Metadata values must be JSON-compatible.")


def _validate_origin(origin: str) -> None:
    try:
        parsed = urlsplit(origin)
        host = normalize_exact_dns_host(parsed.hostname or "")
        port = parsed.port
    except (TypeError, UnicodeError, ValueError):
        raise ValueError("Anonymous public origin must be an exact HTTPS DNS origin.") from None
    if (
        parsed.scheme != "https"
        or not host
        or port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Anonymous public origin must be an exact HTTPS DNS origin.")


def _validate_path_template(path_template: str) -> None:
    if (
        not path_template.startswith("/")
        or path_template.count("{source_id}") != 1
        or "?" in path_template
        or "#" in path_template
        or "\\" in path_template
        or any(segment in {"", ".", ".."} for segment in path_template.split("/")[1:])
        or "{" in path_template.replace("{source_id}", "")
        or "}" in path_template.replace("{source_id}", "")
    ):
        raise ValueError("Anonymous public path must be a fixed query-free source-id template.")


def _validate_fields(fields: set[str]) -> None:
    if not fields or any(not isinstance(field, str) or not field for field in fields):
        raise ValueError("Anonymous public fields must be non-empty strings.")
    for field in fields:
        normalized = field.strip().lower().replace("-", "_")
        if any(fragment in normalized for fragment in _FORBIDDEN_FIELD_FRAGMENTS):
            raise ValueError("Anonymous public fields cannot include secret or media shapes.")


def _validate_reference(reference: str) -> None:
    normalized = reference.strip()
    if not normalized or _contains_secret_shape(normalized):
        raise ValueError("Anonymous public review references must be non-secret.")


def _contains_secret_shape(value: str) -> bool:
    lowered = value.lower()
    return (
        "-----begin " in lowered
        or "authorization:" in lowered
        or "cookie:" in lowered
        or "password=" in lowered
        or "token=" in lowered
        or "@" in lowered and "://" in lowered
    )


def _validate_sha256(value: str) -> None:
    if len(value) != 64 or value != value.lower() or not value.isascii():
        raise ValueError("Anonymous public hashes must be lowercase SHA-256 values.")
    try:
        bytes.fromhex(value)
    except ValueError:
        raise ValueError("Anonymous public hashes must be lowercase SHA-256 values.") from None


def _validate_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Anonymous public timestamps must include a timezone.")
    return value.astimezone(UTC)


def _sha256(value: object) -> str:
    encoded = json.dumps(
        _canonicalize(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _canonicalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _canonicalize(child) for key, child in value.items()}
    if isinstance(value, list):
        children = [_canonicalize(child) for child in value]
        return sorted(
            children,
            key=lambda child: json.dumps(child, ensure_ascii=False, sort_keys=True),
        )
    return value
