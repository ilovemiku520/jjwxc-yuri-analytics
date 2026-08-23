"""Aggregate fail-closed exit review for Fixture-only Phase 5 evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pixiv_yuri.analytics.tag_review import validate_tag_review_decision

EXPECTED_OPENAPI_PATHS = 25
EXPECTED_OPENAPI_SHA256 = "1d40ea77ba9fd98bfcd2b1f894a04e22e22c16b7b342d8fb18c3a08ea7ac733a"
EXPECTED_THRESHOLDS = [1, 2, 3, 5, 10]
MIN_DOCKER_WEB_ROUTES = 15
MAX_EVIDENCE_AGE = timedelta(days=7)
DEFERRED_CAPABILITIES = (
    "automated_semantic_classification",
    "embedding_model",
    "graph_database",
    "search_cluster",
    "background_worker",
    "real_source_collection",
    "external_publication",
)


@dataclass(frozen=True, slots=True)
class Phase5ExitReport:
    generated_at: str
    status: str
    phase: int
    estimated_completion_percent: int
    phase5_private_fixture_ready: bool
    evidence_bundle_sha256: str
    api_path_count: int
    focused_python_test_count: int
    web_unit_test_count: int
    browser_test_count: int
    docker_web_route_count: int
    manual_review_validator_verified: bool
    semantic_classification_performed: bool
    external_publication_approved: bool
    real_source_collection_authorized: bool
    real_source_collection_count: int
    external_network_used: bool
    violations: tuple[str, ...]
    deferred_capabilities: tuple[str, ...]


def review_phase5(
    *,
    core: dict[str, Any],
    web: dict[str, Any],
    manual_review: dict[str, Any],
    review_artifact: dict[str, Any],
    api_integration: dict[str, Any],
    web_integration: dict[str, Any],
    openapi: dict[str, Any],
    phase2: dict[str, Any],
    now: datetime | None = None,
) -> Phase5ExitReport:
    """Require one mutually consistent private Fixture-only evidence bundle."""
    checked_at = _aware_utc(now or datetime.now(UTC))
    reports = {
        "core": core,
        "web": web,
        "manual_review": manual_review,
        "api_integration": api_integration,
        "web_integration": web_integration,
        "openapi": openapi,
        "phase2": phase2,
    }
    bundle_inputs = {**reports, "review_artifact": review_artifact}
    violations: list[str] = []

    _check(
        core.get("status") == "passed_private_fixture_slice"
        and core.get("phase") == 5
        and core.get("capability") == "bounded_tag_associations_and_offline_sensitivity"
        and core.get("focused_test_count") == 33
        and core.get("docker_postgres_api_verified") is True
        and core.get("sample_work_limit") == 5_000
        and core.get("edge_limit") == 200
        and core.get("tags_per_work_limit") == 64
        and core.get("sensitivity_thresholds") == EXPECTED_THRESHOLDS
        and core.get("human_review_candidate_limit") == 200
        and core.get("support_basis_points_exposed") is True
        and core.get("jaccard_basis_points_exposed") is True
        and core.get("pmi_milli_bits_exposed") is True,
        "core_evidence_invalid",
        violations,
    )
    _check(
        web.get("status") == "passed_private_fixture_slice"
        and web.get("phase") == 5
        and web.get("capability") == "tag_association_and_sensitivity_web"
        and web.get("routes") == ["/tags/graph", "/tags/review"]
        and web.get("unit_test_count") == 11
        and web.get("browser_test_count") == 16
        and web.get("browser_projects") == ["desktop", "mobile"]
        and type(web.get("docker_route_count")) is int
        and web.get("docker_route_count", 0) >= MIN_DOCKER_WEB_ROUTES
        and web.get("graph_visualization_verified") is True
        and web.get("accessible_table_fallback_verified") is True
        and web.get("threshold_sensitivity_chart_verified") is True
        and web.get("human_review_queue_verified") is True
        and web.get("bounded_filter_state_verified") is True
        and web.get("serious_or_critical_accessibility_violations") == 0
        and web.get("production_build_passed") is True
        and web.get("typecheck_passed") is True
        and web.get("lint_passed") is True,
        "web_evidence_invalid",
        violations,
    )
    artifact_validation = validate_tag_review_decision(review_artifact, now=checked_at)
    _check(
        manual_review.get("status") == "verified_manual_decision"
        and manual_review.get("manual_review_verified") is True
        and manual_review.get("violations") == []
        and manual_review.get("review_id") == "fixture-review-001"
        and manual_review.get("reviewer_id") == "fixture-reviewer"
        and manual_review.get("decision") == "retain_for_followup"
        and _sha256_value(manual_review.get("artifact_sha256"))
        and _sha256_value(manual_review.get("candidate_fingerprint")),
        "manual_review_validator_evidence_invalid",
        violations,
    )
    _check(
        artifact_validation.manual_review_verified
        and artifact_validation.violations == ()
        and artifact_validation.artifact_sha256 == manual_review.get("artifact_sha256")
        and artifact_validation.candidate_fingerprint
        == manual_review.get("candidate_fingerprint")
        and artifact_validation.review_id == manual_review.get("review_id")
        and artifact_validation.reviewer_id == manual_review.get("reviewer_id")
        and artifact_validation.decision == manual_review.get("decision"),
        "manual_review_artifact_invalid",
        violations,
    )
    _check(
        core.get("synthetic_review_candidate_fingerprint")
        == artifact_validation.candidate_fingerprint,
        "manual_review_candidate_unbound",
        violations,
    )
    _check(
        api_integration.get("tag_association_status") == 200
        and api_integration.get("tag_sensitivity_status") == 200
        and api_integration.get("tag_association_edge_count") == 1
        and api_integration.get("tag_sensitivity_threshold_count") == 5
        and api_integration.get("tag_sensitivity_candidate_count") == 1
        and api_integration.get("query_budget_headers_verified") is True
        and api_integration.get("server_timing_headers_verified") is True
        and api_integration.get("deny_by_default_cors_verified") is True
        and api_integration.get("mutation_routes_exposed") is False
        and api_integration.get("collection_network_enabled") is False,
        "api_integration_evidence_invalid",
        violations,
    )
    _check(
        web_integration.get("status") == "passed"
        and type(web_integration.get("route_count")) is int
        and web_integration.get("route_count", 0) >= web.get("docker_route_count", 0)
        and web_integration.get("all_routes_status_200") is True
        and web_integration.get("fixture_data_rendered") is True
        and web_integration.get("security_headers_verified") is True
        and web_integration.get("internal_api_origin_exposed") is False
        and web_integration.get("prohibited_fields_exposed") is False
        and web_integration.get("collection_network_enabled") is False,
        "web_integration_evidence_invalid",
        violations,
    )
    _check(
        openapi.get("status") == "passed"
        and openapi.get("contract_version") == "v1"
        and openapi.get("api_path_count") == EXPECTED_OPENAPI_PATHS
        and openapi.get("operation_count") == EXPECTED_OPENAPI_PATHS
        and openapi.get("sha256") == EXPECTED_OPENAPI_SHA256
        and openapi.get("mutation_routes_exposed") is False
        and openapi.get("prohibited_fields_exposed") is False
        and core.get("api_path_count") == openapi.get("api_path_count")
        and core.get("openapi_sha256") == openapi.get("sha256")
        and phase2.get("api_path_count") == openapi.get("api_path_count")
        and phase2.get("openapi_sha256") == openapi.get("sha256"),
        "openapi_evidence_mismatch",
        violations,
    )
    _check(
        phase2.get("status") == "passed_private_only"
        and phase2.get("private_read_api_ready") is True
        and phase2.get("violations") == []
        and phase2.get("shared_consumer_controls_verified") is True,
        "private_boundary_evidence_invalid",
        violations,
    )

    for name, report in reports.items():
        try:
            generated_at = _aware_utc(datetime.fromisoformat(str(report["generated_at"])))
        except (KeyError, TypeError, ValueError):
            violations.append(f"evidence_timestamp_invalid:{name}")
            continue
        if generated_at > checked_at or checked_at - generated_at > MAX_EVIDENCE_AGE:
            violations.append(f"evidence_stale_or_future:{name}")

    _check(
        all(
            report.get("semantic_classification_performed") is False
            for report in (core, web, manual_review)
        )
        and api_integration.get("tag_association_semantic_classification") is False
        and api_integration.get("tag_sensitivity_semantic_classification") is False,
        "semantic_classification_boundary_expanded",
        violations,
    )
    _check(
        all(
            report.get("external_publication_approved") is False
            for report in (core, web, phase2)
        )
        and all(
            report.get("real_source_collection_authorized") is False
            for report in (core, web, manual_review)
        )
        and all(
            report.get("real_source_collection_count") == 0
            for report in (core, web, phase2)
        )
        and all(
            report.get("external_network_used") is False
            for report in (core, web, manual_review)
        )
        and api_integration.get("collection_network_enabled") is False
        and web_integration.get("collection_network_enabled") is False,
        "external_boundary_expanded",
        violations,
    )

    passed = not violations
    return Phase5ExitReport(
        generated_at=checked_at.isoformat(),
        status="passed_private_fixture_only" if passed else "failed",
        phase=5,
        estimated_completion_percent=100 if passed else 95,
        phase5_private_fixture_ready=passed,
        evidence_bundle_sha256=_bundle_sha256(bundle_inputs),
        api_path_count=EXPECTED_OPENAPI_PATHS,
        focused_python_test_count=33,
        web_unit_test_count=11,
        browser_test_count=16,
        docker_web_route_count=int(web_integration.get("route_count", 0)),
        manual_review_validator_verified=passed,
        semantic_classification_performed=False,
        external_publication_approved=False,
        real_source_collection_authorized=False,
        real_source_collection_count=0,
        external_network_used=False,
        violations=tuple(violations),
        deferred_capabilities=DEFERRED_CAPABILITIES,
    )


def _check(condition: bool, code: str, violations: list[str]) -> None:
    if not condition:
        violations.append(code)


def _sha256_value(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


def _bundle_sha256(reports: dict[str, dict[str, Any]]) -> str:
    encoded = json.dumps(
        reports, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Phase 5 review time must include a timezone")
    return value.astimezone(UTC)


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"review input must be an object: {path.name}")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    report_directory = Path("var/reports")
    parser.add_argument("--core", type=Path, default=report_directory / "phase5_tag_discovery.json")
    parser.add_argument("--web", type=Path, default=report_directory / "phase5_tag_web.json")
    parser.add_argument(
        "--manual-review", type=Path, default=report_directory / "phase5_tag_review.json"
    )
    parser.add_argument(
        "--review-artifact",
        type=Path,
        default=Path("config/tag_review_decision.fixture.json"),
    )
    parser.add_argument(
        "--api-integration", type=Path, default=report_directory / "api_integration.json"
    )
    parser.add_argument(
        "--web-integration", type=Path, default=report_directory / "web_integration.json"
    )
    parser.add_argument("--openapi", type=Path, default=report_directory / "openapi_contract.json")
    parser.add_argument("--phase2", type=Path, default=report_directory / "phase2_exit_review.json")
    parser.add_argument(
        "--output", type=Path, default=report_directory / "phase5_exit_review.json"
    )
    args = parser.parse_args(argv)
    try:
        report = review_phase5(
            core=_load_object(args.core),
            web=_load_object(args.web),
            manual_review=_load_object(args.manual_review),
            review_artifact=_load_object(args.review_artifact),
            api_integration=_load_object(args.api_integration),
            web_integration=_load_object(args.web_integration),
            openapi=_load_object(args.openapi),
            phase2=_load_object(args.phase2),
        )
    except (OSError, ValueError, json.JSONDecodeError):
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(asdict(report), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(asdict(report), ensure_ascii=False, sort_keys=True))
    return 0 if report.phase5_private_fixture_ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
