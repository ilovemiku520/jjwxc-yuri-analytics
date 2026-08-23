from __future__ import annotations

from typing import cast

from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy import Table

from pixiv_yuri.analytics.models import CatalogAuthor, CatalogWork
from pixiv_yuri.api.app import create_app
from pixiv_yuri.api.auth import ConsumerAuthenticationError, ConsumerIdentity
from pixiv_yuri.api.cursor import encode_rank_cursor
from tests.test_api_catalog import build_catalog_factory


def test_catalog_details_are_minimized_and_private_cached() -> None:
    with TestClient(
        create_app(lambda: None, session_factory=build_catalog_factory())
    ) as client:
        work = client.get("/api/v1/works/synthetic-work-1001")
        author = client.get("/api/v1/authors/synthetic-author-501")
        tag = client.get("/api/v1/tags/synthetic-tag-a")

    assert work.status_code == author.status_code == tag.status_code == 200
    assert work.json()["work_title"] == "Synthetic Work Alpha"
    assert author.json()["work_count"] == 2
    assert author.json()["total_public_like_count"] == 218
    assert tag.json() == {
        "tag_name": "synthetic-tag-a",
        "tag_translation": None,
        "work_count": 2,
    }
    assert work.headers["cache-control"] == "private, max-age=30"
    rendered = f"{work.text}{author.text}{tag.text}".lower()
    for forbidden in ("payload", "source_url", "followers", "comments", "observation_id"):
        assert forbidden not in rendered


def test_detail_missing_errors_are_fixed() -> None:
    with TestClient(
        create_app(lambda: None, session_factory=build_catalog_factory())
    ) as client:
        work = client.get("/api/v1/works/missing")
        author = client.get("/api/v1/authors/missing")
        tag = client.get("/api/v1/tags/missing")

    assert work.status_code == author.status_code == tag.status_code == 404
    assert work.json() == {"detail": "work_not_found"}
    assert author.json() == {"detail": "author_not_found"}
    assert tag.json() == {"detail": "tag_not_found"}


def test_work_ranking_uses_stable_metric_bound_cursor() -> None:
    with TestClient(
        create_app(lambda: None, session_factory=build_catalog_factory())
    ) as client:
        first = client.get(
            "/api/v1/rankings/works", params={"metric": "likes", "limit": 1}
        )
        second = client.get(
            "/api/v1/rankings/works",
            params={
                "metric": "likes",
                "limit": 1,
                "cursor": first.json()["next_cursor"],
            },
        )
        wrong_metric = client.get(
            "/api/v1/rankings/works",
            params={"metric": "bookmarks", "cursor": first.json()["next_cursor"]},
        )

    assert first.status_code == second.status_code == 200
    assert first.json()["items"] == [
        {
            "work_id": "synthetic-work-1001",
            "work_title": "Synthetic Work Alpha",
            "author_id": "synthetic-author-501",
            "author_display_name": "Synthetic Author",
            "score": 120,
        }
    ]
    assert second.json()["items"][0]["score"] == 98
    assert second.json()["next_cursor"] is None
    assert wrong_metric.status_code == 422
    assert wrong_metric.json() == {"detail": "invalid_cursor"}


def test_author_ranking_aggregates_reviewed_metrics() -> None:
    with TestClient(
        create_app(lambda: None, session_factory=build_catalog_factory())
    ) as client:
        response = client.get(
            "/api/v1/rankings/authors", params={"metric": "bookmarks"}
        )

    assert response.status_code == 200
    assert response.json() == {
        "metric": "bookmarks",
        "items": [
            {
                "author_id": "synthetic-author-501",
                "author_display_name": "Synthetic Author",
                "work_count": 2,
                "metric_coverage_count": 2,
                "score": 136,
                "score_scale": 1,
            }
        ],
        "next_cursor": None,
    }


def test_author_ranking_supports_work_count_and_complete_metric_averages() -> None:
    with TestClient(
        create_app(lambda: None, session_factory=build_catalog_factory())
    ) as client:
        works = client.get("/api/v1/rankings/authors", params={"metric": "works"})
        likes = client.get(
            "/api/v1/rankings/authors", params={"metric": "average_likes"}
        )
        bookmarks = client.get(
            "/api/v1/rankings/authors", params={"metric": "average_bookmarks"}
        )

    assert works.status_code == likes.status_code == bookmarks.status_code == 200
    assert works.json()["items"][0] == {
        "author_id": "synthetic-author-501",
        "author_display_name": "Synthetic Author",
        "work_count": 2,
        "metric_coverage_count": 2,
        "score": 2,
        "score_scale": 1,
    }
    assert likes.json()["items"][0]["score"] == 10900
    assert likes.json()["items"][0]["score_scale"] == 100
    assert likes.json()["items"][0]["metric_coverage_count"] == 2
    assert bookmarks.json()["items"][0]["score"] == 6800


def test_author_average_ranking_cursor_is_metric_bound() -> None:
    likes_cursor = encode_rank_cursor(
        10_900, 1, "author-ranking:average_likes"
    )
    with TestClient(
        create_app(lambda: None, session_factory=build_catalog_factory())
    ) as client:
        wrong_metric = client.get(
            "/api/v1/rankings/authors",
            params={
                "metric": "average_bookmarks",
                "cursor": likes_cursor,
            },
        )

    assert wrong_metric.status_code == 422
    assert wrong_metric.json() == {"detail": "invalid_cursor"}


class _AllowedAuthorizer:
    def authorize(self, request: Request) -> ConsumerIdentity:
        return ConsumerIdentity(subject="consumer-1", scopes=frozenset({"analytics:read"}))


class _MissingAuthorizer:
    def authorize(self, request: Request) -> ConsumerIdentity:
        raise ConsumerAuthenticationError


class _WrongScopeAuthorizer:
    def authorize(self, request: Request) -> ConsumerIdentity:
        return ConsumerIdentity(subject="consumer-1", scopes=frozenset({"other:read"}))


class _BrokenAuthorizer:
    def authorize(self, request: Request) -> ConsumerIdentity:
        raise RuntimeError("secret identity provider details")


def test_injected_consumer_authorization_enforces_analytics_read_scope() -> None:
    factory = build_catalog_factory()
    outcomes: list[tuple[int, dict[str, object]]] = []
    for authorizer in (
        _AllowedAuthorizer(),
        _MissingAuthorizer(),
        _WrongScopeAuthorizer(),
        _BrokenAuthorizer(),
    ):
        with TestClient(
            create_app(
                lambda: None,
                session_factory=factory,
                consumer_authorizer=authorizer,
            )
        ) as client:
            response = client.get("/api/v1/analytics/freshness")
            outcomes.append((response.status_code, response.json()))

    assert outcomes[0][0] == 200
    assert outcomes[1:] == [
        (401, {"detail": "consumer_authentication_required"}),
        (403, {"detail": "analytics_read_scope_required"}),
        (503, {"detail": "authorization_service_unavailable"}),
    ]
    assert "secret" not in str(outcomes).lower()


def test_health_routes_bypass_consumer_authorizer() -> None:
    with TestClient(
        create_app(lambda: None, consumer_authorizer=_MissingAuthorizer())
    ) as client:
        response = client.get("/health/live")

    assert response.status_code == 200


def test_openapi_contract_is_read_only_and_has_no_storage_fields() -> None:
    schema = create_app(lambda: None).openapi()
    api_paths = {path: value for path, value in schema["paths"].items() if path.startswith("/api")}
    expected = {
        "/api/v1/works/{work_id}",
        "/api/v1/authors/{author_id}",
        "/api/v1/tags/{tag_name}",
        "/api/v1/rankings/works",
        "/api/v1/rankings/authors",
    }
    assert expected <= set(api_paths)
    for operations in api_paths.values():
        assert set(operations) <= {"get", "parameters"}

    rendered = str(schema["components"]["schemas"]).lower()
    for forbidden in (
        "source_url",
        "payload_object_key",
        "observation_metadata",
        "source_observation_id",
        "authorization",
        "password",
        "cookie",
    ):
        assert forbidden not in rendered


def test_catalog_ranking_indexes_are_registered() -> None:
    work_indexes = {index.name for index in cast(Table, CatalogWork.__table__).indexes}
    author_indexes = {index.name for index in cast(Table, CatalogAuthor.__table__).indexes}
    assert {
        "ix_catalog_works_work_id",
        "ix_catalog_works_like_rank",
        "ix_catalog_works_bookmark_rank",
        "ix_catalog_works_view_rank",
    } <= work_indexes
    assert "ix_catalog_authors_author_id" in author_indexes
