from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from pixiv_yuri.governance.g0 import G0Approval, approval_fingerprint
from pixiv_yuri.governance.source_endpoint_contract import (
    SourceEndpointContract,
    SourceEndpointReviewEvidence,
    finalize_source_endpoint_contract,
    review_source_endpoint_contract,
)
from tests.test_g0_governance import valid_approval_payload

NOW = datetime(2026, 8, 23, tzinfo=UTC)


def build_contract(approval: G0Approval, **changes: object) -> SourceEndpointContract:
    payload: dict[str, object] = {
        "version": 1,
        "status": "reviewed",
        "approval_fingerprint": approval_fingerprint(approval),
        "reviewed_at": NOW - timedelta(minutes=1),
        "expires_at": NOW + timedelta(days=1),
        "review_reference": "synthetic-offline-review",
        "origin": "https://metadata.source.test",
        "path_template": "/works/{source_id}",
        "method": "GET",
        "credential_header": "Cookie",
        "accept_content_type": "application/json",
        "redirects_allowed": False,
        "query_parameters_allowed": False,
        "media_download_allowed": False,
        "planned_requests": 1,
        "max_response_body_bytes": 1_000_000,
        "request_timeout_seconds": approval.traffic_limits.request_timeout_seconds,
        "allowed_fields": approval.source_scope.allowed_fields,
        "allowed_age_ratings": approval.source_scope.allowed_age_ratings,
    }
    payload.update(changes)
    return SourceEndpointContract.model_validate(payload)


def test_reviewed_contract_matches_g0_without_authorizing_network() -> None:
    approval = G0Approval.model_validate(valid_approval_payload())

    result = review_source_endpoint_contract(build_contract(approval), approval, now=NOW)

    assert result.status == "passed"
    assert result.planned_requests == 1
    assert result.field_count == 14
    assert result.rating_count == 3
    assert result.authorizes_network is False


@pytest.mark.parametrize(
    "origin",
    [
        "http://metadata.source.test",
        "https://user@metadata.source.test",
        "https://metadata.source.test/path",
        "https://metadata.source.test?token=x",
        "https://127.0.0.1",
    ],
)
def test_origin_must_be_exact_https_dns_without_secrets(origin: str) -> None:
    approval = G0Approval.model_validate(valid_approval_payload())

    with pytest.raises(ValidationError, match="exact HTTPS DNS origin"):
        build_contract(approval, origin=origin)


@pytest.mark.parametrize(
    "path_template",
    [
        "/works/static",
        "/works/{source_id}?lang=en",
        "/works/../{source_id}",
        "//works/{source_id}",
        "/works/{source_id}/{extra}",
    ],
)
def test_path_is_fixed_query_free_single_identity_template(path_template: str) -> None:
    approval = G0Approval.model_validate(valid_approval_payload())

    with pytest.raises(ValidationError, match="fixed query-free"):
        build_contract(approval, path_template=path_template)


def test_contract_cannot_expand_fields_ratings_or_timeout() -> None:
    approval = G0Approval.model_validate(valid_approval_payload())
    extra_fields = build_contract(
        approval, allowed_fields=approval.source_scope.allowed_fields | {"secret_extra"}
    )
    narrower_ratings = build_contract(approval, allowed_age_ratings={"all_ages"})
    longer_timeout = build_contract(
        approval,
        request_timeout_seconds=approval.traffic_limits.request_timeout_seconds + 1,
    )

    with pytest.raises(ValueError, match="fields"):
        review_source_endpoint_contract(extra_fields, approval, now=NOW)
    with pytest.raises(ValueError, match="ratings"):
        review_source_endpoint_contract(narrower_ratings, approval, now=NOW)
    with pytest.raises(ValueError, match="timeout"):
        review_source_endpoint_contract(longer_timeout, approval, now=NOW)


def test_contract_must_be_current_and_bound_to_active_g0() -> None:
    approval = G0Approval.model_validate(valid_approval_payload())
    wrong = build_contract(approval, approval_fingerprint="a" * 64)
    expired = build_contract(approval, expires_at=NOW)

    with pytest.raises(ValueError, match="different G0"):
        review_source_endpoint_contract(wrong, approval, now=NOW)
    with pytest.raises(ValueError, match="inactive or outlives"):
        review_source_endpoint_contract(expired, approval, now=NOW)


def test_contract_model_forbids_network_expansion_fields() -> None:
    approval = G0Approval.model_validate(valid_approval_payload())
    payload = build_contract(approval).model_dump()
    payload["redirects_allowed"] = True

    with pytest.raises(ValidationError):
        SourceEndpointContract.model_validate(payload)
    assert not {
        "password",
        "cookie_value",
        "session",
        "token",
        "response_body",
    } & set(SourceEndpointContract.model_fields)


def build_evidence(
    approval: G0Approval, **changes: object
) -> SourceEndpointReviewEvidence:
    payload: dict[str, object] = {
        "version": 1,
        "status": "ready",
        "reviewer_role": "accountable-owner",
        "exact_origin": "https://metadata.source.test",
        "path_template": "/works/{source_id}",
        "terms_reference": "synthetic-current-terms-review",
        "terms_reviewed_at": NOW - timedelta(minutes=2),
        "response_reviewed_at": NOW - timedelta(minutes=1),
        "response_schema_sha256": "a" * 64,
        "representative_sample_count": 1,
        "observed_content_type": "application/json",
        "observed_fields": approval.source_scope.allowed_fields,
        "observed_max_body_bytes": 100_000,
        "redirects_observed": False,
        "query_parameters_required": False,
        "media_bytes_observed": False,
        "secret_shaped_fields_observed": False,
        "private_or_deleted_content_observed": False,
    }
    payload.update(changes)
    return SourceEndpointReviewEvidence.model_validate(payload)


def test_complete_human_evidence_finalizes_non_authorizing_contract() -> None:
    approval = G0Approval.model_validate(valid_approval_payload())

    contract = finalize_source_endpoint_contract(
        build_evidence(approval),
        approval,
        expires_at=NOW + timedelta(days=1),
        now=NOW,
    )
    review = review_source_endpoint_contract(contract, approval, now=NOW)

    assert contract.status == "reviewed"
    assert contract.origin == "https://metadata.source.test"
    assert contract.path_template == "/works/{source_id}"
    assert "a" * 64 in contract.review_reference
    assert review.authorizes_network is False


def test_evidence_with_schema_expansion_cannot_finalize_contract() -> None:
    approval = G0Approval.model_validate(valid_approval_payload())
    evidence = build_evidence(
        approval,
        observed_fields=approval.source_scope.allowed_fields | {"unapproved_field"},
    )

    with pytest.raises(ValueError, match="exactly match G0"):
        finalize_source_endpoint_contract(
            evidence,
            approval,
            expires_at=NOW + timedelta(days=1),
            now=NOW,
        )


def test_future_or_incomplete_evidence_is_rejected() -> None:
    approval = G0Approval.model_validate(valid_approval_payload())
    future = build_evidence(approval, response_reviewed_at=NOW + timedelta(seconds=1))

    with pytest.raises(ValueError, match="response evidence"):
        finalize_source_endpoint_contract(
            future,
            approval,
            expires_at=NOW + timedelta(days=1),
            now=NOW,
        )
    with pytest.raises(ValidationError):
        SourceEndpointReviewEvidence.model_validate(
            {"version": 1, "status": "ready", "reviewer_role": "accountable-owner"}
        )
