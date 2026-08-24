from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from pixiv_yuri.api.app import create_app
from pixiv_yuri.jjwxc.author_v_jobs import (
    author_v_job_status,
    enqueue_author_v_job,
    process_next_author_v_job,
    retry_author_v_job,
)
from pixiv_yuri.shared.database import Base


def _factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        execution_options={"schema_translate_map": {"ingest": None}},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(engine)


def _payload() -> dict[str, object]:
    return {
        "source_format": "pyuri_jjwxc_author_v_clicks_json",
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "authorization_attestation": True,
        "records": [{"novel_id": "999999999999", "chapter_id": 1, "click_count": 1}],
    }


def test_durable_job_fails_closed_and_can_be_explicitly_retried() -> None:
    factory = _factory()
    with factory() as session:
        queued = enqueue_author_v_job(session, payload=_payload())
    with factory() as session:
        assert process_next_author_v_job(session, worker_id="test-worker") is True
    with factory() as session:
        failed = author_v_job_status(session, job_id=queued.job_id)
        assert failed.status == "failed"
        assert failed.last_error_code == "novel_not_collected"
        assert failed.novel_ids == ("999999999999",)
        retried = retry_author_v_job(session, job_id=queued.job_id)
        assert retried.status == "pending"
        assert retried.attempt_count == 1


def test_internal_job_api_persists_payload_and_reports_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = _factory()
    monkeypatch.setenv("PYURI_COHORT_IMPORT_TOKEN", "internal-test-token")
    app = create_app(lambda: None, session_factory=factory)
    headers = {"X-Pyuri-Internal-Operation": "internal-test-token"}
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/jjwxc/analytics/author-v-clicks/jobs",
            headers=headers,
            json=_payload(),
        )
        status = client.get(
            f"/api/v1/jjwxc/analytics/author-v-clicks/jobs/{created.json()['job_id']}",
            headers=headers,
        )
    assert created.status_code == 200
    assert created.json()["status"] == "pending"
    assert status.status_code == 200
    assert status.json()["record_count"] == 1
    assert status.json()["novel_ids"] == ["999999999999"]
