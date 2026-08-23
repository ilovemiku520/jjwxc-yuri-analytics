from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

from pixiv_yuri.acquisition.auth import OfflineSessionBroker, SessionCapability
from pixiv_yuri.acquisition.providers.authenticated_fixture import (
    AuthenticatedFixtureProvider,
    AuthenticatedFixtureProviderError,
)
from pixiv_yuri.governance.g0 import G0Approval
from tests.test_g0_governance import valid_approval_payload

MANIFEST = Path(__file__).resolve().parents[1] / "fixtures" / "manifest.json"
CHECKED_AT = datetime(2026, 8, 23, tzinfo=UTC)


def broker_with_ratings(*ratings: str) -> OfflineSessionBroker:
    capability = SessionCapability.model_validate(
        {
            "established_at": "2026-08-22T00:00:00+00:00",
            "expires_at": "2026-08-24T00:00:00+00:00",
            "allowed_age_ratings": list(ratings),
        }
    )
    return OfflineSessionBroker(capability)


def test_authenticated_fixture_provider_reads_only_local_fixture() -> None:
    provider = AuthenticatedFixtureProvider(
        MANIFEST,
        G0Approval.model_validate(valid_approval_payload()),
        broker_with_ratings("all_ages", "r18", "r18g"),
        clock=lambda: CHECKED_AT,
    )

    response = provider.fetch(provider.list_requests()[0])
    serialized = repr(response.model_dump()).lower()

    assert response.provider.startswith("authenticated_fixture:")
    assert response.metadata["authentication_mode"] == "user_managed_session"
    assert "password" not in serialized
    assert "cookie" not in serialized
    assert "authorization" not in serialized
    assert "token" not in serialized


def test_missing_adult_rating_scope_fails_closed() -> None:
    provider = AuthenticatedFixtureProvider(
        MANIFEST,
        G0Approval.model_validate(valid_approval_payload()),
        broker_with_ratings("all_ages", "r18"),
        clock=lambda: CHECKED_AT,
    )

    with pytest.raises(AuthenticatedFixtureProviderError, match="r18g"):
        provider.fetch(provider.list_requests()[0])


def test_expired_session_fails_closed() -> None:
    capability = SessionCapability.model_validate(
        {
            "established_at": "2026-08-20T00:00:00+00:00",
            "expires_at": "2026-08-22T00:00:00+00:00",
            "allowed_age_ratings": ["all_ages", "r18", "r18g"],
        }
    )
    provider = AuthenticatedFixtureProvider(
        MANIFEST,
        G0Approval.model_validate(valid_approval_payload()),
        OfflineSessionBroker(capability),
        clock=lambda: CHECKED_AT,
    )

    with pytest.raises(AuthenticatedFixtureProviderError, match="inactive"):
        provider.fetch(provider.list_requests()[0])


def test_unauthenticated_g0_cannot_construct_authenticated_provider() -> None:
    payload = valid_approval_payload()
    scope = cast(dict[str, object], payload["source_scope"])
    scope["authentication_mode"] = "none"
    scope["content_visibility"] = "unauthenticated_public"
    scope["allowed_age_ratings"] = ["all_ages"]
    approval = G0Approval.model_validate(payload)

    with pytest.raises(AuthenticatedFixtureProviderError, match="user-managed"):
        AuthenticatedFixtureProvider(
            MANIFEST,
            approval,
            broker_with_ratings("all_ages"),
            clock=lambda: CHECKED_AT,
        )


def test_secret_shaped_fixture_fields_fail_closed(tmp_path: Path) -> None:
    payload_path = tmp_path / "payload.json"
    payload_path.write_text(json.dumps({"work_id": "1", "session_token": "unsafe"}))
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "version": 1,
                "provider": "secret_fixture",
                "records": [
                    {
                        "entity_type": "work",
                        "source_id": "1",
                        "observed_at": "2026-08-23T00:00:00+00:00",
                        "path": "payload.json",
                    }
                ],
            }
        )
    )
    provider = AuthenticatedFixtureProvider(
        manifest_path,
        G0Approval.model_validate(valid_approval_payload()),
        broker_with_ratings("all_ages", "r18", "r18g"),
        clock=lambda: CHECKED_AT,
    )

    with pytest.raises(AuthenticatedFixtureProviderError, match="secret-shaped"):
        provider.fetch(provider.list_requests()[0])


def test_session_capability_rating_scope_is_deeply_immutable() -> None:
    ratings = {"all_ages", "r18", "r18g"}
    capability = SessionCapability.model_validate(
        {
            "established_at": "2026-08-22T00:00:00+00:00",
            "expires_at": "2026-08-24T00:00:00+00:00",
            "allowed_age_ratings": ratings,
        }
    )

    ratings.clear()

    assert capability.allowed_age_ratings == frozenset(
        {"all_ages", "r18", "r18g"}
    )
