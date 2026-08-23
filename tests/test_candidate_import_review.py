from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import UTC, datetime, timedelta

from pixiv_yuri.acquisition.browser_export_import import SanitizedPublicMetadata
from pixiv_yuri.governance.candidate_import_review import review_candidate_import

NOW = datetime(2026, 8, 23, tzinfo=UTC)
G0_HASH = "a" * 64
CONTRACT_HASH = "b" * 64


def _candidate_bytes(work_id: str = "123456") -> bytes:
    record = SanitizedPublicMetadata.model_validate(
        {
            "work_id": work_id,
            "work_title": "Synthetic candidate",
            "author_id": "789",
            "author_display_name": "Synthetic author",
            "public_tags": [{"tag_name": "synthetic"}],
            "created_at": datetime(2026, 8, 22, 15, tzinfo=UTC),
            "page_count": 1,
            "width": 1200,
            "height": 900,
            "public_view_count": 10,
            "public_bookmark_count": 2,
            "public_like_count": 3,
        }
    )
    return (json.dumps(record.model_dump(mode="json"), sort_keys=True) + "\n").encode()


def _evidence(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "generated_at": NOW.isoformat(),
        "status": "candidate_ready",
        "source_format": "powerful_pixiv_downloader_json",
        "input_sha256": "c" * 64,
        "input_records": 1,
        "accepted_records": 1,
        "rejected_records": 0,
        "duplicate_or_extra_page_records": 0,
        "violations": [],
        "visibility_verified": False,
        "canonical_ingest_authorized": False,
        "credentials_requested": False,
        "external_network_used": False,
        "media_persisted": False,
        "raw_payload_persisted": False,
    }
    payload.update(changes)
    return payload


def _app_api_evidence(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "generated_at": NOW.isoformat(),
        "status": "candidate_ready",
        "operation": "search_illust",
        "authentication_mode": "oauth_pkce",
        "requested_pages": 1,
        "input_records": 1,
        "candidate_records": 1,
        "duplicate_records": 0,
        "skipped_records": 0,
        "external_network_used": True,
        "oauth_authorization_code_requested": True,
        "refresh_token_requested": False,
        "password_requested": False,
        "secret_persisted": False,
        "raw_payload_persisted": False,
        "media_persisted": False,
        "automatic_retries": 0,
        "network_concurrency": 1,
        "canonical_ingest_authorized": False,
        "violations": [],
    }
    payload.update(changes)
    return payload


def _json_hash(value: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def _review(
    candidate_bytes: bytes, evidence: dict[str, object], **changes: object
) -> dict[str, object]:
    payload: dict[str, object] = {
        "artifact_type": "candidate_visibility_review",
        "version": 1,
        "status": "finalized",
        "review_id": "candidate-review-01",
        "reviewer_id": "reviewer@example.test",
        "reviewer_role": "accountable_human_reviewer",
        "created_at": NOW.isoformat(),
        "reviewed_at": (NOW + timedelta(minutes=1)).isoformat(),
        "expires_at": (NOW + timedelta(days=1)).isoformat(),
        "g0_approval_fingerprint": G0_HASH,
        "import_report_sha256": _json_hash(evidence),
        "candidate_file_sha256": hashlib.sha256(candidate_bytes).hexdigest(),
        "candidate_record_count": 1,
        "visibility_observation": "manual_browser_observation",
        "all_records_observed_as_authenticated_public": True,
        "observed_age_ratings": ["all_ages"],
        "review_reference": "Local human observation; no URL or credential recorded.",
        "canonical_ingest_requested": True,
        "credentials_requested": False,
        "external_network_used": False,
        "media_persisted": False,
        "raw_payload_persisted": False,
    }
    payload.update(changes)
    return payload


def _endpoint(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "generated_at": NOW.isoformat(),
        "status": "ready",
        "contract_ready": True,
        "approval_fingerprint": G0_HASH,
        "evidence_sha256": "d" * 64,
        "contract_sha256": CONTRACT_HASH,
        "contract_expires_at": (NOW + timedelta(days=1)).isoformat(),
        "authorizes_network": False,
        "credentials_requested": False,
        "external_network_used": False,
        "violations": [],
    }
    payload.update(changes)
    return payload


def test_exact_candidate_review_and_source_contract_authorize_only_the_next_stage() -> None:
    candidate = _candidate_bytes()
    evidence = _evidence()

    report = review_candidate_import(
        candidate_bytes=candidate,
        import_report_payload=evidence,
        review_payload=_review(candidate, evidence),
        endpoint_report_payload=_endpoint(),
        active_g0_fingerprint=G0_HASH,
        now=NOW + timedelta(minutes=2),
    )

    assert report.status == "authorized_for_canonical_ingest"
    assert report.canonical_ingest_authorized is True
    assert report.manual_visibility_review_verified is True
    assert report.source_endpoint_contract_ready is True
    assert report.credentials_requested is False
    assert report.external_network_used is False
    assert report.media_persisted is False
    assert report.raw_payload_persisted is False
    assert report.violations == ()


def test_companion_review_accepts_g0_ratings_but_legacy_export_remains_all_ages() -> None:
    candidate = _candidate_bytes()
    companion_evidence = _evidence(source_format="pyuri_pixiv_browser_companion_json")
    companion_review = _review(
        candidate,
        companion_evidence,
        observed_age_ratings=["all_ages", "r18", "r18g"],
    )

    companion = review_candidate_import(
        candidate_bytes=candidate,
        import_report_payload=companion_evidence,
        review_payload=companion_review,
        endpoint_report_payload=_endpoint(),
        active_g0_fingerprint=G0_HASH,
        now=NOW + timedelta(minutes=2),
    )
    assert companion.canonical_ingest_authorized is True
    assert companion.violations == ()

    legacy_evidence = _evidence()
    legacy = review_candidate_import(
        candidate_bytes=candidate,
        import_report_payload=legacy_evidence,
        review_payload=_review(
            candidate,
            legacy_evidence,
            observed_age_ratings=["all_ages", "r18"],
        ),
        endpoint_report_payload=_endpoint(),
        active_g0_fingerprint=G0_HASH,
        now=NOW + timedelta(minutes=2),
    )
    assert legacy.canonical_ingest_authorized is False
    assert legacy.violations == ("candidate_rating_review_outside_source_scope",)


def test_app_api_candidate_uses_the_same_hash_and_manual_review_gate() -> None:
    candidate = _candidate_bytes()
    evidence = _app_api_evidence()
    report = review_candidate_import(
        candidate_bytes=candidate,
        import_report_payload=evidence,
        review_payload=_review(
            candidate,
            evidence,
            observed_age_ratings=["all_ages", "r18", "r18g"],
        ),
        endpoint_report_payload=_endpoint(),
        active_g0_fingerprint=G0_HASH,
        now=NOW + timedelta(minutes=2),
    )

    assert report.candidate_record_count == 1
    assert report.manual_visibility_review_verified is True
    assert report.canonical_ingest_authorized is True
    assert report.violations == ()


def test_missing_or_expired_endpoint_review_fails_closed() -> None:
    candidate = _candidate_bytes()
    evidence = _evidence()
    review = _review(candidate, evidence)

    missing = review_candidate_import(
        candidate_bytes=candidate,
        import_report_payload=evidence,
        review_payload=review,
        endpoint_report_payload=None,
        active_g0_fingerprint=G0_HASH,
        now=NOW + timedelta(minutes=2),
    )
    expired = review_candidate_import(
        candidate_bytes=candidate,
        import_report_payload=evidence,
        review_payload=review,
        endpoint_report_payload=_endpoint(
            contract_expires_at=(NOW - timedelta(seconds=1)).isoformat()
        ),
        active_g0_fingerprint=G0_HASH,
        now=NOW + timedelta(minutes=2),
    )

    assert missing.canonical_ingest_authorized is False
    assert "reviewed_source_endpoint_contract_missing" in missing.violations
    assert expired.canonical_ingest_authorized is False
    assert "reviewed_source_endpoint_contract_expired" in expired.violations


def test_candidate_mutation_count_change_and_g0_mismatch_cannot_reuse_review() -> None:
    original = _candidate_bytes()
    changed = _candidate_bytes("654321")
    evidence = _evidence()

    report = review_candidate_import(
        candidate_bytes=changed,
        import_report_payload=evidence,
        review_payload=_review(original, evidence),
        endpoint_report_payload=_endpoint(),
        active_g0_fingerprint="e" * 64,
        now=NOW + timedelta(minutes=2),
    )

    assert report.canonical_ingest_authorized is False
    assert "candidate_file_unbound" in report.violations
    assert "candidate_review_g0_fingerprint_mismatch" in report.violations
    assert "source_endpoint_g0_fingerprint_mismatch" in report.violations


def test_secret_or_url_shaped_review_reference_is_rejected_without_echoing_it() -> None:
    candidate = _candidate_bytes()
    evidence = _evidence()
    report = review_candidate_import(
        candidate_bytes=candidate,
        import_report_payload=evidence,
        review_payload=_review(candidate, evidence, review_reference="cookie: do-not-echo"),
        endpoint_report_payload=_endpoint(),
        active_g0_fingerprint=G0_HASH,
        now=NOW + timedelta(minutes=2),
    )

    assert report.canonical_ingest_authorized is False
    assert report.violations == ("candidate_visibility_review_invalid",)
    assert "do-not-echo" not in json.dumps(asdict(report))
