from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from pixiv_yuri.analytics.tag_review import (
    ReviewedTagAssociationEvidence,
    TagAssociationReviewDecision,
    main,
    tag_candidate_fingerprint,
    validate_tag_review_decision,
)

FIXTURE = Path("config/tag_review_decision.fixture.json")
CHECKED_AT = datetime(2026, 8, 23, 1, tzinfo=UTC)


def _payload() -> dict[str, object]:
    value = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_fixture_decision_is_bound_to_exact_candidate_and_reviewer() -> None:
    report = validate_tag_review_decision(_payload(), now=CHECKED_AT)

    assert report.status == "verified_manual_decision"
    assert report.manual_review_verified is True
    assert report.review_id == "fixture-review-001"
    assert report.reviewer_id == "fixture-reviewer"
    assert report.candidate_fingerprint == (
        "95946b64dcdbbc705356af171d7c0bb2abce43bb6fb9f09164f9a8801f4f16a2"
    )
    assert report.semantic_classification_performed is False
    assert report.real_source_collection_authorized is False
    assert report.external_network_used is False
    assert report.violations == ()


def test_candidate_fingerprint_is_canonical_and_tampering_fails_closed() -> None:
    artifact = TagAssociationReviewDecision.model_validate(_payload())
    reordered = ReviewedTagAssociationEvidence.model_validate(
        dict(reversed(list(artifact.candidate.model_dump().items())))
    )
    assert tag_candidate_fingerprint(reordered) == artifact.candidate_fingerprint

    tampered = _payload()
    candidate = tampered["candidate"]
    assert isinstance(candidate, dict)
    candidate["cooccurrence_work_count"] = 3
    report = validate_tag_review_decision(tampered, now=CHECKED_AT)
    assert report.status == "blocked"
    assert report.violations == ("tag_review_artifact_invalid",)


def test_draft_and_future_decisions_are_not_verified() -> None:
    draft = _payload()
    draft["status"] = "draft"
    draft_report = validate_tag_review_decision(draft, now=CHECKED_AT)

    future = _payload()
    future["reviewed_at"] = "2026-08-24T00:00:00Z"
    future_report = validate_tag_review_decision(future, now=CHECKED_AT)

    assert draft_report.violations == ("tag_review_not_finalized",)
    assert future_report.violations == ("tag_review_time_in_future",)
    assert draft_report.manual_review_verified is False
    assert future_report.manual_review_verified is False


def test_creation_order_and_noncomparable_retention_fail_closed() -> None:
    reversed_time = _payload()
    reversed_time["created_at"] = "2026-08-23T00:01:00Z"
    assert validate_tag_review_decision(reversed_time, now=CHECKED_AT).status == "blocked"

    noncomparable = _payload()
    candidate = noncomparable["candidate"]
    assert isinstance(candidate, dict)
    candidate["stability_comparable"] = False
    evidence = ReviewedTagAssociationEvidence.model_validate(candidate)
    noncomparable["candidate_fingerprint"] = tag_candidate_fingerprint(evidence)
    assert validate_tag_review_decision(noncomparable, now=CHECKED_AT).status == "blocked"


@pytest.mark.parametrize(
    "mutation",
    [
        {"reviewer_id": "tbd"},
        {"rationale": "password=do-not-store this secret-shaped material"},
        {"semantic_classification_performed": True},
        {"real_source_collection_authorized": True},
        {"semantic_label": "yuri"},
        {"session_token": "unsafe"},
    ],
)
def test_unresolved_identity_secret_or_scope_expansion_fails_closed(
    mutation: dict[str, object],
) -> None:
    payload = _payload()
    payload.update(mutation)
    report = validate_tag_review_decision(payload, now=CHECKED_AT)

    assert report.status == "blocked"
    assert report.review_id is None
    assert report.decision is None


@pytest.mark.parametrize(
    "candidate_mutation",
    [
        {"left_tag_name": "synthetic-tag-z"},
        {"right_tag_name": "synthetic-tag-a"},
        {"survives_minimum_cooccurrence": [2]},
        {"survives_minimum_cooccurrence": [1, 1]},
        {"survives_minimum_cooccurrence": [1, 3]},
        {"jaccard_basis_points": 10_001},
    ],
)
def test_noncanonical_or_unbounded_candidate_fails_closed(
    candidate_mutation: dict[str, object],
) -> None:
    payload = _payload()
    candidate = payload["candidate"]
    assert isinstance(candidate, dict)
    candidate.update(candidate_mutation)

    assert validate_tag_review_decision(payload, now=CHECKED_AT).status == "blocked"


def test_cli_writes_minimized_validation_report(tmp_path: Path) -> None:
    output = tmp_path / "report.json"
    exit_code = main(["--artifact", str(FIXTURE), "--output", str(output)])
    report = json.loads(output.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert report["manual_review_verified"] is True
    rendered = json.dumps(report).lower()
    for forbidden in ("rationale", "tag_translation", "password", "token"):
        assert forbidden not in rendered
