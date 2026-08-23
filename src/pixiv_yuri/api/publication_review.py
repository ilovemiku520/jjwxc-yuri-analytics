"""Fail-closed external-publication deployment review."""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

_DNS_NAME = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)
_IDENTIFIER = re.compile(r"^[A-Za-z0-9._-]{2,100}$")
_PLACEHOLDERS = frozenset({"change-me", "draft", "placeholder", "tbd", "todo", "unconfigured"})


class IdentityProxyDeployment(BaseModel):
    """Non-secret deployment facts for the identity-aware proxy."""

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

    @field_validator("deployment_reference", "proxy_id")
    @classmethod
    def validate_identifier(cls, value: str) -> str:
        if _IDENTIFIER.fullmatch(value) is None:
            raise ValueError("deployment identifier is invalid")
        return value


class TlsDeployment(BaseModel):
    """Non-secret production certificate and transport lifecycle facts."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    hostname: str = Field(min_length=1, max_length=253)
    certificate_authority: str = Field(min_length=2, max_length=100)
    certificate_not_after: datetime
    minimum_tls_version: Literal["TLSv1.2", "TLSv1.3"]
    private_key_storage: Literal["unconfigured", "runtime_secret"]
    automated_renewal: bool
    renewal_monitoring_enabled: bool
    hsts_enabled: bool

    @field_validator("certificate_not_after")
    @classmethod
    def validate_certificate_time(cls, value: datetime) -> datetime:
        return _aware_utc(value)


class PublicationDeploymentManifest(BaseModel):
    """Accountable approval of one exact external API deployment."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: Literal[1]
    status: Literal["draft", "approved"]
    deployment_id: str = Field(min_length=2, max_length=100)
    accountable_owner: str = Field(min_length=2, max_length=100)
    approver: str = Field(min_length=2, max_length=100)
    reviewed_at: datetime
    expires_at: datetime
    identity_proxy: IdentityProxyDeployment
    tls: TlsDeployment

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
class PublicationReviewReport:
    """Machine decision that never broadens source-collection authority."""

    generated_at: str
    status: str
    manifest_sha256: str | None
    deployment_id: str | None
    approved_hostname: str | None
    approval_expires_at: str | None
    external_publication_approved: bool
    real_source_collection_authorized: bool
    violations: tuple[str, ...]
    external_network_used: bool


def review_publication(
    *,
    phase2_report: dict[str, Any],
    manifest_payload: dict[str, Any],
    now: datetime | None = None,
) -> PublicationReviewReport:
    """Review non-secret deployment evidence without changing network state."""
    checked_at = _aware_utc(now or datetime.now(UTC))
    manifest_hash = hashlib.sha256(
        json.dumps(manifest_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    try:
        manifest = PublicationDeploymentManifest.model_validate(manifest_payload)
    except ValidationError:
        return _blocked_report(
            checked_at=checked_at,
            manifest_hash=manifest_hash,
            violations=("deployment_manifest_invalid",),
        )

    violations: list[str] = []
    if phase2_report.get("status") != "passed_private_only":
        violations.append("private_boundary_review_not_passed")
    if phase2_report.get("private_read_api_ready") is not True:
        violations.append("private_read_api_not_ready")
    if phase2_report.get("trusted_proxy_adapter_verified") is not True:
        violations.append("trusted_proxy_adapter_not_verified")
    if phase2_report.get("loopback_tls_verified") is not True:
        violations.append("loopback_tls_not_verified")
    if phase2_report.get("shared_consumer_controls_verified") is not True:
        violations.append("shared_consumer_controls_not_verified")
    if phase2_report.get("real_source_collection_count") != 0:
        violations.append("real_source_collection_not_zero")

    reviewed_at = _aware_utc(manifest.reviewed_at)
    expires_at = _aware_utc(manifest.expires_at)
    certificate_not_after = _aware_utc(manifest.tls.certificate_not_after)
    if manifest.status != "approved":
        violations.append("deployment_manifest_not_approved")
    if reviewed_at > checked_at:
        violations.append("deployment_review_in_future")
    if not reviewed_at <= checked_at < expires_at:
        violations.append("deployment_approval_inactive")
    if expires_at - reviewed_at > timedelta(days=90):
        violations.append("deployment_approval_too_long")
    if _is_placeholder(manifest.accountable_owner):
        violations.append("accountable_owner_unresolved")
    if _is_placeholder(manifest.approver):
        violations.append("approver_unresolved")

    identity = manifest.identity_proxy
    if _is_placeholder(identity.product):
        violations.append("identity_proxy_product_unresolved")
    if _is_placeholder(identity.deployment_reference):
        violations.append("identity_proxy_deployment_unresolved")
    if not identity.direct_api_access_blocked:
        violations.append("direct_api_access_not_blocked")
    if identity.secret_delivery != "runtime_read_only_file":
        violations.append("identity_secret_delivery_unreviewed")
    if identity.secret_rotation_days > 90:
        violations.append("identity_secret_rotation_too_long")
    if identity.assertion_max_age_seconds > 60:
        violations.append("identity_assertion_age_too_long")
    if not identity.health_monitoring_enabled:
        violations.append("identity_proxy_monitoring_disabled")

    tls = manifest.tls
    if not _production_dns_name(tls.hostname):
        violations.append("production_hostname_invalid")
    if _is_placeholder(tls.certificate_authority):
        violations.append("certificate_authority_unresolved")
    if certificate_not_after < expires_at:
        violations.append("certificate_expires_before_approval")
    if tls.private_key_storage != "runtime_secret":
        violations.append("tls_private_key_storage_unreviewed")
    if not tls.automated_renewal:
        violations.append("tls_automated_renewal_disabled")
    if not tls.renewal_monitoring_enabled:
        violations.append("tls_renewal_monitoring_disabled")
    if not tls.hsts_enabled:
        violations.append("hsts_disabled")

    approved = not violations
    return PublicationReviewReport(
        generated_at=checked_at.isoformat(),
        status="approved" if approved else "blocked",
        manifest_sha256=manifest_hash,
        deployment_id=manifest.deployment_id,
        approved_hostname=tls.hostname if approved else None,
        approval_expires_at=expires_at.isoformat() if approved else None,
        external_publication_approved=approved,
        real_source_collection_authorized=False,
        violations=tuple(violations),
        external_network_used=False,
    )


def _blocked_report(
    *, checked_at: datetime, manifest_hash: str, violations: tuple[str, ...]
) -> PublicationReviewReport:
    return PublicationReviewReport(
        generated_at=checked_at.isoformat(),
        status="blocked",
        manifest_sha256=manifest_hash,
        deployment_id=None,
        approved_hostname=None,
        approval_expires_at=None,
        external_publication_approved=False,
        real_source_collection_authorized=False,
        violations=violations,
        external_network_used=False,
    )


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("publication timestamps must be timezone-aware")
    return value.astimezone(UTC)


def _is_placeholder(value: str) -> bool:
    normalized = value.strip().lower()
    return normalized in _PLACEHOLDERS or normalized.endswith(".invalid")


def _production_dns_name(value: str) -> bool:
    normalized = value.strip().lower().rstrip(".")
    try:
        ipaddress.ip_address(normalized)
    except ValueError:
        pass
    else:
        return False
    return (
        normalized not in {"localhost"}
        and not normalized.endswith((".invalid", ".localhost", ".test", ".example"))
        and _DNS_NAME.fullmatch(normalized) is not None
    )


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("review input must be a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase2-report", type=Path, default=Path("var/reports/phase2_exit_review.json")
    )
    parser.add_argument(
        "--manifest", type=Path, default=Path("config/publication_deployment.template.json")
    )
    parser.add_argument(
        "--output", type=Path, default=Path("var/reports/publication_review.json")
    )
    args = parser.parse_args()
    try:
        report = review_publication(
            phase2_report=_load_object(args.phase2_report),
            manifest_payload=_load_object(args.manifest),
        )
    except (OSError, ValueError, json.JSONDecodeError):
        report = _blocked_report(
            checked_at=datetime.now(UTC),
            manifest_hash="0" * 64,
            violations=("publication_review_input_invalid",),
        )
    payload = asdict(report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    stream = sys.stdout if report.external_publication_approved else sys.stderr
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True), file=stream)
    return 0 if report.external_publication_approved else 2


if __name__ == "__main__":
    raise SystemExit(main())
