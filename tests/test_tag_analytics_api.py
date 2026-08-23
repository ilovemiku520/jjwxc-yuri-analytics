from __future__ import annotations

from fastapi.testclient import TestClient

from pixiv_yuri.api.app import create_app
from tests.test_api_catalog import build_catalog_factory


def test_tag_cooccurrence_exposes_bounded_descriptive_metrics() -> None:
    with TestClient(
        create_app(lambda: None, session_factory=build_catalog_factory())
    ) as client:
        response = client.get("/api/v1/analytics/tags/co-occurrence")

    assert response.status_code == 200
    payload = response.json()
    assert payload["interpretation"] == "descriptive_association_only"
    assert payload["semantic_classification_performed"] is False
    assert payload["catalog_work_count"] == 2
    assert payload["sampled_work_count"] == 2
    assert payload["sample_truncated"] is False
    assert payload["observed_tag_count"] == 2
    assert payload["eligible_edge_count"] == 1
    assert payload["result_truncated"] is False
    assert payload["edges"] == [
        {
            "left": {
                "tag_name": "synthetic-tag-a",
                "tag_translation": None,
                "sampled_work_count": 2,
            },
            "right": {
                "tag_name": "synthetic-tag-b",
                "tag_translation": "Synthetic B",
                "sampled_work_count": 1,
            },
            "cooccurrence_work_count": 1,
            "sample_support_basis_points": 5000,
            "jaccard_basis_points": 5000,
            "pmi_milli_bits": 0,
        }
    ]
    assert response.headers["cache-control"] == "private, max-age=60"


def test_tag_cooccurrence_anchor_and_sample_bounds_are_visible() -> None:
    with TestClient(
        create_app(lambda: None, session_factory=build_catalog_factory())
    ) as client:
        missing_anchor = client.get(
            "/api/v1/analytics/tags/co-occurrence?anchor_tag=missing"
        )
        sampled = client.get(
            "/api/v1/analytics/tags/co-occurrence?sample_work_limit=1"
        )

    assert missing_anchor.status_code == 200
    assert missing_anchor.json()["edges"] == []
    assert missing_anchor.json()["anchor_tag"] == "missing"
    assert sampled.status_code == 200
    assert sampled.json()["sampled_work_count"] == 1
    assert sampled.json()["sample_truncated"] is True


def test_tag_cooccurrence_rejects_unbounded_parameters() -> None:
    with TestClient(
        create_app(lambda: None, session_factory=build_catalog_factory())
    ) as client:
        responses = (
            client.get("/api/v1/analytics/tags/co-occurrence?limit=201"),
            client.get("/api/v1/analytics/tags/co-occurrence?sample_work_limit=5001"),
            client.get("/api/v1/analytics/tags/co-occurrence?minimum_cooccurrence=0"),
            client.get("/api/v1/analytics/tags/co-occurrence?anchor_tag="),
        )

    assert all(response.status_code == 422 for response in responses)


def test_tag_cooccurrence_fails_closed_without_data_service() -> None:
    with TestClient(create_app(lambda: None)) as client:
        response = client.get("/api/v1/analytics/tags/co-occurrence")

    assert response.status_code == 503
    assert response.json() == {"detail": "data_service_unavailable"}


def test_tag_cooccurrence_is_get_only_and_omits_classification_fields() -> None:
    schema = create_app(lambda: None).openapi()
    path = schema["paths"]["/api/v1/analytics/tags/co-occurrence"]

    assert set(path) == {"get"}
    rendered = str(path).lower()
    for forbidden in ("is_yuri", "yuri_probability", "semantic_label", "source_url"):
        assert forbidden not in rendered


def test_tag_sensitivity_exposes_fixed_thresholds_and_review_evidence() -> None:
    with TestClient(
        create_app(lambda: None, session_factory=build_catalog_factory())
    ) as client:
        response = client.get("/api/v1/analytics/tags/association-sensitivity")

    assert response.status_code == 200
    payload = response.json()
    assert payload["interpretation"] == "descriptive_association_only"
    assert payload["semantic_classification_performed"] is False
    assert payload["catalog_work_count"] == 2
    assert payload["sampled_work_count"] == 2
    assert payload["sample_truncated"] is False
    assert payload["thresholds"] == [1, 2, 3, 5, 10]
    assert [point["eligible_edge_count"] for point in payload["points"]] == [
        1,
        0,
        0,
        0,
        0,
    ]
    assert payload["review_candidates"] == [
        {
            "rank": 1,
            "left_tag_name": "synthetic-tag-a",
            "left_tag_translation": None,
            "right_tag_name": "synthetic-tag-b",
            "right_tag_translation": "Synthetic B",
            "cooccurrence_work_count": 1,
            "sample_support_basis_points": 5000,
            "jaccard_basis_points": 5000,
            "pmi_milli_bits": 0,
            "survives_minimum_cooccurrence": [1],
            "review_state": "pending_human_review",
        }
    ]
    assert response.headers["cache-control"] == "private, max-age=60"


def test_tag_sensitivity_anchor_sample_and_candidate_bounds_are_visible() -> None:
    with TestClient(
        create_app(lambda: None, session_factory=build_catalog_factory())
    ) as client:
        missing_anchor = client.get(
            "/api/v1/analytics/tags/association-sensitivity?anchor_tag=missing"
        )
        sampled = client.get(
            "/api/v1/analytics/tags/association-sensitivity?sample_work_limit=1"
        )

    assert missing_anchor.status_code == 200
    assert missing_anchor.json()["review_candidates"] == []
    assert missing_anchor.json()["anchor_tag"] == "missing"
    assert sampled.status_code == 200
    assert sampled.json()["sampled_work_count"] == 1
    assert sampled.json()["sample_truncated"] is True


def test_tag_sensitivity_rejects_unbounded_parameters_and_fails_closed() -> None:
    with TestClient(
        create_app(lambda: None, session_factory=build_catalog_factory())
    ) as client:
        invalid = (
            client.get(
                "/api/v1/analytics/tags/association-sensitivity?candidate_limit=0"
            ),
            client.get(
                "/api/v1/analytics/tags/association-sensitivity?candidate_limit=201"
            ),
            client.get(
                "/api/v1/analytics/tags/association-sensitivity?sample_work_limit=5001"
            ),
            client.get(
                "/api/v1/analytics/tags/association-sensitivity?anchor_tag="
            ),
        )
    with TestClient(create_app(lambda: None)) as client:
        unavailable = client.get(
            "/api/v1/analytics/tags/association-sensitivity"
        )

    assert all(response.status_code == 422 for response in invalid)
    assert unavailable.status_code == 503
    assert unavailable.json() == {"detail": "data_service_unavailable"}


def test_tag_sensitivity_is_get_only_and_omits_semantic_or_source_fields() -> None:
    schema = create_app(lambda: None).openapi()
    path = schema["paths"][
        "/api/v1/analytics/tags/association-sensitivity"
    ]

    assert set(path) == {"get"}
    rendered = str(path).lower()
    for forbidden in (
        "is_yuri",
        "yuri_probability",
        "semantic_label",
        "source_url",
        "payload",
        "embedding",
    ):
        assert forbidden not in rendered
