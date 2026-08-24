"""Executable private-boundary exit review for the Phase 2 read-only API."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pixiv_yuri.api.contract import EXPECTED_API_PATH_COUNT

EXPECTED_MIGRATION = "20260824_0014"
REQUIRED_API_STATUS_FIELDS = (
    "source_records_status",
    "schema_definitions_status",
    "observations_status",
    "works_status",
    "tag_aggregates_status",
    "author_aggregates_status",
    "metric_history_status",
    "metric_trends_status",
    "freshness_status",
    "work_detail_status",
    "author_detail_status",
    "tag_detail_status",
    "work_ranking_status",
    "author_ranking_status",
    "author_average_ranking_status",
    "author_quality_map_status",
    "author_influence_status",
    "tag_association_status",
    "tag_sensitivity_status",
)


@dataclass(frozen=True, slots=True)
class Phase2ExitReport:
    """Machine-readable result that separates private readiness from publication."""

    generated_at: str
    status: str
    private_read_api_ready: bool
    external_publication_approved: bool
    openapi_sha256: str | None
    api_path_count: int
    migration_version: str | None
    shared_consumer_controls_verified: bool
    trusted_proxy_adapter_verified: bool
    loopback_tls_verified: bool
    real_source_collection_count: int
    violations: tuple[str, ...]
    external_publication_blockers: tuple[str, ...]


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid review input: {path.name}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"review input must be an object: {path.name}")
    return value


def review_phase2(
    *,
    api_report_path: Path,
    postgres_report_path: Path,
    openapi_report_path: Path,
    launch_report_path: Path,
    consumer_controls_report_path: Path,
    identity_report_path: Path,
    tls_report_path: Path,
    generated_at: datetime | None = None,
) -> Phase2ExitReport:
    """Validate current local evidence without opening any source or consumer network."""
    api_report = _load_object(api_report_path)
    postgres_report = _load_object(postgres_report_path)
    openapi_report = _load_object(openapi_report_path)
    launch_report = _load_object(launch_report_path)
    consumer_controls_report = _load_object(consumer_controls_report_path)
    identity_report = _load_object(identity_report_path)
    tls_report = _load_object(tls_report_path)
    violations: list[str] = []

    for field_name in REQUIRED_API_STATUS_FIELDS:
        if api_report.get(field_name) != 200:
            violations.append(f"api_status_invalid:{field_name}")
    if api_report.get("mutation_routes_exposed") is not False:
        violations.append("mutation_route_exposed")
    if api_report.get("collection_network_enabled") is not False:
        violations.append("collection_network_enabled")
    if api_report.get("query_budget_headers_verified") is not True:
        violations.append("query_budget_headers_unverified")
    if api_report.get("deny_by_default_cors_verified") is not True:
        violations.append("deny_by_default_cors_unverified")

    migration_version = postgres_report.get("migration_version")
    if postgres_report.get("status") != "passed":
        violations.append("postgres_integration_not_passed")
    if migration_version != EXPECTED_MIGRATION:
        violations.append("migration_version_mismatch")
    if postgres_report.get("catalog_read_indexes") != 5:
        violations.append("catalog_read_indexes_missing")

    if openapi_report.get("status") != "passed":
        violations.append("openapi_contract_not_passed")
    if openapi_report.get("api_path_count") != EXPECTED_API_PATH_COUNT:
        violations.append("openapi_path_count_mismatch")
    if openapi_report.get("operation_count") != EXPECTED_API_PATH_COUNT:
        violations.append("openapi_operation_count_mismatch")
    if openapi_report.get("mutation_routes_exposed") is not False:
        violations.append("openapi_mutation_route_exposed")
    if openapi_report.get("prohibited_fields_exposed") is not False:
        violations.append("openapi_prohibited_field_exposed")

    active_permits = launch_report.get("active_permit_count")
    first_slots = launch_report.get("first_request_slot_count")
    external_network_used = launch_report.get("external_network_used")
    if active_permits != 0 or first_slots != 0:
        violations.append("source_request_state_not_zero")
    if external_network_used is not False:
        violations.append("external_network_used")

    consumer_controls_verified = (
        consumer_controls_report.get("status") == "passed"
        and consumer_controls_report.get("backend") == "postgresql"
        and consumer_controls_report.get("concurrent_workers") == 8
        and consumer_controls_report.get("allowed") == 3
        and consumer_controls_report.get("denied") == 5
        and consumer_controls_report.get("persisted_request_count") == 3
        and consumer_controls_report.get("minimized_audit_events") == 8
        and consumer_controls_report.get("expired_audit_rows_purged") == 1
        and consumer_controls_report.get("forbidden_audit_columns_absent") is True
        and consumer_controls_report.get("raw_consumer_identity_reported") is False
        and consumer_controls_report.get("network_used") is False
    )
    if not consumer_controls_verified:
        violations.append("consumer_controls_not_verified")

    identity_verified = (
        identity_report.get("status") == "passed"
        and identity_report.get("adapter") == "trusted_hmac_proxy"
        and identity_report.get("unsigned_status") == 401
        and identity_report.get("valid_status") == 200
        and identity_report.get("wrong_scope_status") == 403
        and identity_report.get("expired_status") == 401
        and identity_report.get("tampered_status") == 401
        and identity_report.get("fixed_error_bodies") is True
        and identity_report.get("raw_subject_exposed") is False
        and identity_report.get("secret_reported") is False
        and identity_report.get("external_publication_approved") is False
        and identity_report.get("external_network_used") is False
    )
    if not identity_verified:
        violations.append("trusted_proxy_adapter_not_verified")

    loopback_tls_verified = (
        tls_report.get("status") == "passed"
        and tls_report.get("target") == "numeric_loopback"
        and tls_report.get("https_status") == 200
        and tls_report.get("tls_protocol") in {"TLSv1.2", "TLSv1.3"}
        and tls_report.get("plaintext_http_accepted") is False
        and tls_report.get("certificate_trust_reviewed") is False
        and tls_report.get("external_publication_approved") is False
        and tls_report.get("external_network_used") is False
    )
    if not loopback_tls_verified:
        violations.append("loopback_tls_not_verified")

    publication_blockers = (
        "trusted_identity_proxy_deployment_not_reviewed",
        "production_tls_certificate_trust_not_reviewed",
    )

    passed = not violations
    return Phase2ExitReport(
        generated_at=(generated_at or datetime.now(UTC)).isoformat(),
        status="passed_private_only" if passed else "failed",
        private_read_api_ready=passed,
        external_publication_approved=False,
        openapi_sha256=(
            str(openapi_report["sha256"]) if isinstance(openapi_report.get("sha256"), str) else None
        ),
        api_path_count=(
            int(openapi_report["api_path_count"])
            if isinstance(openapi_report.get("api_path_count"), int)
            else 0
        ),
        migration_version=str(migration_version) if migration_version is not None else None,
        shared_consumer_controls_verified=consumer_controls_verified,
        trusted_proxy_adapter_verified=identity_verified,
        loopback_tls_verified=loopback_tls_verified,
        real_source_collection_count=0,
        violations=tuple(violations),
        external_publication_blockers=publication_blockers,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-report", type=Path, default=Path("var/reports/api_integration.json"))
    parser.add_argument(
        "--postgres-report",
        type=Path,
        default=Path("var/reports/postgres_safety_integration.json"),
    )
    parser.add_argument(
        "--openapi-report", type=Path, default=Path("var/reports/openapi_contract.json")
    )
    parser.add_argument(
        "--launch-report", type=Path, default=Path("var/reports/launch_review.json")
    )
    parser.add_argument(
        "--consumer-controls-report",
        type=Path,
        default=Path("var/reports/consumer_controls_integration.json"),
    )
    parser.add_argument(
        "--identity-report",
        type=Path,
        default=Path("var/reports/identity_integration.json"),
    )
    parser.add_argument("--tls-report", type=Path, default=Path("var/reports/tls_integration.json"))
    parser.add_argument("--output", type=Path, default=Path("var/reports/phase2_exit_review.json"))
    args = parser.parse_args()
    report = review_phase2(
        api_report_path=args.api_report,
        postgres_report_path=args.postgres_report,
        openapi_report_path=args.openapi_report,
        launch_report_path=args.launch_report,
        consumer_controls_report_path=args.consumer_controls_report,
        identity_report_path=args.identity_report,
        tls_report_path=args.tls_report,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        f"{json.dumps(asdict(report), ensure_ascii=False, indent=2, sort_keys=True)}\n",
        encoding="utf-8",
    )
    print(json.dumps(asdict(report), ensure_ascii=False, sort_keys=True))
    if not report.private_read_api_ready:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
