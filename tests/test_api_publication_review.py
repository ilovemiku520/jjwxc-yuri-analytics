from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from pixiv_yuri.api.publication_review import review_publication

NOW = datetime(2026, 8, 23, tzinfo=UTC)


def _phase2() -> dict[str, Any]:
    return {
        "status": "passed_private_only",
        "private_read_api_ready": True,
        "trusted_proxy_adapter_verified": True,
        "loopback_tls_verified": True,
        "shared_consumer_controls_verified": True,
        "real_source_collection_count": 0,
        "external_publication_approved": False,
    }


def _manifest() -> dict[str, Any]:
    return {
        "version": 1,
        "status": "approved",
        "deployment_id": "production-api-1",
        "accountable_owner": "service-owner@organization.org",
        "approver": "security-approver@organization.org",
        "reviewed_at": (NOW - timedelta(minutes=1)).isoformat(),
        "expires_at": (NOW + timedelta(days=30)).isoformat(),
        "identity_proxy": {
            "adapter": "trusted_hmac_proxy",
            "product": "Reviewed Identity Gateway",
            "deployment_reference": "IDP-REVIEW-2026-001",
            "proxy_id": "production-edge",
            "direct_api_access_blocked": True,
            "secret_delivery": "runtime_read_only_file",
            "secret_rotation_days": 30,
            "assertion_max_age_seconds": 30,
            "health_monitoring_enabled": True,
        },
        "tls": {
            "hostname": "analytics.organization.org",
            "certificate_authority": "Organization Approved Public CA",
            "certificate_not_after": (NOW + timedelta(days=60)).isoformat(),
            "minimum_tls_version": "TLSv1.2",
            "private_key_storage": "runtime_secret",
            "automated_renewal": True,
            "renewal_monitoring_enabled": True,
            "hsts_enabled": True,
        },
    }


def test_publication_review_can_approve_complete_deployment_without_source_authority() -> None:
    report = review_publication(phase2_report=_phase2(), manifest_payload=_manifest(), now=NOW)

    assert report.status == "approved"
    assert report.external_publication_approved
    assert not report.real_source_collection_authorized
    assert report.approved_hostname == "analytics.organization.org"
    assert report.violations == ()


def test_publication_review_blocks_draft_and_unresolved_controls() -> None:
    manifest = _manifest()
    manifest["status"] = "draft"
    manifest["accountable_owner"] = "change-me"
    manifest["identity_proxy"]["direct_api_access_blocked"] = False
    manifest["tls"]["hostname"] = "api.example.invalid"

    report = review_publication(phase2_report=_phase2(), manifest_payload=manifest, now=NOW)

    assert report.status == "blocked"
    assert not report.external_publication_approved
    assert "deployment_manifest_not_approved" in report.violations
    assert "accountable_owner_unresolved" in report.violations
    assert "direct_api_access_not_blocked" in report.violations
    assert "production_hostname_invalid" in report.violations


def test_publication_review_blocks_stale_or_overlong_approval() -> None:
    manifest = _manifest()
    manifest["reviewed_at"] = (NOW - timedelta(days=100)).isoformat()
    manifest["expires_at"] = (NOW + timedelta(days=1)).isoformat()

    report = review_publication(phase2_report=_phase2(), manifest_payload=manifest, now=NOW)

    assert "deployment_approval_too_long" in report.violations


def test_publication_review_blocks_unready_private_boundary_and_source_state() -> None:
    phase2 = _phase2()
    phase2["trusted_proxy_adapter_verified"] = False
    phase2["real_source_collection_count"] = 1

    report = review_publication(phase2_report=phase2, manifest_payload=_manifest(), now=NOW)

    assert "trusted_proxy_adapter_not_verified" in report.violations
    assert "real_source_collection_not_zero" in report.violations


def test_publication_review_rejects_secret_shaped_extra_fields() -> None:
    manifest = _manifest()
    manifest["identity_proxy"]["hmac_secret"] = "must-not-be-accepted"

    report = review_publication(phase2_report=_phase2(), manifest_payload=manifest, now=NOW)

    assert report.violations == ("deployment_manifest_invalid",)
    assert not report.external_publication_approved


def test_publication_review_rejects_naive_timestamps() -> None:
    manifest = _manifest()
    manifest["reviewed_at"] = "2026-08-23T00:00:00"

    report = review_publication(phase2_report=_phase2(), manifest_payload=manifest, now=NOW)

    assert report.violations == ("deployment_manifest_invalid",)
