"""Validate non-secret production identity and TLS evidence without deploying anything."""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import re
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

_IDENTIFIER = re.compile(r"^[A-Za-z0-9._-]{2,100}$")
_DNS_NAME = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PLACEHOLDERS = frozenset({"change-me", "draft", "placeholder", "tbd", "todo", "unconfigured"})
_FORBIDDEN_KEYS = frozenset(
    {
        "account_password",
        "authorization",
        "api_key",
        "bearer",
        "browser_cookie",
        "client_secret",
        "cookie",
        "credential",
        "hmac_secret",
        "key_material",
        "password",
        "private_key",
        "private_key_pem",
        "refresh_token",
        "session_token",
        "token",
    }
)


class IdentityEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    adapter: Literal["trusted_hmac_proxy"]
    product: str = Field(min_length=2, max_length=100)
    deployment_reference: str = Field(min_length=2, max_length=100)
    proxy_id: str = Field(min_length=2, max_length=64)
    direct_api_access_blocked: bool
    secret_delivery: Literal["unconfigured", "runtime_read_only_file"]
    secret_rotation_days: int = Field(ge=1, le=365)
    assertion_max_age_seconds: int = Field(ge=1, le=300)
    health_monitoring_enabled: bool
    production_smoke_sha256: str

    @field_validator("deployment_reference", "proxy_id")
    @classmethod
    def validate_identifier(cls, value: str) -> str:
        if _IDENTIFIER.fullmatch(value) is None:
            raise ValueError("deployment identifier is invalid")
        return value


class TlsEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    hostname: str = Field(min_length=1, max_length=253)
    certificate_authority: str = Field(min_length=2, max_length=100)
    certificate_sha256: str
    certificate_not_after: datetime
    minimum_tls_version: Literal["TLSv1.2", "TLSv1.3"]
    private_key_storage: Literal["unconfigured", "runtime_secret"]
    automated_renewal: bool
    renewal_monitoring_enabled: bool
    hsts_enabled: bool
    production_smoke_sha256: str

    @field_validator("certificate_not_after")
    @classmethod
    def validate_time(cls, value: datetime) -> datetime:
        return _aware_utc(value)


class ProductionDeploymentEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: Literal[1]
    status: Literal["draft", "reviewed"]
    deployment_kind: Literal["production"]
    deployment_id: str = Field(min_length=2, max_length=100)
    accountable_owner: str = Field(min_length=2, max_length=100)
    reviewer: str = Field(min_length=2, max_length=100)
    reviewed_at: datetime
    expires_at: datetime
    identity: IdentityEvidence
    tls: TlsEvidence

    @field_validator("deployment_id")
    @classmethod
    def validate_deployment_id(cls, value: str) -> str:
        if _IDENTIFIER.fullmatch(value) is None:
            raise ValueError("deployment ID is invalid")
        return value

    @field_validator("reviewed_at", "expires_at")
    @classmethod
    def validate_review_time(cls, value: datetime) -> datetime:
        return _aware_utc(value)


@dataclass(frozen=True, slots=True)
class ProductionEvidenceReport:
    generated_at: str
    status: str
    evidence_sha256: str
    deployment_id: str | None
    identity_reviewed: bool
    tls_reviewed: bool
    production_deployment_reviewed: bool
    violations: tuple[str, ...]
    external_network_used: bool
    external_publication_approved: bool
    real_source_collection_authorized: bool


def review_production_evidence(
    payload: dict[str, Any], *, now: datetime | None = None
) -> ProductionEvidenceReport:
    checked_at = _aware_utc(now or datetime.now(UTC))
    evidence_hash = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if _contains_forbidden_key(payload):
        return _blocked(checked_at, evidence_hash, ("secret_shaped_field_forbidden",))
    if _contains_secret_value(payload):
        return _blocked(checked_at, evidence_hash, ("secret_value_shape_forbidden",))
    try:
        evidence = ProductionDeploymentEvidence.model_validate(payload)
    except ValidationError:
        return _blocked(checked_at, evidence_hash, ("production_evidence_invalid",))

    violations: list[str] = []
    reviewed_at = _aware_utc(evidence.reviewed_at)
    expires_at = _aware_utc(evidence.expires_at)
    certificate_not_after = _aware_utc(evidence.tls.certificate_not_after)
    if evidence.status != "reviewed":
        violations.append("production_evidence_not_reviewed")
    if reviewed_at > checked_at or not reviewed_at <= checked_at < expires_at:
        violations.append("production_evidence_inactive")
    if expires_at - reviewed_at > timedelta(days=90):
        violations.append("production_evidence_too_long")
    if _placeholder(evidence.accountable_owner) or _placeholder(evidence.reviewer):
        violations.append("accountability_unresolved")

    identity = evidence.identity
    if _placeholder(identity.product) or _placeholder(identity.deployment_reference):
        violations.append("identity_deployment_unresolved")
    if not identity.direct_api_access_blocked:
        violations.append("direct_api_access_not_blocked")
    if identity.secret_delivery != "runtime_read_only_file":
        violations.append("identity_secret_delivery_unreviewed")
    if identity.secret_rotation_days > 90 or identity.assertion_max_age_seconds > 60:
        violations.append("identity_lifecycle_out_of_bounds")
    if not identity.health_monitoring_enabled:
        violations.append("identity_monitoring_disabled")
    if not _valid_nonzero_sha256(identity.production_smoke_sha256):
        violations.append("identity_production_smoke_missing")

    tls = evidence.tls
    if not _production_dns_name(tls.hostname):
        violations.append("production_hostname_invalid")
    if _placeholder(tls.certificate_authority):
        violations.append("certificate_authority_unresolved")
    if not _valid_nonzero_sha256(tls.certificate_sha256):
        violations.append("certificate_fingerprint_missing")
    if certificate_not_after < expires_at:
        violations.append("certificate_expires_before_review")
    if tls.private_key_storage != "runtime_secret":
        violations.append("tls_private_key_storage_unreviewed")
    if not tls.automated_renewal or not tls.renewal_monitoring_enabled:
        violations.append("tls_renewal_controls_missing")
    if not tls.hsts_enabled:
        violations.append("hsts_disabled")
    if not _valid_nonzero_sha256(tls.production_smoke_sha256):
        violations.append("tls_production_smoke_missing")

    reviewed = not violations
    return ProductionEvidenceReport(
        generated_at=checked_at.isoformat(),
        status="reviewed" if reviewed else "blocked",
        evidence_sha256=evidence_hash,
        deployment_id=evidence.deployment_id,
        identity_reviewed=reviewed,
        tls_reviewed=reviewed,
        production_deployment_reviewed=reviewed,
        violations=tuple(violations),
        external_network_used=False,
        external_publication_approved=False,
        real_source_collection_authorized=False,
    )


def evidence_schema() -> dict[str, Any]:
    schema = ProductionDeploymentEvidence.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = "urn:pixiv-yuri-analytics:production-identity-tls-evidence:v1"
    schema["x-secret-values-forbidden"] = sorted(_FORBIDDEN_KEYS)
    schema["x-authorizes-external-publication"] = False
    schema["x-authorizes-real-source-collection"] = False
    return schema


def draft_evidence(*, now: datetime | None = None) -> dict[str, Any]:
    checked_at = _aware_utc(now or datetime.now(UTC))
    expires_at = checked_at + timedelta(days=30)
    return {
        "version": 1,
        "status": "draft",
        "deployment_kind": "production",
        "deployment_id": "production-draft",
        "accountable_owner": "change-me",
        "reviewer": "change-me",
        "reviewed_at": checked_at.isoformat(),
        "expires_at": expires_at.isoformat(),
        "identity": {
            "adapter": "trusted_hmac_proxy",
            "product": "unconfigured",
            "deployment_reference": "draft",
            "proxy_id": "private-edge",
            "direct_api_access_blocked": False,
            "secret_delivery": "unconfigured",
            "secret_rotation_days": 365,
            "assertion_max_age_seconds": 300,
            "health_monitoring_enabled": False,
            "production_smoke_sha256": "0" * 64,
        },
        "tls": {
            "hostname": "api.example.invalid",
            "certificate_authority": "unconfigured",
            "certificate_sha256": "0" * 64,
            "certificate_not_after": expires_at.isoformat(),
            "minimum_tls_version": "TLSv1.2",
            "private_key_storage": "unconfigured",
            "automated_renewal": False,
            "renewal_monitoring_enabled": False,
            "hsts_enabled": False,
            "production_smoke_sha256": "0" * 64,
        },
    }


def _blocked(
    checked_at: datetime, evidence_hash: str, violations: tuple[str, ...]
) -> ProductionEvidenceReport:
    return ProductionEvidenceReport(
        generated_at=checked_at.isoformat(),
        status="blocked",
        evidence_sha256=evidence_hash,
        deployment_id=None,
        identity_reviewed=False,
        tls_reviewed=False,
        production_deployment_reviewed=False,
        violations=violations,
        external_network_used=False,
        external_publication_approved=False,
        real_source_collection_authorized=False,
    )


def _contains_forbidden_key(value: object) -> bool:
    if isinstance(value, dict):
        return any(
            str(key).lower() in _FORBIDDEN_KEYS or _contains_forbidden_key(child)
            for key, child in value.items()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_key(child) for child in value)
    return False


def _contains_secret_value(value: object) -> bool:
    if isinstance(value, dict):
        return any(_contains_secret_value(child) for child in value.values())
    if isinstance(value, list):
        return any(_contains_secret_value(child) for child in value)
    if not isinstance(value, str):
        return False
    normalized = value.strip()
    return bool(
        re.search(r"-----BEGIN [A-Z ]*PRIVATE KEY-----", normalized, re.IGNORECASE)
        or re.fullmatch(r"(?i:bearer)\s+\S+", normalized)
        or re.fullmatch(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", normalized)
        or re.search(r"^[a-z][a-z0-9+.-]*://[^/@:]+:[^/@]+@", normalized, re.IGNORECASE)
    )


def _placeholder(value: str) -> bool:
    normalized = value.strip().lower()
    return normalized in _PLACEHOLDERS or normalized.endswith(".invalid")


def _valid_nonzero_sha256(value: str) -> bool:
    return _SHA256.fullmatch(value) is not None and value != "0" * 64


def _production_dns_name(value: str) -> bool:
    normalized = value.strip().lower().rstrip(".")
    try:
        ipaddress.ip_address(normalized)
    except ValueError:
        pass
    else:
        return False
    return (
        normalized != "localhost"
        and not normalized.endswith((".invalid", ".localhost", ".test", ".example"))
        and _DNS_NAME.fullmatch(normalized) is not None
    )


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("production evidence timestamps must be timezone-aware")
    return value.astimezone(UTC)


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("production evidence must be an object")
    return value


def _write(path: Path, payload: dict[str, Any], *, force: bool) -> None:
    if path.exists() and not force:
        raise FileExistsError("output already exists; pass --force to replace it")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command_name in ("schema", "init"):
        command = subparsers.add_parser(command_name)
        command.add_argument("--output", type=Path, required=True)
        command.add_argument("--force", action="store_true")
    review = subparsers.add_parser("review")
    review.add_argument("--evidence", type=Path, required=True)
    review.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "schema":
            _write(args.output, evidence_schema(), force=args.force)
            return 0
        if args.command == "init":
            _write(args.output, draft_evidence(), force=args.force)
            return 0
        report = review_production_evidence(_load_object(args.evidence))
    except (OSError, ValueError, json.JSONDecodeError):
        report = _blocked(datetime.now(UTC), "0" * 64, ("production_evidence_input_invalid",))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(asdict(report), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    stream = sys.stdout if report.status == "reviewed" else sys.stderr
    print(json.dumps(asdict(report), sort_keys=True), file=stream)
    return 0 if report.status == "reviewed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
