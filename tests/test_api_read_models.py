from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from pixiv_yuri.acquisition.parsers.registry import build_offline_fixture_registry
from pixiv_yuri.acquisition.providers.fixture import FixtureProvider
from pixiv_yuri.api.app import create_app
from pixiv_yuri.data_quality.validation import load_schema_policy
from pixiv_yuri.ingest.models import SourceRecord
from pixiv_yuri.ingest.service import ingest_fixture_provider
from pixiv_yuri.shared.database import Base

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = PROJECT_ROOT / "fixtures" / "manifest.json"
POLICY = PROJECT_ROOT / "fixtures" / "schema_policy.json"


def build_ingested_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        execution_options={"schema_translate_map": {"ingest": None}},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        ingest_fixture_provider(
            session,
            FixtureProvider(MANIFEST),
            schema_policy=load_schema_policy(POLICY),
            parser_registry=build_offline_fixture_registry(),
        )
        session.commit()
    return factory


def test_schema_summary_filters_paginates_and_omits_definition() -> None:
    factory = build_ingested_factory()
    with TestClient(create_app(lambda: None, session_factory=factory)) as client:
        first = client.get(
            "/api/v1/schema-definitions",
            params={"limit": 1, "status": "discovered"},
        )
        second = client.get(
            "/api/v1/schema-definitions",
            params={"limit": 10, "cursor": first.json()["next_cursor"]},
        )

    assert first.status_code == second.status_code == 200
    assert len(first.json()["items"]) == 1
    assert len(second.json()["items"]) == 2
    assert first.headers["cache-control"] == "private, max-age=60"
    assert first.json()["items"][0]["status"] == "discovered"
    rendered = first.text.lower()
    for forbidden in ("definition", "payload", "source_url", "metadata"):
        assert forbidden not in rendered


def test_schema_summary_rejects_invalid_cursor_and_status() -> None:
    with TestClient(
        create_app(lambda: None, session_factory=build_ingested_factory())
    ) as client:
        invalid_cursor = client.get(
            "/api/v1/schema-definitions", params={"cursor": "not-a-cursor"}
        )
        invalid_status = client.get(
            "/api/v1/schema-definitions", params={"status": "secret"}
        )

    assert invalid_cursor.status_code == invalid_status.status_code == 422
    assert invalid_cursor.json() == {"detail": "invalid_cursor"}


def test_observation_history_is_minimized_and_private_cached() -> None:
    factory = build_ingested_factory()
    with factory() as session:
        source_record_id = session.scalar(
            select(SourceRecord.id).order_by(SourceRecord.id)
        )
    assert source_record_id is not None

    with TestClient(create_app(lambda: None, session_factory=factory)) as client:
        response = client.get(
            f"/api/v1/source-records/{source_record_id}/observations"
        )
        cached = client.get(
            f"/api/v1/source-records/{source_record_id}/observations",
            headers={"If-None-Match": response.headers["etag"]},
        )

    assert response.status_code == 200
    assert response.json()["source_record_id"] == source_record_id
    assert len(response.json()["items"]) == 1
    assert response.headers["cache-control"] == "private, max-age=30"
    assert cached.status_code == 304
    rendered = response.text.lower()
    for forbidden in (
        "payload_sha256",
        "payload_object_key",
        "source_url",
        "metadata",
        "retention_until",
        "task_attempt_id",
    ):
        assert forbidden not in rendered


def test_observation_history_has_fixed_missing_and_invalid_id_errors() -> None:
    with TestClient(
        create_app(lambda: None, session_factory=build_ingested_factory())
    ) as client:
        missing = client.get("/api/v1/source-records/999/observations")
        invalid = client.get("/api/v1/source-records/0/observations")

    assert missing.status_code == 404
    assert missing.json() == {"detail": "source_record_not_found"}
    assert invalid.status_code == 422
    assert invalid.json() == {"detail": "invalid_source_record_id"}
