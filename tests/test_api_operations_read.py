from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from pixiv_yuri.api.app import create_app
from pixiv_yuri.ingest.models import QuarantineRecord, TaskAttempt
from tests.test_api_read_models import build_ingested_factory


def _factory_with_quarantine() -> sessionmaker[Session]:
    factory = build_ingested_factory()
    with factory.begin() as session:
        attempt_id = session.scalar(select(TaskAttempt.id).order_by(TaskAttempt.id))
        assert attempt_id is not None
        session.add(
            QuarantineRecord(
                raw_observation_id=None,
                task_attempt_id=attempt_id,
                entity_type="work",
                source_id="must-not-leak-source-id",
                error_code="schema_drift",
                detail="must-not-leak-free-text",
                status="open",
                first_failed_at=datetime(2026, 8, 23, tzinfo=UTC),
                last_failed_at=datetime(2026, 8, 23, tzinfo=UTC),
            )
        )
    return factory


def test_operational_runs_expose_counts_without_configuration_or_requester() -> None:
    with TestClient(
        create_app(lambda: None, session_factory=build_ingested_factory())
    ) as client:
        response = client.get("/api/v1/operations/runs", params={"status": "completed"})

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, max-age=10"
    assert response.json()["items"] == [
        {
            "id": 1,
            "run_type": "offline_fixture_ingest",
            "provider": "synthetic_fixture",
            "status": "completed",
            "task_count": 3,
            "succeeded_task_count": 3,
            "failed_task_count": 0,
            "started_at": response.json()["items"][0]["started_at"],
            "finished_at": response.json()["items"][0]["finished_at"],
            "created_at": response.json()["items"][0]["created_at"],
        }
    ]
    rendered = response.text.lower()
    for forbidden in ("config_snapshot", "requested_by", "stop_reason", "budget"):
        assert forbidden not in rendered


def test_operational_tasks_filter_and_paginate_without_targets() -> None:
    with TestClient(
        create_app(lambda: None, session_factory=build_ingested_factory())
    ) as client:
        first = client.get(
            "/api/v1/operations/tasks",
            params={"run_id": 1, "status": "succeeded", "limit": 1},
        )
        second = client.get(
            "/api/v1/operations/tasks",
            params={"run_id": 1, "status": "succeeded", "cursor": first.json()["next_cursor"]},
        )

    assert first.status_code == second.status_code == 200
    assert len(first.json()["items"]) == 1
    assert len(second.json()["items"]) == 2
    assert {item["status"] for item in second.json()["items"]} == {"succeeded"}
    rendered = first.text.lower()
    for forbidden in ("logical_target", "idempotency_key", "lease_until", "worker_id"):
        assert forbidden not in rendered


def test_quarantine_summary_omits_source_detail_and_attempt_linkage() -> None:
    with TestClient(create_app(lambda: None, session_factory=_factory_with_quarantine())) as client:
        response = client.get(
            "/api/v1/operations/quarantine",
            params={"entity_type": "work", "status": "open"},
        )

    assert response.status_code == 200
    assert response.json()["items"][0]["error_code"] == "schema_drift"
    rendered = response.text.lower()
    for forbidden in (
        "must-not-leak",
        "source_id",
        "detail",
        "resolution",
        "task_attempt_id",
        "raw_observation_id",
    ):
        assert forbidden not in rendered


def test_operations_routes_fail_closed_for_invalid_filters_or_missing_database() -> None:
    with TestClient(
        create_app(lambda: None, session_factory=build_ingested_factory())
    ) as client:
        invalid_cursor = client.get(
            "/api/v1/operations/runs", params={"cursor": "invalid"}
        )
        invalid_status = client.get(
            "/api/v1/operations/tasks", params={"status": "secret"}
        )
    with TestClient(create_app(lambda: None)) as client:
        unavailable = client.get("/api/v1/operations/quarantine")

    assert invalid_cursor.status_code == invalid_status.status_code == 422
    assert invalid_cursor.json() == {"detail": "invalid_cursor"}
    assert unavailable.status_code == 503
    assert unavailable.json() == {"detail": "data_service_unavailable"}


def test_security_status_reports_shared_controls_without_identity_material() -> None:
    app = create_app(
        lambda: None,
        session_factory=build_ingested_factory(),
        shared_consumer_controls_enabled=True,
        audit_retention_days=14,
    )
    with TestClient(app) as client:
        first = client.get("/api/v1/operations/security-status")
        second = client.get("/api/v1/operations/security-status")

    assert first.status_code == second.status_code == 200
    assert first.json() == {
        "shared_rate_limit_backend": "postgres",
        "durable_access_audit_sink": "postgres",
        "identity_adapter_configured": False,
        "external_publication_approved": False,
        "rate_limit_window_count": 0,
        "audit_event_count": 0,
        "oldest_audit_at": None,
        "latest_audit_at": None,
        "audit_retention_days": 14,
    }
    assert second.json()["audit_event_count"] == 1
    rendered = second.text.lower()
    for forbidden in ("consumer_key", "subject", "request_id", "route_template"):
        assert forbidden not in rendered


def test_shared_controls_require_database_factory() -> None:
    with pytest.raises(ValueError, match="database session factory"):
        create_app(lambda: None, shared_consumer_controls_enabled=True)
