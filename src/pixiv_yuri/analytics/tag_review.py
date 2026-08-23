"""Validate reviewer-attributed decisions over exact offline association evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

_IDENTIFIER = re.compile(r"^[A-Za-z0-9@._+-]{2,100}$")
_PLACEHOLDERS = frozenset({"change-me", "draft", "placeholder", "tbd", "todo", "unknown"})
_SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)(?:authorization|cookie|password|secret|session[_-]?token|access[_-]?token)\s*[:=]"
)


class ReviewedTagAssociationEvidence(BaseModel):
    """The exact bounded statistics shown to a human reviewer."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sampled_work_count: int = Field(ge=1, le=5_000)
    anchor_tag: str | None = Field(default=None, min_length=1, max_length=255)
    thresholds: tuple[int, ...] = Field(min_length=1, max_length=8)
    baseline_result_truncated: bool
    stability_comparable: bool
    left_tag_name: str = Field(min_length=1, max_length=255)
    left_tag_translation: str | None = Field(default=None, max_length=255)
    right_tag_name: str = Field(min_length=1, max_length=255)
    right_tag_translation: str | None = Field(default=None, max_length=255)
    cooccurrence_work_count: int = Field(ge=1, le=5_000)
    sample_support_basis_points: int = Field(ge=0, le=10_000)
    jaccard_basis_points: int = Field(ge=0, le=10_000)
    pmi_milli_bits: int = Field(ge=-100_000, le=100_000)
    survives_minimum_cooccurrence: tuple[int, ...] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def validate_canonical_evidence(self) -> ReviewedTagAssociationEvidence:
        if self.left_tag_name >= self.right_tag_name:
            raise ValueError("tag evidence must use distinct canonical tag order")
        if self.thresholds[0] != 1 or self.thresholds != tuple(
            sorted(set(self.thresholds))
        ):
            raise ValueError("report thresholds must start at 1 and strictly increase")
        if self.thresholds[-1] > 5_000:
            raise ValueError("report threshold exceeds the sample bound")
        thresholds = self.survives_minimum_cooccurrence
        if thresholds[0] != 1 or thresholds != tuple(sorted(set(thresholds))):
            raise ValueError("surviving thresholds must start at 1 and strictly increase")
        if thresholds[-1] > 5_000:
            raise ValueError("surviving threshold exceeds the sample bound")
        if thresholds[-1] > self.cooccurrence_work_count:
            raise ValueError("an edge cannot survive above its cooccurrence count")
        if not set(thresholds).issubset(self.thresholds):
            raise ValueError("surviving thresholds must belong to the report thresholds")
        return self


class TagAssociationReviewDecision(BaseModel):
    """One manual triage decision; it is deliberately not a semantic label."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact_type: Literal["tag_association_review_decision"]
    version: Literal[1]
    status: Literal["draft", "finalized"]
    review_id: str = Field(min_length=2, max_length=100)
    reviewer_id: str = Field(min_length=2, max_length=100)
    reviewer_role: Literal["human_reviewer"]
    created_at: datetime
    reviewed_at: datetime
    candidate_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate: ReviewedTagAssociationEvidence
    decision: Literal[
        "retain_for_followup",
        "defer_insufficient_evidence",
        "dismiss_statistical_artifact",
    ]
    rationale: str = Field(min_length=10, max_length=500)
    semantic_classification_performed: Literal[False]
    real_source_collection_authorized: Literal[False]
    external_network_used: Literal[False]

    @field_validator("review_id", "reviewer_id")
    @classmethod
    def validate_identifier(cls, value: str) -> str:
        if _IDENTIFIER.fullmatch(value) is None or value.strip().lower() in _PLACEHOLDERS:
            raise ValueError("review identity is unresolved or invalid")
        return value

    @field_validator("created_at", "reviewed_at")
    @classmethod
    def validate_reviewed_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("reviewed_at must include a timezone")
        return value.astimezone(UTC)

    @field_validator("rationale")
    @classmethod
    def reject_secret_shaped_rationale(cls, value: str) -> str:
        if _SENSITIVE_ASSIGNMENT.search(value):
            raise ValueError("rationale contains secret-shaped material")
        return value

    @model_validator(mode="after")
    def candidate_must_match_fingerprint(self) -> TagAssociationReviewDecision:
        if self.candidate_fingerprint != tag_candidate_fingerprint(self.candidate):
            raise ValueError("candidate fingerprint does not match the reviewed evidence")
        if self.created_at > self.reviewed_at:
            raise ValueError("review cannot precede artifact creation")
        if self.decision == "retain_for_followup" and (
            self.candidate.baseline_result_truncated
            or not self.candidate.stability_comparable
        ):
            raise ValueError("non-comparable evidence cannot be retained for followup")
        return self


@dataclass(frozen=True, slots=True)
class TagReviewValidationReport:
    generated_at: str
    status: str
    artifact_sha256: str
    review_id: str | None
    reviewer_id: str | None
    candidate_fingerprint: str | None
    decision: str | None
    manual_review_verified: bool
    semantic_classification_performed: bool
    real_source_collection_authorized: bool
    external_network_used: bool
    violations: tuple[str, ...]


def tag_candidate_fingerprint(candidate: ReviewedTagAssociationEvidence) -> str:
    """Bind a decision to one exact canonical candidate evidence object."""
    encoded = json.dumps(
        candidate.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_tag_review_decision(
    payload: dict[str, Any], *, now: datetime | None = None
) -> TagReviewValidationReport:
    """Validate one manual artifact without assigning a label or performing I/O."""
    checked_at = _aware_utc(now or datetime.now(UTC))
    artifact_sha256 = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode(
            "utf-8"
        )
    ).hexdigest()
    try:
        artifact = TagAssociationReviewDecision.model_validate(payload)
    except ValidationError:
        return _blocked_report(
            checked_at=checked_at,
            artifact_sha256=artifact_sha256,
            violations=("tag_review_artifact_invalid",),
        )

    violations: list[str] = []
    if artifact.status != "finalized":
        violations.append("tag_review_not_finalized")
    if artifact.reviewed_at > checked_at:
        violations.append("tag_review_time_in_future")
    verified = not violations
    return TagReviewValidationReport(
        generated_at=checked_at.isoformat(),
        status="verified_manual_decision" if verified else "blocked",
        artifact_sha256=artifact_sha256,
        review_id=artifact.review_id,
        reviewer_id=artifact.reviewer_id,
        candidate_fingerprint=artifact.candidate_fingerprint,
        decision=artifact.decision,
        manual_review_verified=verified,
        semantic_classification_performed=False,
        real_source_collection_authorized=False,
        external_network_used=False,
        violations=tuple(violations),
    )


def _blocked_report(
    *, checked_at: datetime, artifact_sha256: str, violations: tuple[str, ...]
) -> TagReviewValidationReport:
    return TagReviewValidationReport(
        generated_at=checked_at.isoformat(),
        status="blocked",
        artifact_sha256=artifact_sha256,
        review_id=None,
        reviewer_id=None,
        candidate_fingerprint=None,
        decision=None,
        manual_review_verified=False,
        semantic_classification_performed=False,
        real_source_collection_authorized=False,
        external_network_used=False,
        violations=violations,
    )


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("validation time must include a timezone")
    return value.astimezone(UTC)


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("tag review input must be a JSON object")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument(
        "--output", type=Path, default=Path("var/reports/tag_review_validation.json")
    )
    args = parser.parse_args(argv)
    try:
        report = validate_tag_review_decision(_load_object(args.artifact))
    except (OSError, ValueError, json.JSONDecodeError):
        report = _blocked_report(
            checked_at=datetime.now(UTC),
            artifact_sha256="0" * 64,
            violations=("tag_review_input_invalid",),
        )
    output = asdict(report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    stream = sys.stdout if report.manual_review_verified else sys.stderr
    print(json.dumps(output, ensure_ascii=False, sort_keys=True), file=stream)
    return 0 if report.manual_review_verified else 2


if __name__ == "__main__":
    raise SystemExit(main())
