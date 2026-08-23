from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest

from pixiv_yuri.acquisition.providers.pixiv_app_api import (
    PixivAppApiCollector,
    PixivAppApiError,
    PixivAppApiOperation,
    PixivAppApiPolicy,
    build_parser,
    load_pixiv_app_api_policy,
    sanitize_pixiv_app_api_page,
)
from pixiv_yuri.governance.g0 import G0Approval, load_active_g0_approval
from tests.test_g0_governance import valid_approval_payload


def _illust(work_id: int, **changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "id": work_id,
        "title": "Synthetic work",
        "user": {
            "id": 789,
            "name": "Synthetic author",
            "account": "must-not-persist",
            "profile_image_urls": {"medium": "https://media.invalid/profile.jpg"},
        },
        "tags": [{"name": "百合", "translated_name": "Yuri"}],
        "create_date": "2026-08-23T00:00:00+09:00",
        "page_count": 1,
        "width": 1200,
        "height": 900,
        "total_view": 10,
        "total_bookmarks": 2,
        "x_restrict": 0,
        "visible": True,
        "caption": "must-not-persist",
        "image_urls": {"large": "https://media.invalid/work.jpg"},
        "meta_pages": [{"image_urls": {"original": "https://media.invalid/raw.jpg"}}],
        "is_bookmarked": True,
    }
    value.update(changes)
    return value


def _policy() -> PixivAppApiPolicy:
    path = Path(__file__).resolve().parents[1] / "config" / "pixiv_app_api_policy.json"
    return load_pixiv_app_api_policy(path)


def _approval() -> G0Approval:
    payload = valid_approval_payload()
    source_scope = cast(dict[str, object], payload["source_scope"])
    source_scope["access_methods"] = ["browser_current_work", "pixiv_app_api"]
    traffic = cast(dict[str, object], payload["traffic_limits"])
    traffic.update(
        {
            "requests_per_minute": 12,
            "daily_request_cap": 500,
            "per_run_request_cap": 100,
        }
    )
    return G0Approval.model_validate(payload)


class FakeClient:
    def __init__(self, pages: list[Mapping[str, Any]]) -> None:
        self.pages = list(pages)
        self.calls: list[tuple[PixivAppApiOperation, dict[str, object]]] = []

    def fetch_page(
        self,
        operation: PixivAppApiOperation,
        parameters: Mapping[str, object],
    ) -> Mapping[str, Any]:
        self.calls.append((operation, dict(parameters)))
        return self.pages.pop(0)

    def next_parameters(
        self,
        operation: PixivAppApiOperation,
        payload: Mapping[str, Any],
    ) -> Mapping[str, object] | None:
        del operation
        return {"word": "百合", "offset": 30} if payload.get("next_url") else None


def test_page_minimization_drops_media_caption_account_state_and_rating() -> None:
    records, skipped, input_records = sanitize_pixiv_app_api_page(
        {"illusts": [_illust(123456, x_restrict=2)]}
    )

    assert skipped == 0
    assert input_records == 1
    output = records[0].model_dump(mode="json")
    assert set(output) == {
        "work_id",
        "work_title",
        "author_id",
        "author_display_name",
        "public_tags",
        "created_at",
        "page_count",
        "width",
        "height",
        "public_view_count",
        "public_bookmark_count",
        "public_like_count",
    }
    encoded = json.dumps(output)
    assert "media.invalid" not in encoded
    assert "must-not-persist" not in encoded
    assert "x_restrict" not in encoded


def test_collector_pages_serially_deduplicates_and_reports_efficiency_boundary() -> None:
    client = FakeClient(
        [
            {"illusts": [_illust(1), _illust(2)], "next_url": "in-memory-only"},
            {"illusts": [_illust(2), _illust(3, visible=False)], "next_url": None},
        ]
    )
    sleeps: list[float] = []
    ticks = iter([0.0, 0.0, 0.0, 5.0])
    collector = PixivAppApiCollector(
        client,
        _policy(),
        _approval(),
        sleeper=sleeps.append,
        monotonic=lambda: next(ticks),
    )

    result = collector.collect(
        PixivAppApiOperation.SEARCH_ILLUST,
        {"word": "百合"},
        max_pages=2,
    )

    assert [record.work_id for record in result.records] == ["1", "2"]
    assert result.report.requested_pages == 2
    assert result.report.input_records == 4
    assert result.report.duplicate_records == 1
    assert result.report.skipped_records == 1
    assert result.report.network_concurrency == 1
    assert result.report.automatic_retries == 0
    assert result.report.oauth_authorization_code_requested is False
    assert result.report.refresh_token_requested is True
    assert result.report.password_requested is False
    assert result.report.secret_persisted is False
    assert result.report.raw_payload_persisted is False
    assert result.report.media_persisted is False
    assert result.report.canonical_ingest_authorized is False
    assert len(client.calls) == 2
    assert sleeps == [5.0]


def test_unreviewed_parameters_and_missing_g0_method_fail_before_client_call() -> None:
    client = FakeClient([{"illusts": []}])
    collector = PixivAppApiCollector(client, _policy(), _approval(), sleeper=lambda _: None)
    with pytest.raises(ValueError, match="unreviewed"):
        collector.collect(
            PixivAppApiOperation.SEARCH_ILLUST,
            {"word": "百合", "refresh_token": "must-not-echo"},
        )
    assert client.calls == []

    with pytest.raises(ValueError, match="does not approve"):
        PixivAppApiCollector(
            client,
            _policy(),
            G0Approval.model_validate(valid_approval_payload()),
        )


def test_schema_failure_is_payload_free_and_does_not_retry() -> None:
    client = FakeClient([{"illusts": [_illust(1, x_restrict=99)]}])
    collector = PixivAppApiCollector(client, _policy(), _approval(), sleeper=lambda _: None)

    with pytest.raises(PixivAppApiError) as caught:
        collector.collect(PixivAppApiOperation.SEARCH_ILLUST, {"word": "百合"})

    assert str(caught.value) == "pixiv_app_api_schema_invalid"
    assert len(client.calls) == 1


def test_active_workspace_g0_and_policy_are_compatible() -> None:
    root = Path(__file__).resolve().parents[1]
    approval = load_active_g0_approval(
        root / "config" / "g0_approval.json",
        now=datetime(2026, 8, 23, 12, tzinfo=UTC),
    )
    policy = load_pixiv_app_api_policy(root / "config" / "pixiv_app_api_policy.json")

    assert "pixiv_app_api" in approval.source_scope.access_methods
    assert policy.max_pages_per_run == approval.traffic_limits.per_run_request_cap
    assert policy.requests_per_minute == approval.traffic_limits.requests_per_minute
    assert policy.authentication_modes == {"oauth_pkce", "runtime_refresh_token"}


def test_cli_has_no_password_token_cookie_or_secret_option() -> None:
    parser = build_parser()
    option_strings = {
        option
        for action in parser._actions
        for option in action.option_strings
    }
    assert all(
        fragment not in option.lower()
        for option in option_strings
        for fragment in ("password", "token", "cookie", "secret")
    )
