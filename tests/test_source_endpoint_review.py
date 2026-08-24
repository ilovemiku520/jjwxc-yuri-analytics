from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import pytest
from pydantic import ValidationError

from pixiv_yuri.governance.g0 import G0Approval
from pixiv_yuri.governance.source_endpoint_contract import SourceEndpointReviewEvidence
from pixiv_yuri.governance.source_endpoint_review import (
    main,
    review_source_endpoint_artifact,
)
from tests.test_g0_governance import valid_approval_payload

NOW = datetime(2026, 8, 23, tzinfo=UTC)


def _approval() -> G0Approval:
    return G0Approval.model_validate(valid_approval_payload())


def _evidence(approval: G0Approval) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "version": 1,
        "status": "ready",
        "reviewer_role": "accountable-owner",
        "exact_origin": "https://metadata.source.test",
        "path_template": "/works/{source_id}",
        "terms_reference": "offline-terms-review",
        "terms_reviewed_at": NOW - timedelta(minutes=2),
        "response_reviewed_at": NOW - timedelta(minutes=1),
        "response_schema_sha256": "a" * 64,
        "representative_sample_count": 1,
        "observed_content_type": "application/json",
        "observed_fields": set(approval.source_scope.allowed_fields),
        "observed_max_body_bytes": 100_000,
        "redirects_observed": False,
        "query_parameters_required": False,
        "media_bytes_observed": False,
        "secret_shaped_fields_observed": False,
        "private_or_deleted_content_observed": False,
    }
    return SourceEndpointReviewEvidence.model_validate(payload).model_dump(mode="json")


def test_complete_local_evidence_is_ready_but_non_authorizing() -> None:
    report = review_source_endpoint_artifact(
        approval=_approval(),
        evidence_payload=_evidence(_approval()),
        contract_expires_at=NOW + timedelta(days=1),
        now=NOW,
    )

    assert report.status == "ready"
    assert report.contract_ready is True
    assert report.contract_sha256 is not None
    assert report.authorizes_network is False
    assert report.credentials_requested is False
    assert report.external_network_used is False
    assert report.violations == ()


def test_missing_exact_evidence_is_blocked_without_inventing_endpoint() -> None:
    report = review_source_endpoint_artifact(
        approval=_approval(),
        evidence_payload=None,
        contract_expires_at=NOW + timedelta(days=1),
        now=NOW,
    )

    assert report.status == "blocked"
    assert report.contract_ready is False
    assert "endpoint_evidence_missing" in report.violations
    assert report.contract_sha256 is None
    assert report.authorizes_network is False


def test_missing_expiry_is_blocked() -> None:
    report = review_source_endpoint_artifact(
        approval=_approval(),
        evidence_payload=_evidence(_approval()),
        contract_expires_at=None,
        now=NOW,
    )

    assert report.status == "blocked"
    assert "contract_expiry_missing" in report.violations
    assert report.authorizes_network is False


def test_naive_expiry_is_blocked_without_raising() -> None:
    report = review_source_endpoint_artifact(
        approval=_approval(),
        evidence_payload=_evidence(_approval()),
        contract_expires_at=datetime(2026, 8, 24),
        now=NOW,
    )

    assert report.status == "blocked"
    assert "contract_expiry_invalid" in report.violations
    assert report.authorizes_network is False


def test_secret_or_response_body_evidence_is_rejected_without_echo() -> None:
    evidence = _evidence(_approval())
    evidence["response_body"] = "must-not-be-stored"

    report = review_source_endpoint_artifact(
        approval=_approval(),
        evidence_payload=evidence,
        contract_expires_at=NOW + timedelta(days=1),
        now=NOW,
    )

    assert report.status == "blocked"
    assert report.violations == ("secret_shaped_endpoint_evidence_forbidden",)
    assert report.evidence_sha256 is None
    assert "must-not-be-stored" not in json.dumps(asdict(report), default=str)


def test_field_expansion_and_expiry_beyond_g0_are_blocked() -> None:
    evidence = _evidence(_approval())
    evidence["observed_fields"].append("unapproved_field")
    report = review_source_endpoint_artifact(
        approval=_approval(),
        evidence_payload=evidence,
        contract_expires_at=NOW + timedelta(days=1),
        now=NOW,
    )
    assert report.status == "blocked"
    assert "endpoint_contract_review_rejected" in report.violations

    valid = _evidence(_approval())
    expired_report = review_source_endpoint_artifact(
        approval=_approval(),
        evidence_payload=valid,
        contract_expires_at=datetime(2026, 9, 22, tzinfo=UTC),
        now=NOW,
    )
    assert expired_report.status == "blocked"
    assert "endpoint_contract_review_rejected" in expired_report.violations


def test_invalid_g0_is_blocked() -> None:
    report = review_source_endpoint_artifact(
        approval=None,
        evidence_payload=None,
        contract_expires_at=NOW + timedelta(days=1),
        now=NOW,
    )

    assert report.status == "blocked"
    assert "g0_approval_missing_or_invalid" in report.violations
    assert "endpoint_evidence_missing" in report.violations
    assert report.authorizes_network is False


def test_cli_missing_default_evidence_writes_machine_blocked_report() -> None:
    with TemporaryDirectory(dir=Path.cwd() / ".tmp") as directory:
        root = Path(directory)
        report_path = root / "source-endpoint-review.json"
        exit_code = main(
            [
                "--g0",
                "config/g0_approval.json",
                "--evidence",
                str(root / "missing-evidence.json"),
                "--contract-expires-at",
                "2026-08-25T00:00:00+00:00",
                "--output",
                str(report_path),
            ]
        )

        assert exit_code == 2
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["status"] == "blocked"
        assert report["violations"] == ["endpoint_evidence_missing"]
        assert report["authorizes_network"] is False
        assert report["credentials_requested"] is False


def test_cli_finalizes_from_local_json_without_network() -> None:
    with TemporaryDirectory(dir=Path.cwd() / ".tmp") as directory:
        root = Path(directory)
        g0_path = root / "g0.json"
        evidence_path = root / "evidence.json"
        report_path = root / "report.json"
        contract_path = root / "contract.json"
        g0_path.write_text(
            json.dumps(valid_approval_payload()), encoding="utf-8"
        )
        evidence_path.write_text(
            json.dumps(_evidence(_approval())), encoding="utf-8"
        )

        exit_code = main(
            [
                "--g0",
                str(g0_path),
                "--evidence",
                str(evidence_path),
                "--contract-expires-at",
                "2026-08-25T00:00:00+00:00",
                "--output",
                str(report_path),
                "--contract-output",
                str(contract_path),
            ]
        )

        assert exit_code == 0
        report = json.loads(report_path.read_text(encoding="utf-8"))
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        assert report["status"] == "ready"
        assert report["authorizes_network"] is False
        assert report["external_network_used"] is False
        assert contract["credential_header"] == "Cookie"


def test_evidence_model_still_rejects_unknown_fields() -> None:
    evidence = _evidence(_approval())
    evidence["response_body"] = "unknown"
    with pytest.raises(ValidationError):
        SourceEndpointReviewEvidence.model_validate(evidence)
