"""Executable offline contract for one reviewed source metadata endpoint."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pixiv_yuri.acquisition.transport_contract import normalize_exact_dns_host
from pixiv_yuri.governance.g0 import G0Approval, approval_fingerprint


class SourceEndpointContract(BaseModel):
    """Non-secret, network-free description of exactly one reviewed endpoint."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    version: Literal[1]
    status: Literal["reviewed"]
    approval_fingerprint: str
    reviewed_at: datetime
    expires_at: datetime
    review_reference: str = Field(min_length=5, max_length=500)
    origin: str = Field(min_length=12, max_length=255)
    path_template: str = Field(min_length=3, max_length=500)
    method: Literal["GET"] = "GET"
    credential_header: Literal["Cookie", "Authorization"] = "Cookie"
    accept_content_type: Literal["application/json"] = "application/json"
    redirects_allowed: Literal[False] = False
    query_parameters_allowed: Literal[False] = False
    media_download_allowed: Literal[False] = False
    planned_requests: Literal[1] = 1
    max_response_body_bytes: int = Field(ge=1, le=1_000_000)
    request_timeout_seconds: int = Field(ge=1, le=30)
    allowed_fields: set[str] = Field(min_length=1)
    allowed_age_ratings: set[Literal["all_ages", "r18", "r18g"]] = Field(
        min_length=1
    )

    @model_validator(mode="after")
    def validate_static_endpoint_shape(self) -> Self:
        _validate_sha256(self.approval_fingerprint)
        reviewed_at = _aware_utc(self.reviewed_at)
        expires_at = _aware_utc(self.expires_at)
        if expires_at <= reviewed_at:
            raise ValueError("Endpoint contract expiry must follow its review.")
        _validate_origin(self.origin)
        _validate_path_template(self.path_template)
        return self


class SourceEndpointReviewEvidence(BaseModel):
    """Payload-free human review evidence required to finalize one endpoint."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    version: Literal[1]
    status: Literal["ready"]
    reviewer_role: Literal["accountable-owner"]
    exact_origin: str = Field(min_length=12, max_length=255)
    path_template: str = Field(min_length=3, max_length=500)
    terms_reference: str = Field(min_length=5, max_length=500)
    terms_reviewed_at: datetime
    response_reviewed_at: datetime
    response_schema_sha256: str
    representative_sample_count: int = Field(ge=1, le=3)
    observed_content_type: Literal["application/json"]
    observed_fields: set[str] = Field(min_length=1)
    observed_max_body_bytes: int = Field(ge=1, le=1_000_000)
    redirects_observed: Literal[False]
    query_parameters_required: Literal[False]
    media_bytes_observed: Literal[False]
    secret_shaped_fields_observed: Literal[False]
    private_or_deleted_content_observed: Literal[False]

    @model_validator(mode="after")
    def validate_evidence_shape(self) -> Self:
        _validate_origin(self.exact_origin)
        _validate_path_template(self.path_template)
        _validate_sha256(self.response_schema_sha256)
        _aware_utc(self.terms_reviewed_at)
        _aware_utc(self.response_reviewed_at)
        return self


@dataclass(frozen=True, slots=True)
class SourceEndpointReviewResult:
    """Safe, non-authorizing endpoint review evidence."""

    status: Literal["passed"]
    approval_fingerprint: str
    checked_at: datetime
    planned_requests: Literal[1]
    field_count: int
    rating_count: int
    authorizes_network: Literal[False]


def review_source_endpoint_contract(
    contract: SourceEndpointContract,
    approval: G0Approval,
    *,
    now: datetime,
) -> SourceEndpointReviewResult:
    """Bind the reviewed endpoint to one active G0 without performing I/O."""
    checked_at = _aware_utc(now)
    fingerprint = approval_fingerprint(approval)
    if not approval.approved_at <= checked_at < approval.expires_at:
        raise ValueError("G0 approval is inactive.")
    if contract.approval_fingerprint != fingerprint:
        raise ValueError("Endpoint contract is bound to a different G0 approval.")
    if not approval.approved_at <= contract.reviewed_at <= checked_at:
        raise ValueError("Endpoint review time is outside the active approval window.")
    if not checked_at < contract.expires_at <= approval.expires_at:
        raise ValueError("Endpoint contract is inactive or outlives G0 approval.")
    if contract.allowed_fields != approval.source_scope.allowed_fields:
        raise ValueError("Endpoint fields must exactly match the G0 allowlist.")
    if contract.allowed_age_ratings != approval.source_scope.allowed_age_ratings:
        raise ValueError("Endpoint ratings must exactly match the G0 scope.")
    if contract.request_timeout_seconds != approval.traffic_limits.request_timeout_seconds:
        raise ValueError("Endpoint timeout must exactly match the G0 limit.")
    if (
        approval.source_scope.authentication_mode != "user_managed_session"
        or approval.source_scope.content_visibility != "authenticated_public"
    ):
        raise ValueError("Endpoint contract requires authenticated-public G0 scope.")
    return SourceEndpointReviewResult(
        status="passed",
        approval_fingerprint=fingerprint,
        checked_at=checked_at,
        planned_requests=1,
        field_count=len(contract.allowed_fields),
        rating_count=len(contract.allowed_age_ratings),
        authorizes_network=False,
    )


def finalize_source_endpoint_contract(
    evidence: SourceEndpointReviewEvidence,
    approval: G0Approval,
    *,
    expires_at: datetime,
    now: datetime,
) -> SourceEndpointContract:
    """Convert complete human evidence into a non-authorizing reviewed contract."""
    checked_at = _aware_utc(now)
    contract_expiry = _aware_utc(expires_at)
    terms_at = _aware_utc(evidence.terms_reviewed_at)
    response_at = _aware_utc(evidence.response_reviewed_at)
    reviewed_at = max(terms_at, response_at)
    if not approval.approved_at <= terms_at <= checked_at:
        raise ValueError("Endpoint terms evidence is outside the active review window.")
    if not approval.approved_at <= response_at <= checked_at:
        raise ValueError("Endpoint response evidence is outside the active review window.")
    if evidence.observed_fields != approval.source_scope.allowed_fields:
        raise ValueError("Endpoint response fields do not exactly match G0.")
    contract = SourceEndpointContract(
        version=1,
        status="reviewed",
        approval_fingerprint=approval_fingerprint(approval),
        reviewed_at=reviewed_at,
        expires_at=contract_expiry,
        review_reference=(
            f"{evidence.terms_reference}; response-schema-sha256:"
            f"{evidence.response_schema_sha256}"
        ),
        origin=evidence.exact_origin,
        path_template=evidence.path_template,
        method="GET",
        credential_header="Cookie",
        accept_content_type="application/json",
        redirects_allowed=False,
        query_parameters_allowed=False,
        media_download_allowed=False,
        planned_requests=1,
        max_response_body_bytes=evidence.observed_max_body_bytes,
        request_timeout_seconds=approval.traffic_limits.request_timeout_seconds,
        allowed_fields=set(evidence.observed_fields),
        allowed_age_ratings=set(approval.source_scope.allowed_age_ratings),
    )
    review_source_endpoint_contract(contract, approval, now=checked_at)
    return contract


def _validate_origin(origin: str) -> None:
    try:
        parsed = urlsplit(origin)
        host = normalize_exact_dns_host(parsed.hostname or "")
        port = parsed.port
    except (UnicodeError, ValueError):
        raise ValueError("Endpoint origin must be an exact HTTPS DNS origin.") from None
    if (
        parsed.scheme != "https"
        or not host
        or port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or bool(parsed.query)
        or bool(parsed.fragment)
    ):
        raise ValueError("Endpoint origin must be an exact HTTPS DNS origin.")


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
        raise ValueError("Endpoint path must be a fixed query-free source-id template.")


def _validate_sha256(value: str) -> None:
    if len(value) != 64 or not value.isascii() or value != value.lower():
        raise ValueError("Approval fingerprint must be lowercase SHA-256 hexadecimal.")
    try:
        bytes.fromhex(value)
    except ValueError:
        raise ValueError("Approval fingerprint must be lowercase SHA-256 hexadecimal.") from None


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Endpoint contract timestamps must include a timezone.")
    return value.astimezone(UTC)
