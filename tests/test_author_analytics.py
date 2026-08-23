from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from pixiv_yuri.analytics.models import CatalogWork, CatalogWorkMetricSnapshot
from pixiv_yuri.api.app import create_app
from pixiv_yuri.ingest.models import RawObservation
from tests.test_api_catalog import build_catalog_factory


def _add_later_snapshot(
    factory: sessionmaker[Session],
    *,
    observed_at: datetime,
    views: int | None,
    bookmarks: int | None,
    likes: int | None,
) -> None:
    with factory() as session:
        work = session.scalars(select(CatalogWork).order_by(CatalogWork.id)).first()
        assert work is not None
        base_observation = session.get(RawObservation, work.latest_observation_id)
        assert base_observation is not None
        later_observation = RawObservation(
            source_record_id=base_observation.source_record_id,
            task_attempt_id=base_observation.task_attempt_id,
            observed_at=observed_at,
            status_code=base_observation.status_code,
            content_type=base_observation.content_type,
            payload_sha256="f" * 64,
            payload_object_key=f"{base_observation.payload_object_key}.later",
            payload_bytes=base_observation.payload_bytes,
            schema_fingerprint=base_observation.schema_fingerprint,
            parser_version=base_observation.parser_version,
            validation_status="valid",
            retention_until=base_observation.retention_until,
            observation_metadata={"synthetic": True, "test_revision": 2},
        )
        session.add(later_observation)
        session.flush()
        session.add(
            CatalogWorkMetricSnapshot(
                work_id=work.id,
                source_observation_id=later_observation.id,
                observed_at=observed_at,
                public_view_count=views,
                public_bookmark_count=bookmarks,
                public_like_count=likes,
            )
        )
        session.commit()


def test_author_profile_preserves_missing_metric_semantics_and_tag_order() -> None:
    with TestClient(
        create_app(lambda: None, session_factory=build_catalog_factory())
    ) as client:
        response = client.get(
            "/api/v1/analytics/authors/synthetic-author-501/profile"
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["analyzed_work_count"] == 2
    assert payload["total_page_count"] == 4
    assert payload["total_public_view_count"] is None
    assert payload["total_public_bookmark_count"] == 136
    assert payload["total_public_like_count"] == 218
    assert payload["public_bookmark_rate_basis_points"] is None
    assert payload["public_like_rate_basis_points"] is None
    assert payload["metric_coverage"] == {
        "public_view_count": 0,
        "public_bookmark_count": 2,
        "public_like_count": 2,
    }
    assert payload["top_public_tags"] == [
        {
            "tag_name": "synthetic-tag-a",
            "tag_translation": None,
            "work_count": 2,
            "work_share_basis_points": 10000,
        },
        {
            "tag_name": "synthetic-tag-b",
            "tag_translation": "Synthetic B",
            "work_count": 1,
            "work_share_basis_points": 5000,
        },
    ]
    assert response.headers["cache-control"] == "private, max-age=60"
    for forbidden in ("source_url", "observation_id", "followers", "comments", "payload"):
        assert forbidden not in response.text.lower()


def test_author_profile_rates_require_complete_view_and_numerator_coverage() -> None:
    factory = build_catalog_factory()
    with factory() as session:
        works = session.scalars(select(CatalogWork).order_by(CatalogWork.id)).all()
        works[0].public_view_count = 1000
        works[1].public_view_count = 500
        session.commit()

    with TestClient(create_app(lambda: None, session_factory=factory)) as client:
        response = client.get(
            "/api/v1/analytics/authors/synthetic-author-501/profile"
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_public_view_count"] == 1500
    assert payload["public_bookmark_rate_basis_points"] == 907
    assert payload["public_like_rate_basis_points"] == 1453


def test_author_profile_missing_and_unavailable_fail_closed() -> None:
    with TestClient(
        create_app(lambda: None, session_factory=build_catalog_factory())
    ) as client:
        missing = client.get("/api/v1/analytics/authors/missing/profile")
    with TestClient(create_app(lambda: None)) as client:
        unavailable = client.get(
            "/api/v1/analytics/authors/synthetic-author-501/profile"
        )

    assert missing.status_code == 404
    assert missing.json() == {"detail": "author_not_found"}
    assert unavailable.status_code == 503
    assert unavailable.json() == {"detail": "data_service_unavailable"}


def test_author_profile_is_get_only_in_openapi() -> None:
    schema = create_app(lambda: None).openapi()
    path = schema["paths"]["/api/v1/analytics/authors/{author_id}/profile"]

    assert set(path) == {"get"}
    rendered = str(path).lower()
    for forbidden in ("password", "cookie", "source_url", "observation_id"):
        assert forbidden not in rendered


def test_author_metric_trends_preserve_daily_metric_coverage() -> None:
    with TestClient(
        create_app(lambda: None, session_factory=build_catalog_factory())
    ) as client:
        response = client.get(
            "/api/v1/analytics/authors/synthetic-author-501/metric-trends",
            params={"date_from": "2026-08-01", "date_to": "2026-08-02"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "author_id": "synthetic-author-501",
        "date_from": "2026-08-01",
        "date_to": "2026-08-02",
        "items": [
            {
                "day": "2026-08-01",
                "observed_work_count": 1,
                "public_view_coverage_count": 0,
                "public_bookmark_coverage_count": 1,
                "public_like_coverage_count": 1,
                "total_public_view_count": None,
                "total_public_bookmark_count": 75,
                "total_public_like_count": 120,
            },
            {
                "day": "2026-08-02",
                "observed_work_count": 1,
                "public_view_coverage_count": 0,
                "public_bookmark_coverage_count": 1,
                "public_like_coverage_count": 1,
                "total_public_view_count": None,
                "total_public_bookmark_count": 61,
                "total_public_like_count": 98,
            },
        ],
    }
    assert response.headers["cache-control"] == "private, max-age=60"


def test_author_metric_trends_use_last_snapshot_per_work_and_day() -> None:
    factory = build_catalog_factory()
    _add_later_snapshot(
        factory,
        observed_at=datetime(2026, 8, 1, 12, tzinfo=UTC),
        views=1000,
        bookmarks=80,
        likes=130,
    )

    with TestClient(create_app(lambda: None, session_factory=factory)) as client:
        response = client.get(
            "/api/v1/analytics/authors/synthetic-author-501/metric-trends",
            params={"date_from": "2026-08-01", "date_to": "2026-08-01"},
        )

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["observed_work_count"] == 1
    assert item["total_public_view_count"] == 1000
    assert item["total_public_bookmark_count"] == 80
    assert item["total_public_like_count"] == 130


def test_author_metric_trend_range_and_identity_fail_closed() -> None:
    with TestClient(
        create_app(lambda: None, session_factory=build_catalog_factory())
    ) as client:
        too_wide = client.get(
            "/api/v1/analytics/authors/synthetic-author-501/metric-trends",
            params={"date_from": "2025-01-01", "date_to": "2026-08-02"},
        )
        reversed_range = client.get(
            "/api/v1/analytics/authors/synthetic-author-501/metric-trends",
            params={"date_from": "2026-08-03", "date_to": "2026-08-02"},
        )
        missing = client.get(
            "/api/v1/analytics/authors/missing/metric-trends",
            params={"date_from": "2026-08-01", "date_to": "2026-08-02"},
        )

    assert too_wide.status_code == reversed_range.status_code == 422
    assert too_wide.json() == reversed_range.json() == {"detail": "invalid_date_range"}
    assert missing.status_code == 404
    assert missing.json() == {"detail": "author_not_found"}


def test_author_metric_trends_are_get_only_and_minimized() -> None:
    schema = create_app(lambda: None).openapi()
    path = schema["paths"][
        "/api/v1/analytics/authors/{author_id}/metric-trends"
    ]

    assert set(path) == {"get"}
    rendered = str(path).lower()
    for forbidden in ("password", "cookie", "source_url", "observation_id", "payload"):
        assert forbidden not in rendered


def test_author_growth_does_not_compare_different_work_cohorts() -> None:
    with TestClient(
        create_app(lambda: None, session_factory=build_catalog_factory())
    ) as client:
        response = client.get(
            "/api/v1/analytics/authors/synthetic-author-501/growth",
            params={"date_from": "2026-08-01", "date_to": "2026-08-02"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["start_observed_work_count"] == 1
    assert payload["end_observed_work_count"] == 1
    assert payload["matched_work_count"] == 0
    assert payload["start_only_work_count"] == 1
    assert payload["end_only_work_count"] == 1
    for metric in ("public_views", "public_bookmarks", "public_likes"):
        assert payload[metric] == {
            "complete_work_count": 0,
            "start_total": None,
            "end_total": None,
            "absolute_change": None,
            "growth_basis_points": None,
        }


def test_author_growth_uses_only_complete_matched_work_metrics() -> None:
    factory = build_catalog_factory()
    _add_later_snapshot(
        factory,
        observed_at=datetime(2026, 8, 2, 12, tzinfo=UTC),
        views=1000,
        bookmarks=80,
        likes=130,
    )

    with TestClient(create_app(lambda: None, session_factory=factory)) as client:
        response = client.get(
            "/api/v1/analytics/authors/synthetic-author-501/growth",
            params={"date_from": "2026-08-01", "date_to": "2026-08-02"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["start_observed_work_count"] == 1
    assert payload["end_observed_work_count"] == 2
    assert payload["matched_work_count"] == 1
    assert payload["start_only_work_count"] == 0
    assert payload["end_only_work_count"] == 1
    assert payload["public_views"]["complete_work_count"] == 0
    assert payload["public_views"]["growth_basis_points"] is None
    assert payload["public_bookmarks"] == {
        "complete_work_count": 1,
        "start_total": 75,
        "end_total": 80,
        "absolute_change": 5,
        "growth_basis_points": 667,
    }
    assert payload["public_likes"] == {
        "complete_work_count": 1,
        "start_total": 120,
        "end_total": 130,
        "absolute_change": 10,
        "growth_basis_points": 833,
    }


def test_author_growth_range_and_identity_fail_closed() -> None:
    with TestClient(
        create_app(lambda: None, session_factory=build_catalog_factory())
    ) as client:
        same_day = client.get(
            "/api/v1/analytics/authors/synthetic-author-501/growth",
            params={"date_from": "2026-08-01", "date_to": "2026-08-01"},
        )
        too_wide = client.get(
            "/api/v1/analytics/authors/synthetic-author-501/growth",
            params={"date_from": "2025-01-01", "date_to": "2026-08-02"},
        )
        missing = client.get(
            "/api/v1/analytics/authors/missing/growth",
            params={"date_from": "2026-08-01", "date_to": "2026-08-02"},
        )

    assert same_day.status_code == too_wide.status_code == 422
    assert same_day.json() == too_wide.json() == {"detail": "invalid_date_range"}
    assert missing.status_code == 404
    assert missing.json() == {"detail": "author_not_found"}


def test_author_growth_is_get_only_and_minimized() -> None:
    schema = create_app(lambda: None).openapi()
    path = schema["paths"]["/api/v1/analytics/authors/{author_id}/growth"]

    assert set(path) == {"get"}
    rendered = str(path).lower()
    for forbidden in ("password", "cookie", "source_url", "observation_id", "payload"):
        assert forbidden not in rendered


def test_author_quality_map_uses_bounded_complete_bookmark_axis() -> None:
    with TestClient(
        create_app(lambda: None, session_factory=build_catalog_factory())
    ) as client:
        response = client.get("/api/v1/analytics/authors/quality-map")

    assert response.status_code == 200
    assert response.json() == {
        "sampled_author_count": 1,
        "sample_truncated": False,
        "work_count_threshold_x100": 200,
        "average_bookmark_threshold_x100": 6800,
        "items": [
            {
                "author_id": "synthetic-author-501",
                "author_display_name": "Synthetic Author",
                "work_count": 2,
                "bookmark_coverage_count": 2,
                "average_public_bookmark_count_x100": 6800,
                "like_coverage_count": 2,
                "total_public_like_count": 218,
                "quadrant": "core",
            }
        ],
    }
    assert response.headers["cache-control"] == "private, max-age=60"


def test_author_quality_map_is_bounded_get_only_and_minimized() -> None:
    with TestClient(
        create_app(lambda: None, session_factory=build_catalog_factory())
    ) as client:
        too_many = client.get(
            "/api/v1/analytics/authors/quality-map", params={"limit": 201}
        )
    schema = create_app(lambda: None).openapi()
    path = schema["paths"]["/api/v1/analytics/authors/quality-map"]

    assert too_many.status_code == 422
    assert set(path) == {"get"}
    rendered = str(path).lower()
    for forbidden in (
        "password",
        "cookie",
        "source_url",
        "observation_id",
        "payload",
        "comment",
        "follower",
    ):
        assert forbidden not in rendered
