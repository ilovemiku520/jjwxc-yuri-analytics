from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from pixiv_yuri.api.app import create_app


def test_liveness_does_not_depend_on_database() -> None:
    def unavailable_database() -> None:
        raise RuntimeError("synthetic database failure")

    with TestClient(create_app(unavailable_database)) as client:
        response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_readiness_succeeds_when_database_probe_succeeds() -> None:
    with TestClient(create_app(lambda: None)) as client:
        response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": "ready"}


def test_readiness_fails_closed_without_database_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PYURI_DATABASE_URL", raising=False)

    with TestClient(create_app()) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "database": "not_configured"}


def test_readiness_hides_database_error_details() -> None:
    def unavailable_database() -> None:
        raise RuntimeError("secret connection details")

    with TestClient(create_app(unavailable_database)) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "database": "unavailable"}
    assert "secret" not in response.text


def test_request_id_is_generated_when_missing() -> None:
    with TestClient(create_app(lambda: None)) as client:
        response = client.get("/health/live")

    request_id = response.headers["x-request-id"]
    assert len(request_id) == 32
    assert request_id.isalnum()


def test_valid_request_id_is_preserved() -> None:
    with TestClient(create_app(lambda: None)) as client:
        response = client.get("/health/live", headers={"X-Request-ID": "phase0-demo_1"})

    assert response.headers["x-request-id"] == "phase0-demo_1"


def test_invalid_request_id_is_replaced() -> None:
    with TestClient(create_app(lambda: None)) as client:
        response = client.get("/health/live", headers={"X-Request-ID": "bad id\nvalue"})

    assert response.headers["x-request-id"] != "bad id\nvalue"
    assert len(response.headers["x-request-id"]) == 32


def test_security_headers_and_health_no_store_are_enforced() -> None:
    with TestClient(create_app(lambda: None)) as client:
        response = client.get("/health/live")

    assert response.headers["cache-control"] == "no-store"


def test_cross_origin_requests_are_denied_by_default() -> None:
    with TestClient(create_app(lambda: None)) as client:
        response = client.get(
            "/health/live", headers={"Origin": "https://untrusted.example"}
        )
        preflight = client.options(
            "/api/v1/works",
            headers={
                "Origin": "https://untrusted.example",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers
    assert preflight.status_code == 405
    assert "access-control-allow-origin" not in preflight.headers
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["content-security-policy"] == (
        "default-src 'none'; frame-ancestors 'none'"
    )
