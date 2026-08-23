from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from pydantic import ValidationError

from pixiv_yuri.acquisition.anonymous_public_gate import (
    AnonymousPublicGateError,
    AnonymousPublicRequestGate,
)
from pixiv_yuri.governance.anonymous_public_contract import (
    AnonymousPublicReviewEvidence,
    AnonymousPublicSourceContract,
    finalize_anonymous_public_contract,
    schema_fingerprint,
)

NOW = datetime(2026, 8, 23, tzinfo=UTC)


def _payload() -> dict[str, Any]:
    return {
        "work_id": "synthetic-1",
        "work_title": "Synthetic Work",
        "public_tags": ["synthetic-tag"],
        "public_view_count": 10,
    }


def _evidence(**changes: object) -> AnonymousPublicReviewEvidence:
    payload: dict[str, object] = {
        "version": 1,
        "status": "ready",
        "access_mode": "unauthenticated_public",
        "authentication_mode": "none",
        "content_visibility": "unauthenticated_public",
        "exact_origin": "https://metadata.source.test",
        "path_template": "/works/{source_id}",
        "terms_reference": "offline-terms-review",
        "terms_access_status": "public_unauthenticated_metadata_allowed",
        "terms_reviewed_at": NOW - timedelta(minutes=3),
        "robots_reference": "offline-robots-review",
        "robots_directive_status": "allowed",
        "robots_reviewed_at": NOW - timedelta(minutes=2),
        "response_reviewed_at": NOW - timedelta(minutes=1),
        "credentials_required": False,
        "commercial_use_allowed": False,
        "redistribution_allowed": False,
        "representative_sample_count": 1,
        "observed_content_type": "application/json",
        "observed_fields": set(_payload()),
        "allowed_age_ratings": {"all_ages"},
        "observed_max_body_bytes": 100_000,
        "response_schema_sha256": schema_fingerprint(_payload()),
        "redirects_observed": False,
        "query_parameters_required": False,
        "media_bytes_observed": False,
        "secret_shaped_fields_observed": False,
        "private_or_deleted_content_observed": False,
        "challenge_or_login_observed": False,
    }
    payload.update(changes)
    return AnonymousPublicReviewEvidence.model_validate(payload)


def _contract() -> AnonymousPublicSourceContract:
    return finalize_anonymous_public_contract(
        _evidence(),
        expires_at=NOW + timedelta(days=1),
        now=NOW,
    )


def test_public_contract_is_anonymous_all_ages_and_non_authorizing() -> None:
    contract = _contract()

    assert contract.authentication_mode == "none"
    assert contract.content_visibility == "unauthenticated_public"
    assert contract.authorizes_network is False
    assert contract.credentials_required is False
    assert contract.credential_header is None
    assert contract.allowed_age_ratings == {"all_ages"}
    assert contract.commercial_use_allowed is False
    assert contract.redistribution_allowed is False
    assert contract.concurrency == 1
    assert contract.initial_request_cap == 1
    assert contract.min_request_interval_seconds >= 20
    assert contract.requests_per_minute <= 3
    assert contract.media_download_allowed is False
    assert contract.max_response_body_bytes == 100_000


def test_public_contract_can_bind_reviewed_html_without_persisting_raw_body() -> None:
    contract = finalize_anonymous_public_contract(
        _evidence(observed_content_type="text/html"),
        expires_at=NOW + timedelta(days=1),
        now=NOW,
    )
    gate = AnonymousPublicRequestGate(contract)

    plan = gate.reserve("work-1", now=NOW)

    assert plan.headers[0] == ("Accept", "text/html")
    assert contract.response_schema_sha256 == schema_fingerprint(_payload())


@pytest.mark.parametrize(
    "change",
    [
        {"allowed_age_ratings": {"all_ages", "r18"}},
        {"redirects_observed": True},
        {"query_parameters_required": True},
        {"media_bytes_observed": True},
        {"observed_fields": {"work_id", "image_url"}},
    ],
)
def test_public_evidence_rejects_scope_expansion_or_media(change: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _evidence(**change)


def test_public_contract_rejects_non_exact_origin_and_path() -> None:
    with pytest.raises(ValidationError):
        _evidence(exact_origin="http://metadata.source.test")
    with pytest.raises(ValidationError):
        _evidence(path_template="/works/{source_id}?lang=en")


def test_public_contract_requires_current_terms_and_robots_evidence() -> None:
    evidence = _evidence()
    with pytest.raises(ValueError, match="future"):
        finalize_anonymous_public_contract(
            evidence,
            expires_at=NOW + timedelta(days=1),
            now=NOW - timedelta(minutes=5),
        )

    incomplete = evidence.model_dump()
    del incomplete["robots_reference"]
    with pytest.raises(ValidationError):
        AnonymousPublicReviewEvidence.model_validate(incomplete)


def test_schema_fingerprint_ignores_values_but_detects_shape() -> None:
    same_shape = {**_payload(), "work_title": "Another Synthetic Work", "public_view_count": 99}
    changed_shape = {**_payload(), "public_view_count": "10"}

    assert schema_fingerprint(_payload()) == schema_fingerprint(same_shape)
    assert schema_fingerprint(_payload()) != schema_fingerprint(changed_shape)


def test_gate_only_reserves_a_fixed_no_credential_plan() -> None:
    gate = AnonymousPublicRequestGate(_contract())

    plan = gate.reserve("work/1", now=NOW)

    assert plan.url == "https://metadata.source.test/works/work%2F1"
    assert plan.method == "GET"
    assert plan.headers == (
        ("Accept", "application/json"),
        ("User-Agent", "pyuri-anonymous-public-metadata/1"),
    )
    assert not any(
        "cookie" in key.lower() or "authorization" in key.lower()
        for key, _ in plan.headers
    )
    assert gate.active is True
    assert gate.reservation_count == 1
    gate.complete(plan)
    assert gate.active is False


def test_gate_enforces_delay_then_initial_cap() -> None:
    gate = AnonymousPublicRequestGate(_contract())
    plan = gate.reserve("work-1", now=NOW)
    gate.complete(plan)

    with pytest.raises(AnonymousPublicGateError, match="minimum_interval"):
        gate.reserve("work-2", now=NOW + timedelta(seconds=19))
    with pytest.raises(AnonymousPublicGateError, match="initial_request_cap"):
        gate.reserve("work-2", now=NOW + timedelta(seconds=20))


@pytest.mark.parametrize(
    "reason",
    ["forbidden_403", "rate_limited_429", "challenge_or_login", "schema_drift"],
)
def test_gate_stops_permanently_on_source_safety_signal(reason: str) -> None:
    gate = AnonymousPublicRequestGate(_contract())
    gate.signal_stop(cast(Any, reason))

    with pytest.raises(AnonymousPublicGateError, match=reason):
        gate.reserve("work-1", now=NOW)
    assert gate.stopped_reason == reason


def test_gate_rejects_plan_mismatch_and_invalid_clock() -> None:
    gate = AnonymousPublicRequestGate(_contract())
    plan = gate.reserve("work-1", now=NOW)

    with pytest.raises(AnonymousPublicGateError, match="plan_mismatch"):
        gate.complete(cast(Any, object()))
    with pytest.raises(AnonymousPublicGateError, match="invalid_clock"):
        gate.reserve("work-2", now=datetime(2026, 8, 23))
    gate.abort(plan)
