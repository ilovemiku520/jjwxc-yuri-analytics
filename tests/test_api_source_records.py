from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from pixiv_yuri.api.app import create_app
from pixiv_yuri.ingest.models import SourceRecord
from pixiv_yuri.shared.database import Base

NOW = datetime(2026, 8, 23, tzinfo=UTC)


def build_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        execution_options={"schema_translate_map": {"ingest": None}},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory.begin() as session:
        session.add_all(
            SourceRecord(
                source_system="fixture",
                entity_type=entity_type,
                source_id=str(index),
                source_url=f"https://must-not-leak.test/{index}?token=secret",
                current_availability="available",
                first_seen_at=NOW + timedelta(seconds=index),
                last_seen_at=NOW + timedelta(seconds=index),
            )
            for index, entity_type in enumerate(("work", "author", "work"), start=1)
        )
    return factory


def test_keyset_pagination_is_stable_and_minimized() -> None:
    with TestClient(create_app(lambda: None, session_factory=build_factory())) as client:
        first = client.get("/api/v1/source-records", params={"limit": 2})
        second = client.get(
            "/api/v1/source-records",
            params={"limit": 2, "cursor": first.json()["next_cursor"]},
        )

    assert first.status_code == second.status_code == 200
    assert [item["id"] for item in first.json()["items"]] == [1, 2]
    assert first.json()["next_after_id"] == 2
    assert first.json()["next_cursor"] is not None
    assert [item["id"] for item in second.json()["items"]] == [3]
    assert second.json()["next_after_id"] is None
    assert second.json()["next_cursor"] is None
    rendered = first.text.lower()
    for forbidden in ("source_url", "token", "payload", "metadata", "secret"):
        assert forbidden not in rendered


def test_entity_filter_applies_before_keyset_limit() -> None:
    with TestClient(create_app(lambda: None, session_factory=build_factory())) as client:
        response = client.get(
            "/api/v1/source-records",
            params={"entity_type": "work", "limit": 100},
        )

    assert response.status_code == 200
    assert [item["source_id"] for item in response.json()["items"]] == ["1", "3"]


def test_missing_database_factory_fails_closed() -> None:
    with TestClient(create_app(lambda: None)) as client:
        response = client.get("/api/v1/source-records")

    assert response.status_code == 503
    assert response.json() == {"detail": "data_service_unavailable"}


def test_invalid_pagination_or_entity_type_is_rejected() -> None:
    with TestClient(create_app(lambda: None, session_factory=build_factory())) as client:
        too_large = client.get("/api/v1/source-records", params={"limit": 101})
        invalid_type = client.get(
            "/api/v1/source-records", params={"entity_type": "private_work"}
        )

    assert too_large.status_code == invalid_type.status_code == 422


def test_cursor_tampering_and_conflicting_legacy_cursor_are_rejected() -> None:
    with TestClient(create_app(lambda: None, session_factory=build_factory())) as client:
        first = client.get("/api/v1/source-records", params={"limit": 1})
        cursor = first.json()["next_cursor"]
        tampered = client.get(
            "/api/v1/source-records", params={"cursor": f"{cursor[:-1]}A"}
        )
        conflicting = client.get(
            "/api/v1/source-records", params={"cursor": cursor, "after_id": 1}
        )

    assert tampered.status_code == conflicting.status_code == 422
    assert tampered.json() == conflicting.json() == {"detail": "invalid_cursor"}


def test_private_etag_supports_conditional_read() -> None:
    with TestClient(create_app(lambda: None, session_factory=build_factory())) as client:
        first = client.get("/api/v1/source-records")
        cached = client.get(
            "/api/v1/source-records", headers={"If-None-Match": first.headers["etag"]}
        )

    assert first.status_code == 200
    assert first.headers["cache-control"] == "private, max-age=15"
    assert cached.status_code == 304
    assert cached.content == b""
    assert cached.headers["etag"] == first.headers["etag"]
