from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from pixiv_yuri.api.app import create_app
from pixiv_yuri.jjwxc.cohort_import import (
    cohort_collection_status,
    queue_cohort_novels,
)
from pixiv_yuri.jjwxc.demo import load_demo_catalog
from pixiv_yuri.jjwxc.persistence import JjwxcDiscoveryRecord
from pixiv_yuri.jjwxc.snapshot_store import store_novel_snapshot
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


def test_queue_preserves_ready_rows_and_prioritizes_missing_ids() -> None:
    factory = _factory()
    ready_novel = (
        load_demo_catalog().novels[0].model_copy(update={"source_mode": "public_candidate"})
    )
    with factory() as session:
        store_novel_snapshot(session, ready_novel)
        session.commit()
        items = queue_cohort_novels(
            session,
            novel_ids=(ready_novel.novel_id, "10806685"),
            now=datetime(2026, 8, 24, tzinfo=UTC),
        )

    assert [(item.novel_id, item.status) for item in items] == [
        (ready_novel.novel_id, "ready"),
        ("10806685", "queued"),
    ]
    with factory() as session:
        queued = session.scalar(
            select(JjwxcDiscoveryRecord).where(JjwxcDiscoveryRecord.novel_id == "10806685")
        )
        assert queued is not None
        assert queued.source_kind == "uploaded_cohort"
        assert queued.priority == 120


def test_status_keeps_failed_collection_out_of_ready_cohort() -> None:
    factory = _factory()
    with factory() as session:
        queue_cohort_novels(
            session,
            novel_ids=("10806685",),
            now=datetime(2026, 8, 24, tzinfo=UTC),
        )
        record = session.scalar(select(JjwxcDiscoveryRecord))
        assert record is not None
        record.status = "failed"
        record.last_error_code = "novel_outside_yuri_scope"
        session.commit()
        status = cohort_collection_status(session, novel_ids=("10806685",))

    assert status[0].status == "failed"
    assert status[0].error_code == "novel_outside_yuri_scope"


def test_api_queues_and_checks_a_bounded_cohort_without_source_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = _factory()
    monkeypatch.setenv("PYURI_COHORT_IMPORT_TOKEN", "test-internal-token")
    app = create_app(lambda: None, session_factory=factory)
    headers = {"X-Pyuri-Internal-Operation": "test-internal-token"}
    with TestClient(app) as client:
        queued = client.post(
            "/api/v1/jjwxc/analytics/cohorts/import",
            json={"mode": "queue", "novel_ids": ["10806685", "148682428"]},
            headers=headers,
        )
        status = client.post(
            "/api/v1/jjwxc/analytics/cohorts/import",
            json={"mode": "status", "novel_ids": ["10806685", "148682428"]},
            headers=headers,
        )
        invalid = client.post(
            "/api/v1/jjwxc/analytics/cohorts/import",
            json={"mode": "queue", "novel_ids": ["1.2E8"]},
            headers=headers,
        )
        forbidden = client.post(
            "/api/v1/jjwxc/analytics/cohorts/import",
            json={"mode": "status", "novel_ids": ["10806685"]},
        )

    assert queued.status_code == 200
    assert queued.json()["minimum_analysis_sample"] == 30
    assert {item["status"] for item in queued.json()["items"]} == {"queued"}
    assert status.status_code == 200
    assert status.json()["ready_count"] == 0
    assert invalid.status_code == 422
    assert forbidden.status_code == 403
