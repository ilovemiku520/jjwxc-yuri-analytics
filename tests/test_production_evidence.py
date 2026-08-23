from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pixiv_yuri.deployment.production_evidence import (
    draft_evidence,
    evidence_schema,
    review_production_evidence,
)

NOW = datetime(2026, 8, 23, 6, tzinfo=UTC)


def _valid_evidence() -> dict[str, object]:
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


def test_draft_is_deliberately_blocked_and_non_authorizing() -> None:
    report = review_production_evidence(draft_evidence(now=NOW), now=NOW)

    assert report.status == "blocked"
    assert report.production_deployment_reviewed is False
    assert report.external_publication_approved is False
    assert report.real_source_collection_authorized is False
    assert report.external_network_used is False


def test_complete_non_secret_evidence_can_be_reviewed() -> None:
    report = review_production_evidence(_valid_evidence(), now=NOW)

    assert report.status == "reviewed"
    assert report.identity_reviewed is True
    assert report.tls_reviewed is True
    assert report.production_deployment_reviewed is True
    assert report.external_publication_approved is False
    assert report.real_source_collection_authorized is False


def test_secret_shaped_unknown_field_fails_closed() -> None:
    payload = _valid_evidence()
    payload["identity"]["hmac_secret"] = "must-not-be-accepted"  # type: ignore[index]

    report = review_production_evidence(payload, now=NOW)

    assert report.violations == ("secret_shaped_field_forbidden",)
    assert report.deployment_id is None


def test_zero_smoke_hash_and_loopback_certificate_cannot_pass() -> None:
    payload = _valid_evidence()
    payload["identity"]["production_smoke_sha256"] = "0" * 64  # type: ignore[index]
    payload["tls"]["hostname"] = "127.0.0.1"  # type: ignore[index]

    report = review_production_evidence(payload, now=NOW)

    assert "identity_production_smoke_missing" in report.violations
    assert "production_hostname_invalid" in report.violations


def test_secret_value_shape_fails_before_schema_validation() -> None:
    payload = _valid_evidence()
    payload["identity"]["product"] = "Bearer do-not-store-this"  # type: ignore[index]

    report = review_production_evidence(payload, now=NOW)

    assert report.violations == ("secret_value_shape_forbidden",)


def test_schema_forbids_unknown_fields_and_declares_no_authority() -> None:
    schema = evidence_schema()

    assert schema["additionalProperties"] is False
    assert schema["x-authorizes-external-publication"] is False
    assert schema["x-authorizes-real-source-collection"] is False
    assert "private_key" in schema["x-secret-values-forbidden"]
