from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from pixiv_yuri.deployment.readiness import review_deployment_readiness

NOW = datetime(2026, 8, 23, 5, tzinfo=UTC)
RUNBOOK = "\n".join(
    (
        "## Startup",
        "## Shutdown",
        "## Backup",
        "## Restore",
        "## Incident rollback",
        "## Publication boundary",
    )
)


def _service(*, port: int | None = None, network: bool = False) -> dict[str, Any]:
    value: dict[str, Any] = {
        "environment": {"PYURI_ENABLE_NETWORK": str(network).lower()},
        "healthcheck": {"test": ["CMD", "true"]},
    }
    if port is not None:
        value["ports"] = [{"host_ip": "127.0.0.1", "target": port}]
    return value


def _inputs() -> dict[str, Any]:
    services = {
        "web": _service(port=3000),
        "api": _service(port=8000),
        "tls-api": _service(port=8443),
        "identity-api": _service(port=8001),
        "postgres": {"healthcheck": {"test": ["CMD", "true"]}},
        "db-migrate": _service(),
        "fixture-ingest": _service(),
        "schema-probe": {"network_mode": "none"},
    }
    services["api"]["environment"]["PYURI_DATABASE_URL"] = (
        "postgresql://pyuri:change-me-local-only@postgres/pyuri"
    )
    return {
        "compose": {"services": services, "networks": {"offline-db": {"internal": True}}},
        "api_dockerfile": "FROM python:3.12-slim\n",
        "web_dockerfile": "FROM node:22-alpine\nUSER nextjs\n",
        "phase2": {"status": "passed_private_only", "private_read_api_ready": True},
        "phase3": {
            "real_identity_proxy_deployment_reviewed": False,
            "production_certificate_trust_reviewed": False,
        },
        "phase5": {
            "status": "passed_private_fixture_only",
            "phase5_private_fixture_ready": True,
        },
        "publication": {"status": "blocked", "external_publication_approved": False},
        "publication_binding": {
            "status": "blocked",
            "violations": ["publication_artifact_not_approved"],
            "external_publication_approved": False,
            "real_source_collection_authorized": False,
            "external_network_used": False,
        },
        "production_evidence": {
            "status": "blocked",
            "identity_reviewed": False,
            "tls_reviewed": False,
            "production_deployment_reviewed": False,
            "violations": ["production_evidence_not_reviewed"],
            "external_network_used": False,
            "external_publication_approved": False,
            "real_source_collection_authorized": False,
        },
        "backup_restore": None,
        "runbook": RUNBOOK,
    }


def test_current_offline_shape_reports_explicit_deployment_blockers() -> None:
    report = review_deployment_readiness(**_inputs(), now=NOW)

    assert report.status == "offline_preparation_blocked"
    assert report.private_runtime_ready is False
    assert report.passed_control_count == 6
    assert report.control_count == 12
    assert set(report.blockers) == {
        "api_or_web_container_runs_as_root",
        "app_container_runtime_hardening_missing",
        "placeholder_database_password_configured",
        "backup_restore_drill_missing_or_invalid",
        "production_identity_or_tls_not_reviewed",
        "external_publication_not_approved",
    }
    assert report.external_publication_approved is False
    assert report.real_source_collection_authorized is False
    assert report.external_network_used is False


def test_internal_service_without_published_ports_is_safe() -> None:
    inputs = _inputs()
    del inputs["compose"]["services"]["identity-api"]["ports"]

    report = review_deployment_readiness(**inputs, now=NOW)

    assert "non_loopback_port_published" not in report.blockers


@pytest.mark.parametrize(
    "mutation,blocker",
    [
        ("public_port", "non_loopback_port_published"),
        ("external_network", "collection_network_boundary_incomplete"),
        ("missing_healthcheck", "required_healthcheck_missing"),
        ("non_internal_network", "internal_network_not_enforced"),
        ("incomplete_runbook", "operator_runbook_incomplete"),
        ("invalid_phase5", "private_phase_evidence_invalid"),
    ],
)
def test_boundary_regressions_fail_closed(mutation: str, blocker: str) -> None:
    inputs = _inputs()
    services = inputs["compose"]["services"]
    if mutation == "public_port":
        services["web"]["ports"][0]["host_ip"] = "0.0.0.0"
    elif mutation == "external_network":
        services["api"]["environment"]["PYURI_ENABLE_NETWORK"] = "true"
    elif mutation == "missing_healthcheck":
        del services["postgres"]["healthcheck"]
    elif mutation == "non_internal_network":
        inputs["compose"]["networks"]["offline-db"]["internal"] = False
    elif mutation == "incomplete_runbook":
        inputs["runbook"] = "## Startup"
    else:
        inputs["phase5"]["phase5_private_fixture_ready"] = False

    assert blocker in review_deployment_readiness(**inputs, now=NOW).blockers


def test_complete_evidence_can_satisfy_matrix_without_enabling_network() -> None:
    inputs = _inputs()
    for name in ("web", "api"):
        service = inputs["compose"]["services"][name]
        service.update(
            read_only=True,
            cap_drop=["ALL"],
            security_opt=["no-new-privileges:true"],
            tmpfs=["/tmp"],
        )
    inputs["compose"]["services"]["api"]["environment"]["PYURI_DATABASE_URL"] = (
        "postgresql://pyuri:runtime-secret@postgres/pyuri"
    )
    inputs["api_dockerfile"] = "FROM python:3.12-slim\nUSER 10001\n"
    inputs["production_evidence"] = {
        "status": "reviewed",
        "identity_reviewed": True,
        "tls_reviewed": True,
        "production_deployment_reviewed": True,
        "violations": [],
        "external_network_used": False,
        "external_publication_approved": False,
        "real_source_collection_authorized": False,
    }
    inputs["publication"] = {"status": "approved", "external_publication_approved": True}
    inputs["publication_binding"] = {
        "status": "bound",
        "violations": [],
        "external_publication_approved": False,
        "real_source_collection_authorized": False,
        "external_network_used": False,
    }
    inputs["backup_restore"] = {
        "status": "passed_offline_restore_drill",
        "isolated_restore": True,
        "backup_sha256_verified": True,
        "backup_sha256": "a" * 64,
        "backup_size_bytes": 4096,
        "schema_version_verified": True,
        "schema_version": "20260823_0009",
        "source_row_count": 9,
        "restored_row_count": 9,
        "source_table_counts": {
            "crawl_runs": 1,
            "raw_observations": 1,
            "schema_definitions": 1,
            "quarantine_records": 0,
            "catalog_authors": 1,
            "catalog_works": 1,
            "catalog_tags": 1,
            "catalog_work_tags": 1,
            "catalog_work_metric_snapshots": 2,
        },
        "restored_table_counts": {
            "crawl_runs": 1,
            "raw_observations": 1,
            "schema_definitions": 1,
            "quarantine_records": 0,
            "catalog_authors": 1,
            "catalog_works": 1,
            "catalog_tags": 1,
            "catalog_work_tags": 1,
            "catalog_work_metric_snapshots": 2,
        },
        "table_counts_match": True,
        "runtime_secret_generated": True,
        "secret_persisted": False,
        "canonical_volume_untouched": True,
        "external_network_used": False,
    }

    report = review_deployment_readiness(**inputs, now=NOW)
    assert report.status == "ready_for_accountable_private_deployment"
    assert report.private_runtime_ready is True
    assert report.blockers == ()
    assert report.external_publication_approved is False
    assert report.real_source_collection_authorized is False


def test_zero_count_backup_report_cannot_pass() -> None:
    inputs = _inputs()
    inputs["backup_restore"] = {
        "status": "passed_offline_restore_drill",
        "isolated_restore": True,
        "backup_sha256_verified": True,
        "schema_version_verified": True,
        "source_row_count": 0,
        "restored_row_count": 0,
        "external_network_used": False,
    }

    report = review_deployment_readiness(**inputs, now=NOW)

    assert "backup_restore_drill_missing_or_invalid" in report.blockers


def test_configuration_fingerprint_is_stable_and_time_must_be_aware() -> None:
    inputs = _inputs()
    first = review_deployment_readiness(**inputs, now=NOW)
    second = review_deployment_readiness(**inputs, now=NOW)
    assert first.configuration_sha256 == second.configuration_sha256

    with pytest.raises(ValueError, match="timezone"):
        review_deployment_readiness(**inputs, now=datetime(2026, 8, 23))
