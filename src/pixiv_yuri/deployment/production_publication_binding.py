"""Bind production identity/TLS evidence to one publication artifact offline."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pixiv_yuri.deployment.production_evidence import review_production_evidence

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DNS_NAME = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)
_FORBIDDEN_KEYS = frozenset(
    {
        "account_password",
        "api_key",
        "authorization",
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
        "secret",
        "session_token",
        "token",
    }
)
_ARTIFACT_KEYS = frozenset(
    {
        "version",
        "manifest",
        "review",
        "certificate_sha256",
        "production_evidence_sha256",
    }
)


@dataclass(frozen=True, slots=True)
class ProductionPublicationBindingReport:
    """A non-authorizing result for one exact evidence/publication pair."""

    generated_at: str
    status: str
    binding_sha256: str
    deployment_id: str | None
    hostname: str | None
    certificate_sha256: str | None
    production_evidence_sha256: str | None
    publication_manifest_sha256: str | None
    matched_fields: tuple[str, ...]
    violations: tuple[str, ...]
    external_publication_approved: bool
    real_source_collection_authorized: bool
    external_network_used: bool


def review_production_publication_binding(
    *,
    production_evidence: dict[str, Any],
    publication_artifact: dict[str, Any],
    now: datetime | None = None,
) -> ProductionPublicationBindingReport:
    """Check that an approved publication artifact names the reviewed evidence.

    The publication artifact is an offline envelope with ``manifest`` and ``review``
    objects plus the non-secret ``certificate_sha256`` and
    ``production_evidence_sha256`` references.  A successful binding is an evidence
    result only; it never grants publication or real-source authority.
    """

    checked_at = _aware_utc(now or datetime.now(UTC))
    violations: list[str] = []
    matched: list[str] = []

    secret_shaped = _contains_forbidden_key(production_evidence) or _contains_forbidden_key(
        publication_artifact
    )
    secret_value_shaped = _contains_secret_value(production_evidence) or _contains_secret_value(
        publication_artifact
    )
    if secret_shaped:
        violations.append("secret_shaped_field_forbidden")
    if secret_value_shaped:
        violations.append("secret_value_shape_forbidden")
    binding_input = {
        "production_evidence": production_evidence,
        "publication_artifact": publication_artifact,
    }
    binding_sha256 = "0" * 64 if secret_shaped or secret_value_shaped else _safe_hash(binding_input)

    try:
        evidence_report = review_production_evidence(production_evidence, now=checked_at)
    except (TypeError, ValueError):
        evidence_report = None
        violations.append("production_evidence_input_invalid")

    if evidence_report is None:
        evidence_hash: str | None = None
        evidence_deployment_id: str | None = None
        evidence_hostname: str | None = None
        evidence_certificate: str | None = None
    else:
        evidence_hash = evidence_report.evidence_sha256
        evidence_deployment_id = evidence_report.deployment_id
        evidence_payload_id = production_evidence.get("deployment_id")
        evidence_deployment_id = (
            evidence_payload_id
            if isinstance(evidence_payload_id, str)
            else evidence_deployment_id
        )
        tls_value = production_evidence.get("tls")
        tls = tls_value if isinstance(tls_value, dict) else {}
        evidence_hostname = _string_value(tls.get("hostname"))
        evidence_certificate = _string_value(tls.get("certificate_sha256"))
        if evidence_report.status != "reviewed":
            violations.extend(evidence_report.violations or ("production_evidence_not_reviewed",))
        if evidence_report.external_network_used:
            violations.append("production_evidence_used_external_network")
        if evidence_report.external_publication_approved:
            violations.append("production_evidence_grants_publication_authority")
        if evidence_report.real_source_collection_authorized:
            violations.append("production_evidence_grants_source_authority")

    artifact = publication_artifact
    unknown_keys = set(artifact) - _ARTIFACT_KEYS
    if unknown_keys:
        violations.append("publication_artifact_unknown_field")
    if artifact.get("version") != 1:
        violations.append("publication_artifact_version_invalid")

    manifest_value = artifact.get("manifest")
    review_value = artifact.get("review")
    manifest = manifest_value if isinstance(manifest_value, dict) else None
    review = review_value if isinstance(review_value, dict) else None
    if manifest is None or review is None:
        violations.append("publication_artifact_shape_invalid")

    manifest_id: str | None = None
    manifest_hostname: str | None = None
    manifest_hash: str | None = None
    review_manifest_hash: str | None = None
    if manifest is not None:
        manifest_id = _string_value(manifest.get("deployment_id"))
        tls_manifest_value = manifest.get("tls")
        tls_manifest = tls_manifest_value if isinstance(tls_manifest_value, dict) else {}
        manifest_hostname = _string_value(tls_manifest.get("hostname"))
        if manifest.get("status") != "approved":
            violations.append("publication_manifest_not_approved")
        manifest_hash = _safe_hash(manifest)

    review_deployment_id: str | None = None
    approved_hostname: str | None = None
    if review is not None:
        review_deployment_id = _string_value(review.get("deployment_id"))
        approved_hostname = _string_value(review.get("approved_hostname"))
        review_manifest_hash = _string_value(review.get("manifest_sha256"))
        if review.get("status") != "approved":
            violations.append("publication_artifact_not_approved")
        if review.get("external_publication_approved") is not True:
            violations.append("publication_artifact_not_approved")
        if review.get("real_source_collection_authorized") is not False:
            violations.append("publication_artifact_source_authority_forbidden")
        if review.get("external_network_used") is not False:
            violations.append("publication_artifact_external_network_forbidden")
        review_violations = review.get("violations")
        if not isinstance(review_violations, (list, tuple)) or review_violations:
            violations.append("publication_artifact_has_violations")
        if not _valid_nonzero_sha256(review_manifest_hash):
            violations.append("publication_manifest_hash_missing")
        elif manifest_hash != review_manifest_hash:
            violations.append("publication_manifest_hash_mismatch")

    publication_evidence_hash = _string_value(artifact.get("production_evidence_sha256"))
    publication_certificate = _string_value(artifact.get("certificate_sha256"))
    if not _valid_nonzero_sha256(publication_evidence_hash):
        violations.append("publication_evidence_hash_missing")
    elif evidence_hash != publication_evidence_hash:
        violations.append("production_evidence_hash_mismatch")
    else:
        matched.append("production_evidence_sha256")

    if not _valid_nonzero_sha256(publication_certificate):
        violations.append("publication_certificate_fingerprint_missing")
    elif evidence_certificate != publication_certificate:
        violations.append("certificate_fingerprint_mismatch")
    else:
        matched.append("certificate_sha256")
    manifest_certificate = (
        _string_value(tls_manifest.get("certificate_sha256")) if manifest is not None else None
    )
    if manifest_certificate is not None and manifest_certificate != publication_certificate:
        violations.append("publication_manifest_certificate_fingerprint_mismatch")

    if evidence_deployment_id and manifest_id and evidence_deployment_id == manifest_id:
        matched.append("deployment_id")
    else:
        violations.append("deployment_id_mismatch")
    if review_deployment_id and manifest_id and review_deployment_id == manifest_id:
        matched.append("publication_review_deployment_id")
    else:
        violations.append("publication_review_deployment_id_mismatch")

    normalized_evidence_hostname = _normalize_hostname(evidence_hostname)
    normalized_manifest_hostname = _normalize_hostname(manifest_hostname)
    if (
        normalized_evidence_hostname
        and normalized_evidence_hostname == normalized_manifest_hostname
    ):
        matched.append("hostname")
    else:
        violations.append("hostname_mismatch")
    if (
        approved_hostname is not None
        and _normalize_hostname(approved_hostname) != normalized_manifest_hostname
    ):
        violations.append("approved_hostname_mismatch")

    unique_violations = tuple(dict.fromkeys(violations))
    passed = evidence_report is not None and not unique_violations
    return ProductionPublicationBindingReport(
        generated_at=checked_at.isoformat(),
        status="bound" if passed else "blocked",
        binding_sha256=binding_sha256,
        deployment_id=evidence_deployment_id if passed else None,
        hostname=normalized_evidence_hostname if passed else None,
        certificate_sha256=publication_certificate if passed else None,
        production_evidence_sha256=publication_evidence_hash if passed else None,
        publication_manifest_sha256=review_manifest_hash if passed else None,
        matched_fields=tuple(matched),
        violations=unique_violations,
        external_publication_approved=False,
        real_source_collection_authorized=False,
        external_network_used=False,
    )


def binding_schema() -> dict[str, Any]:
    """Return the non-secret envelope schema used by this binding review."""

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "urn:pixiv-yuri-analytics:production-publication-binding:v1",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "version",
            "manifest",
            "review",
            "certificate_sha256",
            "production_evidence_sha256",
        ],
        "properties": {
            "version": {"const": 1},
            "manifest": {"type": "object"},
            "review": {"type": "object"},
            "certificate_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            "production_evidence_sha256": {
                "type": "string",
                "pattern": "^[0-9a-f]{64}$",
            },
        },
        "x-secret-values-forbidden": sorted(_FORBIDDEN_KEYS),
        "x-authorizes-external-publication": False,
        "x-authorizes-real-source-collection": False,
    }


def _contains_forbidden_key(value: object) -> bool:
    if isinstance(value, dict):
        return any(
            _normalize_key(str(key)) in _FORBIDDEN_KEYS
            or _contains_forbidden_key(child)
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
        or re.fullmatch(r"(?i:bearer|basic)\s+\S+", normalized)
        or re.fullmatch(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", normalized)
        or re.search(r"^[a-z][a-z0-9+.-]*://[^/@:]+:[^/@]+@", normalized, re.IGNORECASE)
    )


def _normalize_key(value: str) -> str:
    return re.sub(r"[- ]+", "_", value.strip().lower())


def _normalize_hostname(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower().rstrip(".")
    return normalized if _DNS_NAME.fullmatch(normalized) else None


def _valid_nonzero_sha256(value: object) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None and value != "0" * 64


def _string_value(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _safe_hash(value: object) -> str:
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError):
        return "0" * 64
    return hashlib.sha256(encoded).hexdigest()


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("binding timestamps must be timezone-aware")
    return value.astimezone(UTC)


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("binding input must be a JSON object")
    return value


def _write_report(path: Path, report: ProductionPublicationBindingReport) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(report), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _blocked(checked_at: datetime, violation: str) -> ProductionPublicationBindingReport:
    return ProductionPublicationBindingReport(
        generated_at=checked_at.isoformat(),
        status="blocked",
        binding_sha256="0" * 64,
        deployment_id=None,
        hostname=None,
        certificate_sha256=None,
        production_evidence_sha256=None,
        publication_manifest_sha256=None,
        matched_fields=(),
        violations=(violation,),
        external_publication_approved=False,
        real_source_collection_authorized=False,
        external_network_used=False,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    schema = subparsers.add_parser("schema")
    schema.add_argument("--output", type=Path, required=True)
    review = subparsers.add_parser("review")
    review.add_argument("--production-evidence", type=Path, required=True)
    review.add_argument("--publication-artifact", type=Path, required=True)
    review.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    if args.command == "schema":
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(binding_schema(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return 0

    try:
        evidence = _load_object(args.production_evidence)
        artifact = _load_object(args.publication_artifact)
        report = review_production_publication_binding(
            production_evidence=evidence,
            publication_artifact=artifact,
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        report = _blocked(datetime.now(UTC), "binding_input_invalid")
    _write_report(args.output, report)
    stream = sys.stdout if report.status == "bound" else sys.stderr
    print(json.dumps(asdict(report), sort_keys=True), file=stream)
    return 0 if report.status == "bound" else 2


if __name__ == "__main__":
    raise SystemExit(main())
