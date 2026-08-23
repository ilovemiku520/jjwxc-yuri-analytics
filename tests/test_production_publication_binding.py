from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from pixiv_yuri.deployment.production_evidence import draft_evidence, review_production_evidence
from pixiv_yuri.deployment.production_publication_binding import (
    binding_schema,
    review_production_publication_binding,
)

NOW = datetime(2026, 8, 23, 7, tzinfo=UTC)


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _valid_evidence() -> dict[str, Any]:
    payload = draft_evidence(now=NOW)
    payload.update(
        status="reviewed",
        deployment_id="prod-edge-1",
        accountable_owner="owner-1",
        reviewer="reviewer-1",
        reviewed_at=(NOW - timedelta(hours=1)).isoformat(),
        expires_at=(NOW + timedelta(days=30)).isoformat(),
    )
    payload["identity"] = {
        "adapter": "trusted_hmac_proxy",
        "product": "reviewed-edge",
        "deployment_reference": "prod-edge-ref-1",
        "proxy_id": "prod-edge",
        "direct_api_access_blocked": True,
        "secret_delivery": "runtime_read_only_file",
        "secret_rotation_days": 30,
        "assertion_max_age_seconds": 30,
        "health_monitoring_enabled": True,
        "production_smoke_sha256": "a" * 64,
    }
    payload["tls"] = {
        "hostname": "analytics.example.org",
        "certificate_authority": "reviewed-ca",
        "certificate_sha256": "b" * 64,
        "certificate_not_after": (NOW + timedelta(days=60)).isoformat(),
        "minimum_tls_version": "TLSv1.3",
        "private_key_storage": "runtime_secret",
        "automated_renewal": True,
        "renewal_monitoring_enabled": True,
        "hsts_enabled": True,
        "production_smoke_sha256": "c" * 64,
    }
    return payload


def _publication_artifact(evidence: dict[str, Any]) -> dict[str, Any]:
    manifest = {
        "version": 1,
        "status": "approved",
        "deployment_id": evidence["deployment_id"],
        "accountable_owner": "owner-1",
        "approver": "reviewer-1",
        "reviewed_at": (NOW - timedelta(minutes=10)).isoformat(),
        "expires_at": (NOW + timedelta(days=20)).isoformat(),
        "identity_proxy": {
            "adapter": "trusted_hmac_proxy",
            "product": "reviewed-edge",
            "deployment_reference": "prod-edge-ref-1",
            "proxy_id": "prod-edge",
            "direct_api_access_blocked": True,
            "secret_delivery": "runtime_read_only_file",
            "secret_rotation_days": 30,
            "assertion_max_age_seconds": 30,
            "health_monitoring_enabled": True,
        },
        "tls": {
            "hostname": evidence["tls"]["hostname"],
            "certificate_authority": "reviewed-ca",
            "certificate_not_after": (NOW + timedelta(days=60)).isoformat(),
            "minimum_tls_version": "TLSv1.3",
            "private_key_storage": "runtime_secret",
            "automated_renewal": True,
            "renewal_monitoring_enabled": True,
            "hsts_enabled": True,
        },
    }
    evidence_hash = review_production_evidence(evidence, now=NOW).evidence_sha256
    review = {
        "status": "approved",
        "deployment_id": manifest["deployment_id"],
        "approved_hostname": manifest["tls"]["hostname"],
        "approval_expires_at": manifest["expires_at"],
        "manifest_sha256": _hash(manifest),
        "violations": [],
        "external_publication_approved": True,
        "real_source_collection_authorized": False,
        "external_network_used": False,
    }
    return {
        "version": 1,
        "manifest": manifest,
        "review": review,
        "certificate_sha256": evidence["tls"]["certificate_sha256"],
        "production_evidence_sha256": evidence_hash,
    }


def test_matching_non_secret_artifacts_bind_without_authority() -> None:
    evidence = _valid_evidence()
    report = review_production_publication_binding(
        production_evidence=evidence,
        publication_artifact=_publication_artifact(evidence),
        now=NOW,
    )

    assert report.status == "bound"
    assert report.deployment_id == "prod-edge-1"
    assert report.hostname == "analytics.example.org"
    assert set(report.matched_fields) == {
        "deployment_id",
        "publication_review_deployment_id",
        "hostname",
        "certificate_sha256",
        "production_evidence_sha256",
    }
    assert report.violations == ()
    assert report.external_publication_approved is False
    assert report.real_source_collection_authorized is False
    assert report.external_network_used is False


def test_draft_evidence_remains_fail_closed() -> None:
    evidence = draft_evidence(now=NOW)
    valid = _valid_evidence()
    report = review_production_publication_binding(
        production_evidence=evidence,
        publication_artifact=_publication_artifact(valid),
        now=NOW,
    )

    assert report.status == "blocked"
    assert "production_evidence_not_reviewed" in report.violations
    assert report.external_publication_approved is False
    assert report.real_source_collection_authorized is False


@pytest.mark.parametrize(
    ("mutation", "violation"),
    [
        ("deployment_id", "deployment_id_mismatch"),
        ("hostname", "hostname_mismatch"),
        ("certificate", "certificate_fingerprint_mismatch"),
        ("evidence_hash", "production_evidence_hash_mismatch"),
    ],
)
def test_identity_and_tls_cross_fields_fail_closed(mutation: str, violation: str) -> None:
    evidence = _valid_evidence()
    artifact = _publication_artifact(evidence)
    if mutation == "deployment_id":
        artifact["manifest"]["deployment_id"] = "other-edge"
    elif mutation == "hostname":
        artifact["manifest"]["tls"]["hostname"] = "other.example.org"
    elif mutation == "certificate":
        artifact["certificate_sha256"] = "d" * 64
    else:
        artifact["production_evidence_sha256"] = "e" * 64

    report = review_production_publication_binding(
        production_evidence=evidence,
        publication_artifact=artifact,
        now=NOW,
    )

    assert report.status == "blocked"
    assert violation in report.violations
    assert report.external_publication_approved is False


def test_publication_manifest_hash_and_review_state_are_bound() -> None:
    evidence = _valid_evidence()
    artifact = _publication_artifact(evidence)
    artifact["review"]["manifest_sha256"] = "f" * 64
    artifact["review"]["status"] = "blocked"
    artifact["review"]["external_publication_approved"] = False
    artifact["review"]["violations"] = ["draft"]

    report = review_production_publication_binding(
        production_evidence=evidence,
        publication_artifact=artifact,
        now=NOW,
    )

    assert report.status == "blocked"
    assert "publication_manifest_hash_mismatch" in report.violations
    assert "publication_artifact_has_violations" in report.violations
    assert "publication_artifact_not_approved" in report.violations


def test_secret_shaped_fields_and_values_are_rejected() -> None:
    evidence = _valid_evidence()
    artifact = _publication_artifact(evidence)
    artifact["review"]["hmac_secret"] = "must-not-be-stored"

    report = review_production_publication_binding(
        production_evidence=evidence,
        publication_artifact=artifact,
        now=NOW,
    )
    assert report.violations == ("secret_shaped_field_forbidden",)

    clean_artifact = _publication_artifact(evidence)
    clean_artifact["manifest"]["accountable_owner"] = "Bearer do-not-store"
    report = review_production_publication_binding(
        production_evidence=evidence,
        publication_artifact=clean_artifact,
        now=NOW,
    )
    assert "secret_value_shape_forbidden" in report.violations


def test_unknown_artifact_fields_and_source_authority_are_blocked() -> None:
    evidence = _valid_evidence()
    artifact = _publication_artifact(evidence)
    artifact["unexpected"] = True
    artifact["review"]["real_source_collection_authorized"] = True

    report = review_production_publication_binding(
        production_evidence=evidence,
        publication_artifact=artifact,
        now=NOW,
    )

    assert report.status == "blocked"
    assert "publication_artifact_unknown_field" in report.violations
    assert "publication_artifact_source_authority_forbidden" in report.violations


def test_schema_is_non_authorizing_and_fail_closed_by_shape() -> None:
    schema = binding_schema()

    assert schema["$id"].endswith(":v1")
    assert schema["additionalProperties"] is False
    assert schema["x-authorizes-external-publication"] is False
    assert schema["x-authorizes-real-source-collection"] is False
    assert "production_evidence_sha256" in schema["required"]


def test_hostname_case_and_trailing_dot_are_canonicalized() -> None:
    evidence = _valid_evidence()
    evidence["tls"]["hostname"] = "ANALYTICS.EXAMPLE.ORG."
    artifact = _publication_artifact(evidence)
    artifact["manifest"]["tls"]["hostname"] = "analytics.example.org"
    artifact["review"]["approved_hostname"] = "analytics.example.org"
    artifact["review"]["manifest_sha256"] = _hash(artifact["manifest"])

    report = review_production_publication_binding(
        production_evidence=evidence,
        publication_artifact=artifact,
        now=NOW,
    )

    assert report.status == "bound"
    assert report.hostname == "analytics.example.org"
