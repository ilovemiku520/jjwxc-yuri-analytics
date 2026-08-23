from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pixiv_yuri.analytics.author_influence import (
    AuthorInfluenceInput,
    AuthorInfluenceWeights,
    classify_author_quality,
    score_author_influence,
)
from pixiv_yuri.api.app import create_app
from tests.test_api_catalog import build_catalog_factory

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "analytics" / "author_influence.json"


def _fixture_authors() -> list[AuthorInfluenceInput]:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert payload["fixture_kind"] == "author_influence_aggregates_v1"
    return [AuthorInfluenceInput(**item) for item in payload["authors"]]


def test_influence_fixture_scores_four_authors_deterministically() -> None:
    result = score_author_influence(
        _fixture_authors(), AuthorInfluenceWeights(), limit=4
    )

    assert [item.author_id for item in result] == [
        "author-boutique",
        "author-core",
        "author-volume",
        "author-ordinary",
    ]
    assert result[0].influence_score_basis_points == 8500
    assert result[0].bookmark_component_basis_points == 10000
    assert result[0].like_component_basis_points == 10000
    assert result[0].production_component_basis_points == 2000


def test_multi_author_fixture_spans_all_quality_quadrants() -> None:
    quadrants = {
        classify_author_quality(
            work_count_x100=author.work_count * 100,
            average_bookmarks_x100=author.average_bookmark_count_x100,
            work_threshold_x100=500,
            bookmark_threshold_x100=6000,
        )
        for author in _fixture_authors()
    }

    assert quadrants == {"core", "boutique", "volume", "ordinary"}


def test_influence_weights_and_limit_fail_closed() -> None:
    authors = _fixture_authors()
    with pytest.raises(ValueError, match="total 10000"):
        score_author_influence(
            authors,
            AuthorInfluenceWeights(bookmark=5000, like=5000, production=5000),
            limit=4,
        )
    with pytest.raises(ValueError, match="between 1 and 100"):
        score_author_influence(authors, AuthorInfluenceWeights(), limit=101)


def test_influence_api_requires_complete_metrics_and_exposes_model() -> None:
    with TestClient(
        create_app(lambda: None, session_factory=build_catalog_factory())
    ) as client:
        response = client.get("/api/v1/analytics/authors/influence-ranking")
        invalid = client.get(
            "/api/v1/analytics/authors/influence-ranking",
            params={
                "bookmark_weight": 5000,
                "like_weight": 5000,
                "production_weight": 5000,
            },
        )
        custom = client.get(
            "/api/v1/analytics/authors/influence-ranking",
            params={
                "bookmark_weight": 5000,
                "like_weight": 3000,
                "production_weight": 2000,
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "model_version": "allowed-metadata-v1",
        "weights": {"bookmark": 4375, "like": 3750, "production": 1875},
        "sampled_author_count": 1,
        "sample_truncated": False,
        "items": [
            {
                "author_id": "synthetic-author-501",
                "author_display_name": "Synthetic Author",
                "work_count": 2,
                "complete_metric_work_count": 2,
                "average_public_bookmark_count_x100": 6800,
                "average_public_like_count_x100": 10900,
                "bookmark_component_basis_points": 10000,
                "like_component_basis_points": 10000,
                "production_component_basis_points": 10000,
                "influence_score_basis_points": 10000,
            }
        ],
    }
    assert invalid.status_code == 422
    assert invalid.json() == {"detail": "invalid_influence_weights"}
    assert custom.status_code == 200
    assert custom.json()["weights"] == {
        "bookmark": 5000,
        "like": 3000,
        "production": 2000,
    }
