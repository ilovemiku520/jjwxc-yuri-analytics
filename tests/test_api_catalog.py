from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from pixiv_yuri.acquisition.parsers.registry import build_offline_fixture_registry
from pixiv_yuri.acquisition.providers.fixture import FixtureProvider
from pixiv_yuri.analytics.projection import project_fixture_catalog
from pixiv_yuri.api.app import create_app
from pixiv_yuri.data_quality.validation import load_schema_policy
from pixiv_yuri.ingest.service import ingest_fixture_provider
from pixiv_yuri.shared.database import Base

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = PROJECT_ROOT / "fixtures" / "manifest.json"
POLICY = PROJECT_ROOT / "fixtures" / "schema_policy.json"


def build_catalog_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        execution_options={"schema_translate_map": {"ingest": None}},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        provider = FixtureProvider(MANIFEST)
        ingest_fixture_provider(
            session,
            provider,
            schema_policy=load_schema_policy(POLICY),
            parser_registry=build_offline_fixture_registry(),
        )
        project_fixture_catalog(session, provider)
        session.commit()
    return factory


def test_work_search_filters_paginates_and_minimizes_fields() -> None:
    factory = build_catalog_factory()
    with TestClient(create_app(lambda: None, session_factory=factory)) as client:
        first = client.get("/api/v1/works", params={"limit": 1})
        second = client.get(
            "/api/v1/works",
            params={"limit": 1, "cursor": first.json()["next_cursor"]},
        )
        title = client.get("/api/v1/works", params={"q": "Beta"})
        author = client.get(
            "/api/v1/works", params={"author_id": "synthetic-author-501"}
        )
        tag = client.get("/api/v1/works", params={"tag": "synthetic-tag-b"})

    assert first.status_code == second.status_code == 200
    assert first.json()["items"][0]["work_id"] == "synthetic-work-1001"
    assert second.json()["items"][0]["work_id"] == "synthetic-work-1002"
    assert [item["work_id"] for item in title.json()["items"]] == ["synthetic-work-1002"]
    assert len(author.json()["items"]) == 2
    assert [item["work_id"] for item in tag.json()["items"]] == ["synthetic-work-1001"]
    assert first.headers["cache-control"] == "private, max-age=15"
    rendered = first.text.lower()
    for forbidden in (
        "description",
        "comments",
        "followers",
        "source_url",
        "payload",
        "latest_observation_id",
    ):
        assert forbidden not in rendered


def test_tag_and_author_aggregates_use_only_reviewed_metrics() -> None:
    with TestClient(
        create_app(lambda: None, session_factory=build_catalog_factory())
    ) as client:
        tags = client.get("/api/v1/analytics/tags")
        authors = client.get("/api/v1/analytics/authors")

    assert tags.status_code == authors.status_code == 200
    assert {item["tag_name"]: item["work_count"] for item in tags.json()["items"]} == {
        "synthetic-tag-a": 2,
        "synthetic-tag-b": 1,
    }
    assert authors.json()["items"] == [
        {
            "author_id": "synthetic-author-501",
            "author_display_name": "Synthetic Author",
            "work_count": 2,
            "total_public_view_count": 0,
            "total_public_bookmark_count": 136,
            "total_public_like_count": 218,
        }
    ]
    assert tags.headers["cache-control"] == "private, max-age=60"


def test_catalog_cursor_query_and_missing_database_fail_closed() -> None:
    with TestClient(
        create_app(lambda: None, session_factory=build_catalog_factory())
    ) as client:
        invalid_cursor = client.get("/api/v1/works", params={"cursor": "forged"})
        blank_query = client.get("/api/v1/works", params={"q": "   "})
    with TestClient(create_app(lambda: None)) as client:
        unavailable = client.get("/api/v1/analytics/authors")

    assert invalid_cursor.status_code == blank_query.status_code == 422
    assert invalid_cursor.json() == {"detail": "invalid_cursor"}
    assert blank_query.json() == {"detail": "invalid_query"}
    assert unavailable.status_code == 503
    assert unavailable.json() == {"detail": "data_service_unavailable"}


def test_catalog_etag_supports_conditional_read() -> None:
    with TestClient(
        create_app(lambda: None, session_factory=build_catalog_factory())
    ) as client:
        first = client.get("/api/v1/analytics/tags")
        cached = client.get(
            "/api/v1/analytics/tags", headers={"If-None-Match": first.headers["etag"]}
        )

    assert first.status_code == 200
    assert cached.status_code == 304
    assert cached.content == b""


def test_work_metric_history_is_observation_bound_and_minimized() -> None:
    with TestClient(
        create_app(lambda: None, session_factory=build_catalog_factory())
    ) as client:
        response = client.get(
            "/api/v1/works/synthetic-work-1001/metric-history",
            params={
                "from": "2026-08-01T00:00:00Z",
                "to": "2026-08-02T00:00:00Z",
            },
        )
        missing = client.get("/api/v1/works/missing/metric-history")

    assert response.status_code == 200
    assert response.json() == {
        "work_id": "synthetic-work-1001",
        "items": [
            {
                "observed_at": "2026-08-01T00:00:00Z",
                "public_view_count": None,
                "public_bookmark_count": 75,
                "public_like_count": 120,
            }
        ],
        "next_cursor": None,
    }
    assert response.headers["cache-control"] == "private, max-age=30"
    assert missing.status_code == 404
    assert missing.json() == {"detail": "work_not_found"}
    for forbidden in ("source_observation_id", "payload", "source_url", "comments"):
        assert forbidden not in response.text.lower()


def test_daily_metric_trends_and_freshness_are_bounded() -> None:
    with TestClient(
        create_app(lambda: None, session_factory=build_catalog_factory())
    ) as client:
        trend = client.get(
            "/api/v1/analytics/metric-trends",
            params={"date_from": "2026-08-01", "date_to": "2026-08-02"},
        )
        freshness = client.get("/api/v1/analytics/freshness")

    assert trend.status_code == freshness.status_code == 200
    assert trend.json()["items"] == [
        {
            "day": "2026-08-01",
            "observed_work_count": 1,
            "total_public_view_count": 0,
            "total_public_bookmark_count": 75,
            "total_public_like_count": 120,
        },
        {
            "day": "2026-08-02",
            "observed_work_count": 1,
            "total_public_view_count": 0,
            "total_public_bookmark_count": 61,
            "total_public_like_count": 98,
        },
    ]
    assert freshness.json() == {
        "latest_observed_at": "2026-08-02T00:00:00Z",
        "author_count": 1,
        "work_count": 2,
        "tag_count": 2,
        "metric_snapshot_count": 2,
    }


def test_metric_ranges_fail_closed() -> None:
    with TestClient(
        create_app(lambda: None, session_factory=build_catalog_factory())
    ) as client:
        too_wide = client.get(
            "/api/v1/analytics/metric-trends",
            params={"date_from": "2025-01-01", "date_to": "2026-08-02"},
        )
        reversed_range = client.get(
            "/api/v1/analytics/metric-trends",
            params={"date_from": "2026-08-03", "date_to": "2026-08-02"},
        )
        naive_time = client.get(
            "/api/v1/works/synthetic-work-1001/metric-history",
            params={"from": "2026-08-01T00:00:00"},
        )

    assert too_wide.status_code == reversed_range.status_code == naive_time.status_code == 422
    assert too_wide.json() == reversed_range.json() == {"detail": "invalid_date_range"}
    assert naive_time.json() == {"detail": "timezone_required"}
