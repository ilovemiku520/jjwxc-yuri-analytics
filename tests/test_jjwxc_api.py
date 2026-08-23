from __future__ import annotations

from fastapi.testclient import TestClient

from pixiv_yuri.api.app import create_app


def test_jjwxc_overview_and_trends_are_fixture_only() -> None:
    with TestClient(create_app(lambda: None)) as client:
        overview = client.get("/api/v1/jjwxc/overview")
        trends = client.get("/api/v1/jjwxc/trends")

    assert overview.status_code == 200
    assert overview.json()["data_mode"] == "synthetic_fixture"
    assert overview.json()["novel_count"] == 8
    assert overview.json()["author_count"] == 5
    assert overview.json()["click_coverage_count"] == 6
    assert trends.status_code == 200
    assert len(trends.json()["items"]) == 8
    assert trends.json()["items"][-1]["click_coverage_count"] == 6


def test_jjwxc_novel_filters_and_sorting_are_bounded() -> None:
    with TestClient(create_app(lambda: None)) as client:
        response = client.get(
            "/api/v1/jjwxc/novels",
            params={"status": "完结", "genre": "爱情", "sort": "reviews", "limit": 3},
        )
        invalid = client.get("/api/v1/jjwxc/novels", params={"limit": 201})

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] >= len(payload["items"]) > 0
    assert all(item["status"] == "完结" for item in payload["items"])
    assert [item["review_count"] for item in payload["items"]] == sorted(
        [item["review_count"] for item in payload["items"]], reverse=True
    )
    assert invalid.status_code == 422


def test_jjwxc_author_detail_contains_only_its_novels() -> None:
    with TestClient(create_app(lambda: None)) as client:
        response = client.get("/api/v1/jjwxc/authors/700001")
        missing = client.get("/api/v1/jjwxc/authors/999999")

    assert response.status_code == 200
    payload = response.json()
    assert payload["author"]["author_id"] == "700001"
    assert payload["author"]["novel_count"] == 2
    assert {item["author_id"] for item in payload["novels"]} == {"700001"}
    assert missing.status_code == 404


def test_jjwxc_api_is_get_only_and_no_store() -> None:
    with TestClient(create_app(lambda: None)) as client:
        response = client.post("/api/v1/jjwxc/overview")
        get_response = client.get("/api/v1/jjwxc/overview")

    assert response.status_code == 405
    assert get_response.headers["cache-control"] == "no-store"
    assert "chapter" not in get_response.text.lower()
    assert "comment" not in get_response.text.lower()


def test_multivariate_analytics_preserves_missingness_and_matrix_shape() -> None:
    with TestClient(create_app(lambda: None)) as client:
        response = client.get("/api/v1/jjwxc/analytics/multivariate")

    assert response.status_code == 200
    payload = response.json()
    assert payload["history_source"] == "project_snapshot_fixture"
    assert payload["interpretation"] == "descriptive_association_only"
    assert len(payload["timeline"]) == 8
    assert len(payload["normalized_timeline"]) == 8
    assert payload["normalized_timeline"][0]["values"]["reviews"] == 10_000
    assert len(payload["correlation_matrix"]) == 36
    click_summary = next(item for item in payload["summaries"] if item["metric"] == "clicks")
    assert click_summary["observed_count"] == 6
    assert click_summary["missing_count"] == 2
    assert click_summary["coverage_basis_points"] == 7_500


def test_adjustable_ratings_are_normalized_ranked_and_explicitly_relative() -> None:
    with TestClient(create_app(lambda: None)) as client:
        default_response = client.get("/api/v1/jjwxc/analytics/ratings")
        adjusted_response = client.get(
            "/api/v1/jjwxc/analytics/ratings",
            params={"reviews": 1, "favorites": 0, "points": 0, "words": 0, "clicks": 0},
        )
        unavailable_day = client.get(
            "/api/v1/jjwxc/analytics/ratings", params={"day": "2026-01-01"}
        )

    assert default_response.status_code == 200
    payload = default_response.json()
    assert payload["interpretation"] == "cohort_relative_public_data_performance"
    assert sum(payload["default_weights"].values()) == 10_000
    assert payload["default_weights"]["favorites"] > payload["default_weights"]["words"]
    assert {item["grade"] for item in payload["novels"]} <= {"SSS", "SS", "S", "A", "B"}
    assert [item["score_basis_points"] for item in payload["novels"]] == sorted(
        [item["score_basis_points"] for item in payload["novels"]], reverse=True
    )
    assert any(item["coverage_basis_points"] == 8_000 for item in payload["novels"])
    assert adjusted_response.status_code == 200
    assert adjusted_response.json()["effective_weights"]["reviews"] == 10_000
    assert unavailable_day.status_code == 422
