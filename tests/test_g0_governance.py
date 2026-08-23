from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from pydantic import ValidationError

from pixiv_yuri.governance.cli import main
from pixiv_yuri.governance.g0 import (
    G0Approval,
    approval_fingerprint,
    load_active_g0_approval,
)


def valid_approval_payload() -> dict[str, object]:
    return {
        "version": 2,
        "status": "approved",
        "purpose": "Bounded representative-sample research for schema validation.",
        "accountable_owner": "Research Owner",
        "approved_by": "Project Approver",
        "incident_contact_role": "On-call Operator",
        "approved_at": "2026-08-22T00:00:00+00:00",
        "expires_at": "2026-09-21T00:00:00+00:00",
        "terms_reviewed_at": "2026-08-21T00:00:00+00:00",
        "terms_reference": "legal-review-2026-08-21",
        "source_scope": {
            "page_types": ["public_work", "public_author", "public_tag"],
            "allowed_fields": [
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
                "tag_name",
                "tag_translation",
            ],
            "prohibited_fields": ["cookies", "private_content", "image_bytes"],
            "authentication_mode": "user_managed_session",
            "content_visibility": "authenticated_public",
            "allowed_age_ratings": ["all_ages", "r18", "r18g"],
            "password_collection_allowed": False,
            "secret_persistence_allowed": False,
            "secret_logging_allowed": False,
            "private_content_allowed": False,
            "deleted_content_allowed": False,
            "access_control_bypass_allowed": False,
            "media_storage_allowed": False,
        },
        "traffic_limits": {
            "requests_per_minute": 6,
            "concurrency": 1,
            "daily_request_cap": 100,
            "per_run_request_cap": 25,
            "request_timeout_seconds": 15,
        },
        "cost_limits": {"currency": "CNY", "daily_cap": 10, "monthly_cap": 100},
        "retention": {
            "raw_metadata_days": 7,
            "audit_metadata_days": 365,
            "store_raw_payloads_in_database": False,
            "publication_mode": "private_research",
        },
        "stop_conditions": [
            "repeated_403",
            "repeated_429",
            "schema_drift",
            "daily_request_cap",
            "daily_cost_cap",
            "monthly_cost_cap",
            "complaint_or_takedown",
            "incident_owner_request",
        ],
    }


def write_payload(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_complete_active_approval_loads_and_has_stable_fingerprint(tmp_path: Path) -> None:
    approval_path = tmp_path / "g0.json"
    write_payload(approval_path, valid_approval_payload())

    approval = load_active_g0_approval(
        approval_path, now=datetime(2026, 8, 23, tzinfo=UTC)
    )

    assert approval.status == "approved"
    assert len(approval_fingerprint(approval)) == 64
    assert approval_fingerprint(approval) == approval_fingerprint(approval)


def test_draft_record_is_rejected() -> None:
    payload = valid_approval_payload()
    payload["status"] = "draft"

    with pytest.raises(ValidationError):
        G0Approval.model_validate(payload)


def test_missing_mandatory_stop_condition_is_rejected() -> None:
    payload = valid_approval_payload()
    stop_conditions = cast(list[str], payload["stop_conditions"])
    payload["stop_conditions"] = [
        item for item in stop_conditions if item != "complaint_or_takedown"
    ] + ["unexpected_stop"]

    with pytest.raises(ValidationError, match="complaint_or_takedown"):
        G0Approval.model_validate(payload)


def test_expired_approval_is_rejected(tmp_path: Path) -> None:
    approval_path = tmp_path / "g0.json"
    write_payload(approval_path, valid_approval_payload())

    with pytest.raises(ValueError, match="expired"):
        load_active_g0_approval(approval_path, now=datetime(2026, 10, 1, tzinfo=UTC))


def test_unsafe_limits_are_rejected() -> None:
    payload = valid_approval_payload()
    traffic_limits = cast(dict[str, object], payload["traffic_limits"])
    traffic_limits["concurrency"] = 10
    payload["traffic_limits"] = traffic_limits

    with pytest.raises(ValidationError):
        G0Approval.model_validate(payload)


def test_authenticated_public_adult_ratings_are_explicitly_supported() -> None:
    approval = G0Approval.model_validate(valid_approval_payload())

    assert approval.source_scope.authentication_mode == "user_managed_session"
    assert approval.source_scope.content_visibility == "authenticated_public"
    assert approval.source_scope.allowed_age_ratings == {"all_ages", "r18", "r18g"}


def test_adult_ratings_without_authenticated_session_are_rejected() -> None:
    payload = valid_approval_payload()
    source_scope = cast(dict[str, object], payload["source_scope"])
    source_scope["authentication_mode"] = "none"
    source_scope["content_visibility"] = "unauthenticated_public"

    with pytest.raises(ValidationError, match="Age-restricted"):
        G0Approval.model_validate(payload)


def test_password_or_secret_persistence_cannot_be_approved() -> None:
    for unsafe_field in (
        "password_collection_allowed",
        "secret_persistence_allowed",
        "secret_logging_allowed",
    ):
        payload = valid_approval_payload()
        source_scope = cast(dict[str, object], payload["source_scope"])
        source_scope[unsafe_field] = True

        with pytest.raises(ValidationError):
            G0Approval.model_validate(payload)


def test_cli_rejects_example_draft(capsys: pytest.CaptureFixture[str]) -> None:
    project_root = Path(__file__).resolve().parents[1]
    exit_code = main([str(project_root / "config" / "g0_approval.example.json")])

    assert exit_code == 2
    output = json.loads(capsys.readouterr().err)
    assert output["status"] == "rejected"
