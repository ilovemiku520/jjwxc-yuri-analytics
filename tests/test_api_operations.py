from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from fastapi import Request
from fastapi.testclient import TestClient

from pixiv_yuri.api.app import create_app
from pixiv_yuri.api.auth import ConsumerIdentity
from pixiv_yuri.api.contract import export_openapi_contract, validate_openapi_contract
from pixiv_yuri.api.operations import (
    ApiPerformancePolicy,
    ApiRequestObservation,
    ConsumerAccessEvent,
    ConsumerRateLimitDecision,
    FixedWindowConsumerRateLimiter,
)
from pixiv_yuri.api.phase2_review import REQUIRED_API_STATUS_FIELDS, review_phase2
from tests.test_api_catalog import build_catalog_factory


class _AllowedAuthorizer:
    def authorize(self, request: Request) -> ConsumerIdentity:
        subject = request.headers.get("X-Test-Consumer", "consumer-one")
        return ConsumerIdentity(subject=subject, scopes=frozenset({"analytics:read"}))


class _ObservationCollector:
    def __init__(self) -> None:
        self.items: list[ApiRequestObservation] = []

    def observe(self, observation: ApiRequestObservation) -> None:
        self.items.append(observation)


class _AuditCollector:
    def __init__(self) -> None:
        self.items: list[ConsumerAccessEvent] = []

    def record(self, event: ConsumerAccessEvent) -> None:
        self.items.append(event)


class _SequenceClock:
    def __init__(self, *values: float) -> None:
        self._values = iter(values)

    def __call__(self) -> float:
        return next(self._values)


def test_query_budget_observation_uses_route_template_and_safe_headers() -> None:
    observer = _ObservationCollector()
    clock = _SequenceClock(10.0, 10.125)
    app = create_app(
        lambda: None,
        session_factory=build_catalog_factory(),
        request_observer=observer,
        performance_policy=ApiPerformancePolicy(
            default_budget_ms=100,
            route_budgets_ms={"/api/v1/works/{work_id}": 100},
        ),
        monotonic_clock=clock,
    )
    with TestClient(app) as client:
        response = client.get("/api/v1/works/synthetic-work-1001?ignored=private")

    assert response.status_code == 200
    assert response.headers["x-query-budget"] == "exceeded"
    assert response.headers["server-timing"] == "app;dur=125.000"
    assert observer.items == [
        ApiRequestObservation(
            request_id=response.headers["x-request-id"],
            method="GET",
            route_template="/api/v1/works/{work_id}",
            status_code=200,
            duration_ms=125.0,
            budget_ms=100,
            budget_exceeded=True,
            auth_outcome="private_boundary",
        )
    ]
    assert "synthetic-work-1001" not in str(observer.items)
    assert "ignored" not in str(observer.items)


def test_per_consumer_rate_limit_and_minimized_audit() -> None:
    auditor = _AuditCollector()
    limiter = FixedWindowConsumerRateLimiter(max_requests=2, window_seconds=60)
    clock = _SequenceClock(0.0, 0.01, 1.0, 1.01, 2.0, 2.01, 3.0, 3.01)
    app = create_app(
        lambda: None,
        session_factory=build_catalog_factory(),
        consumer_authorizer=_AllowedAuthorizer(),
        consumer_rate_limiter=limiter,
        consumer_access_auditor=auditor,
        monotonic_clock=clock,
        utc_clock=lambda: datetime(2026, 8, 23, tzinfo=UTC),
    )
    with TestClient(app) as client:
        first = client.get("/api/v1/analytics/freshness")
        second = client.get("/api/v1/analytics/freshness")
        limited = client.get("/api/v1/analytics/freshness")
        other_consumer = client.get(
            "/api/v1/analytics/freshness", headers={"X-Test-Consumer": "consumer-two"}
        )

    assert first.status_code == second.status_code == other_consumer.status_code == 200
    assert limited.status_code == 429
    assert limited.json() == {"detail": "consumer_rate_limit_exceeded"}
    assert limited.headers["retry-after"] == "58"
    assert [event.status_code for event in auditor.items] == [200, 200, 429, 200]
    assert auditor.items[2].auth_outcome == "rate_limited"
    assert all(event.route_template == "/api/v1/analytics/freshness" for event in auditor.items)
    assert all(event.consumer_key is not None for event in auditor.items)
    assert auditor.items[0].consumer_key != auditor.items[3].consumer_key
    rendered = str(auditor.items)
    assert "consumer-one" not in rendered
    assert "consumer-two" not in rendered


class _BrokenLimiter:
    def check(self, *, consumer_key: str, now: float) -> ConsumerRateLimitDecision:
        raise RuntimeError("secret backend details")


class _BrokenAuditor:
    def record(self, event: ConsumerAccessEvent) -> None:
        raise RuntimeError("secret audit details")


def test_rate_limit_backend_fails_closed_but_audit_failure_is_best_effort() -> None:
    with TestClient(
        create_app(
            lambda: None,
            consumer_authorizer=_AllowedAuthorizer(),
            consumer_rate_limiter=_BrokenLimiter(),
        )
    ) as client:
        failed_limiter = client.get("/api/v1/analytics/freshness")
    with TestClient(
        create_app(
            lambda: None,
            session_factory=build_catalog_factory(),
            consumer_access_auditor=_BrokenAuditor(),
        )
    ) as client:
        failed_audit = client.get("/api/v1/analytics/freshness")

    assert failed_limiter.status_code == 503
    assert failed_limiter.json() == {"detail": "rate_limit_service_unavailable"}
    assert "secret" not in failed_limiter.text.lower()
    assert failed_audit.status_code == 200


def test_fixed_window_limiter_validates_bounds_and_recovers_expired_subjects() -> None:
    limiter = FixedWindowConsumerRateLimiter(
        max_requests=1,
        window_seconds=10,
        max_consumers=1,
    )
    first_key = "a" * 64
    second_key = "b" * 64
    assert limiter.check(consumer_key=first_key, now=0).allowed
    assert not limiter.check(consumer_key=first_key, now=1).allowed
    assert limiter.check(consumer_key=second_key, now=11).allowed


def test_openapi_contract_export_is_canonical_and_minimized(tmp_path: Path) -> None:
    contract_path = tmp_path / "openapi-v1.json"
    report_path = tmp_path / "openapi-contract-report.json"
    generated_at = datetime(2026, 8, 23, tzinfo=UTC)
    report = export_openapi_contract(
        contract_path,
        report_path,
        generated_at=generated_at,
    )
    canonical = contract_path.read_text(encoding="utf-8").strip()
    persisted_report = json.loads(report_path.read_text(encoding="utf-8"))

    assert report.status == "passed"
    assert report.api_path_count == report.operation_count == 35
    assert report.sha256 == hashlib.sha256(canonical.encode()).hexdigest()
    assert persisted_report["sha256"] == report.sha256
    assert validate_openapi_contract(json.loads(canonical)) == (35, 35)


def test_phase2_exit_review_passes_private_boundary_and_blocks_publication(
    tmp_path: Path,
) -> None:
    api_report = {field_name: 200 for field_name in REQUIRED_API_STATUS_FIELDS}
    api_report.update(
        mutation_routes_exposed=False,
        collection_network_enabled=False,
        query_budget_headers_verified=True,
        deny_by_default_cors_verified=True,
    )
    inputs = {
        "api.json": api_report,
        "postgres.json": {
            "status": "passed",
            "migration_version": "20260824_0012",
            "catalog_read_indexes": 5,
        },
        "openapi.json": {
            "status": "passed",
            "sha256": "a" * 64,
            "api_path_count": 35,
            "operation_count": 35,
            "mutation_routes_exposed": False,
            "prohibited_fields_exposed": False,
        },
        "launch.json": {
            "active_permit_count": 0,
            "first_request_slot_count": 0,
            "external_network_used": False,
        },
        "consumer-controls.json": {
            "status": "passed",
            "backend": "postgresql",
            "concurrent_workers": 8,
            "allowed": 3,
            "denied": 5,
            "persisted_request_count": 3,
            "minimized_audit_events": 8,
            "expired_audit_rows_purged": 1,
            "forbidden_audit_columns_absent": True,
            "raw_consumer_identity_reported": False,
            "network_used": False,
        },
        "identity.json": {
            "status": "passed",
            "adapter": "trusted_hmac_proxy",
            "unsigned_status": 401,
            "valid_status": 200,
            "wrong_scope_status": 403,
            "expired_status": 401,
            "tampered_status": 401,
            "fixed_error_bodies": True,
            "raw_subject_exposed": False,
            "secret_reported": False,
            "external_publication_approved": False,
            "external_network_used": False,
        },
        "tls.json": {
            "status": "passed",
            "target": "numeric_loopback",
            "https_status": 200,
            "tls_protocol": "TLSv1.3",
            "plaintext_http_accepted": False,
            "certificate_trust_reviewed": False,
            "external_publication_approved": False,
            "external_network_used": False,
        },
    }
    for name, value in inputs.items():
        (tmp_path / name).write_text(json.dumps(value), encoding="utf-8")

    report = review_phase2(
        api_report_path=tmp_path / "api.json",
        postgres_report_path=tmp_path / "postgres.json",
        openapi_report_path=tmp_path / "openapi.json",
        launch_report_path=tmp_path / "launch.json",
        consumer_controls_report_path=tmp_path / "consumer-controls.json",
        identity_report_path=tmp_path / "identity.json",
        tls_report_path=tmp_path / "tls.json",
        generated_at=datetime(2026, 8, 23, tzinfo=UTC),
    )

    assert report.status == "passed_private_only"
    assert report.private_read_api_ready
    assert not report.external_publication_approved
    assert report.real_source_collection_count == 0
    assert report.shared_consumer_controls_verified
    assert report.trusted_proxy_adapter_verified
    assert report.loopback_tls_verified
    assert "trusted_identity_proxy_deployment_not_reviewed" in report.external_publication_blockers
    assert "shared_rate_limit_backend_not_configured" not in report.external_publication_blockers
    assert "durable_access_audit_sink_not_configured" not in report.external_publication_blockers


def test_phase2_exit_review_fails_when_operational_evidence_is_missing(
    tmp_path: Path,
) -> None:
    api_report = {field_name: 200 for field_name in REQUIRED_API_STATUS_FIELDS}
    api_report.update(
        mutation_routes_exposed=False,
        collection_network_enabled=False,
        deny_by_default_cors_verified=True,
    )
    reports = (
        ("api.json", api_report),
        (
            "postgres.json",
            {
                "status": "passed",
                "migration_version": "20260824_0012",
                "catalog_read_indexes": 5,
            },
        ),
        (
            "openapi.json",
            {
                "status": "passed",
                "sha256": "a" * 64,
                "api_path_count": 35,
                "operation_count": 35,
                "mutation_routes_exposed": False,
                "prohibited_fields_exposed": False,
            },
        ),
        (
            "launch.json",
            {
                "active_permit_count": 0,
                "first_request_slot_count": 0,
                "external_network_used": False,
            },
        ),
        (
            "consumer-controls.json",
            {
                "status": "passed",
                "backend": "postgresql",
                "concurrent_workers": 8,
                "allowed": 3,
                "denied": 5,
                "persisted_request_count": 3,
                "minimized_audit_events": 8,
                "expired_audit_rows_purged": 1,
                "forbidden_audit_columns_absent": True,
                "raw_consumer_identity_reported": False,
                "network_used": False,
            },
        ),
        (
            "identity.json",
            {
                "status": "passed",
                "adapter": "trusted_hmac_proxy",
                "unsigned_status": 401,
                "valid_status": 200,
                "wrong_scope_status": 403,
                "expired_status": 401,
                "tampered_status": 401,
                "fixed_error_bodies": True,
                "raw_subject_exposed": False,
                "secret_reported": False,
                "external_publication_approved": False,
                "external_network_used": False,
            },
        ),
        (
            "tls.json",
            {
                "status": "passed",
                "target": "numeric_loopback",
                "https_status": 200,
                "tls_protocol": "TLSv1.3",
                "plaintext_http_accepted": False,
                "certificate_trust_reviewed": False,
                "external_publication_approved": False,
                "external_network_used": False,
            },
        ),
    )
    for name, value in reports:
        (tmp_path / name).write_text(json.dumps(value), encoding="utf-8")

    report = review_phase2(
        api_report_path=tmp_path / "api.json",
        postgres_report_path=tmp_path / "postgres.json",
        openapi_report_path=tmp_path / "openapi.json",
        launch_report_path=tmp_path / "launch.json",
        consumer_controls_report_path=tmp_path / "consumer-controls.json",
        identity_report_path=tmp_path / "identity.json",
        tls_report_path=tmp_path / "tls.json",
    )

    assert report.status == "failed"
    assert report.violations == ("query_budget_headers_unverified",)
