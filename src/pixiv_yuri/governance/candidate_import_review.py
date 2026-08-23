"""Fail-closed manual review for sanitized browser-export candidate metadata."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from pixiv_yuri.acquisition.browser_export_import import SanitizedPublicMetadata
from pixiv_yuri.governance.g0 import approval_fingerprint, load_active_g0_approval

_IDENTIFIER = re.compile(r"^[A-Za-z0-9@._+-]{2,100}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SECRET_SHAPE = re.compile(
    r"(?i)(?:authorization|cookie|password|secret|session[_-]?token|access[_-]?token)\s*[:=]"
)


class CandidateImportEvidence(BaseModel):
    """Strict value-free evidence emitted by the local browser-export sanitizer."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    generated_at: datetime
    status: Literal["candidate_ready"]
    source_format: Literal[
        "powerful_pixiv_downloader_json",
        "pyuri_pixiv_browser_companion_json",
    ]
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_files: int = Field(default=1, ge=1, le=25)
    input_records: int = Field(ge=1, le=1_000)
    accepted_records: int = Field(ge=1, le=1_000)
    rejected_records: Literal[0]
    duplicate_or_extra_page_records: int = Field(ge=0, le=1_000)
    violations: tuple[str, ...] = Field(default=(), max_length=0)
    visibility_verified: Literal[False]
    canonical_ingest_authorized: Literal[False]
    credentials_requested: Literal[False]
    external_network_used: Literal[False]
    media_persisted: Literal[False]
    raw_payload_persisted: Literal[False]

    @field_validator("generated_at")
    @classmethod
    def timestamp_must_be_aware(cls, value: datetime) -> datetime:
        return _aware_utc(value, "import evidence timestamp")


class AppApiCandidateEvidence(BaseModel):
    """Strict value-free evidence emitted by the bounded Pixiv App API collector."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    generated_at: datetime
    status: Literal["candidate_ready"]
    operation: Literal["search_illust", "user_illusts", "illust_ranking"]
    authentication_mode: Literal["oauth_pkce", "runtime_refresh_token"]
    requested_pages: int = Field(ge=1, le=100)
    input_records: int = Field(ge=1, le=3_000)
    candidate_records: int = Field(ge=1, le=3_000)
    duplicate_records: int = Field(ge=0, le=3_000)
    skipped_records: int = Field(ge=0, le=3_000)
    external_network_used: Literal[True]
    oauth_authorization_code_requested: bool
    refresh_token_requested: bool
    password_requested: Literal[False]
    secret_persisted: Literal[False]
    raw_payload_persisted: Literal[False]
    media_persisted: Literal[False]
    automatic_retries: Literal[0]
    network_concurrency: Literal[1]
    canonical_ingest_authorized: Literal[False]
    violations: tuple[str, ...] = Field(default=(), max_length=0)

    @field_validator("generated_at")
    @classmethod
    def timestamp_must_be_aware(cls, value: datetime) -> datetime:
        return _aware_utc(value, "App API evidence timestamp")

    @model_validator(mode="after")
    def counts_and_authentication_must_be_consistent(self) -> AppApiCandidateEvidence:
        if self.input_records != (
            self.candidate_records + self.duplicate_records + self.skipped_records
        ):
            raise ValueError("App API evidence counts are inconsistent")
        expected_oauth = self.authentication_mode == "oauth_pkce"
        if (
            self.oauth_authorization_code_requested is not expected_oauth
            or self.refresh_token_requested is expected_oauth
        ):
            raise ValueError("App API authentication evidence is inconsistent")
        return self


class CandidateVisibilityReview(BaseModel):
    """A human-only, expiring assertion about one exact sanitized candidate file."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact_type: Literal["candidate_visibility_review"]
    version: Literal[1]
    status: Literal["finalized"]
    review_id: str = Field(min_length=2, max_length=100)
    reviewer_id: str = Field(min_length=2, max_length=100)
    reviewer_role: Literal["accountable_human_reviewer"]
    created_at: datetime
    reviewed_at: datetime
    expires_at: datetime
    g0_approval_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    import_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_record_count: int = Field(ge=1, le=3_000)
    visibility_observation: Literal["manual_browser_observation"]
    all_records_observed_as_authenticated_public: Literal[True]
    observed_age_ratings: set[Literal["all_ages", "r18", "r18g"]] = Field(
        min_length=1, max_length=3
    )
    review_reference: str = Field(min_length=10, max_length=500)
    canonical_ingest_requested: Literal[True]
    credentials_requested: Literal[False]
    external_network_used: Literal[False]
    media_persisted: Literal[False]
    raw_payload_persisted: Literal[False]

    @field_validator("review_id", "reviewer_id")
    @classmethod
    def identifier_must_be_safe(cls, value: str) -> str:
        if _IDENTIFIER.fullmatch(value) is None or value.strip().lower() in {
            "draft",
            "placeholder",
            "todo",
            "unknown",
        }:
            raise ValueError("review identity is unresolved or invalid")
        return value

    @field_validator("created_at", "reviewed_at", "expires_at")
    @classmethod
    def timestamps_must_be_aware(cls, value: datetime) -> datetime:
        return _aware_utc(value, "review timestamp")

    @field_validator("review_reference")
    @classmethod
    def reference_must_not_leak_source_or_secret(cls, value: str) -> str:
        if "://" in value or _SECRET_SHAPE.search(value):
            raise ValueError("review reference must not contain a URL or secret-shaped material")
        return value

    @model_validator(mode="after")
    def review_window_must_be_bounded(self) -> CandidateVisibilityReview:
        if self.created_at > self.reviewed_at:
            raise ValueError("review cannot precede artifact creation")
        if (
            self.expires_at <= self.reviewed_at
            or self.expires_at - self.reviewed_at > timedelta(days=7)
        ):
            raise ValueError("candidate review must expire within seven days")
        return self


class ReviewedEndpointStatus(BaseModel):
    """Safe subset of the independent endpoint-review report."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    generated_at: datetime
    status: Literal["ready"]
    contract_ready: Literal[True]
    approval_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    contract_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    contract_expires_at: datetime
    authorizes_network: Literal[False]
    credentials_requested: Literal[False]
    external_network_used: Literal[False]
    violations: tuple[str, ...] = Field(default=(), max_length=0)

    @field_validator("generated_at", "contract_expires_at")
    @classmethod
    def expiry_must_be_aware(cls, value: datetime) -> datetime:
        return _aware_utc(value, "endpoint contract expiry")


@dataclass(frozen=True, slots=True)
class CandidateImportReviewReport:
    """Non-secret result; authorization is false unless every independent bind succeeds."""

    generated_at: str
    status: str
    import_report_sha256: str | None
    candidate_file_sha256: str | None
    candidate_record_count: int
    review_id: str | None
    reviewer_id: str | None
    g0_approval_fingerprint: str | None
    source_contract_sha256: str | None
    manual_visibility_review_verified: bool
    source_endpoint_contract_ready: bool
    canonical_ingest_authorized: bool
    credentials_requested: bool
    external_network_used: bool
    media_persisted: bool
    raw_payload_persisted: bool
    violations: tuple[str, ...]


def review_candidate_import(
    *,
    candidate_bytes: bytes,
    import_report_payload: dict[str, Any],
    review_payload: dict[str, Any],
    endpoint_report_payload: dict[str, Any] | None,
    active_g0_fingerprint: str | None,
    now: datetime | None = None,
) -> CandidateImportReviewReport:
    """Bind local output to human review, G0 and an independently reviewed endpoint.

    This function performs no I/O beyond the values passed to it, does not trust raw
    browser exports, and does not insert candidate records anywhere.
    """
    checked_at = _aware_utc(now or datetime.now(UTC), "review time")
    candidate_hash = hashlib.sha256(candidate_bytes).hexdigest()
    import_hash = _sha256_json(import_report_payload)
    violations: list[str] = []
    candidate_count = 0
    evidence: CandidateImportEvidence | AppApiCandidateEvidence | None = None
    review: CandidateVisibilityReview | None = None
    endpoint: ReviewedEndpointStatus | None = None

    try:
        candidates = _load_candidates(candidate_bytes)
        candidate_count = len(candidates)
    except (UnicodeDecodeError, ValueError, ValidationError):
        violations.append("sanitized_candidate_file_invalid")
        candidates = ()

    try:
        if import_report_payload.get("authentication_mode") in {
            "oauth_pkce",
            "runtime_refresh_token",
        }:
            evidence = AppApiCandidateEvidence.model_validate(import_report_payload)
        else:
            evidence = CandidateImportEvidence.model_validate(import_report_payload)
    except ValidationError:
        violations.append("candidate_import_evidence_invalid")
    try:
        review = CandidateVisibilityReview.model_validate(review_payload)
    except ValidationError:
        violations.append("candidate_visibility_review_invalid")
    if endpoint_report_payload is None:
        violations.append("reviewed_source_endpoint_contract_missing")
    else:
        try:
            endpoint = ReviewedEndpointStatus.model_validate(endpoint_report_payload)
        except ValidationError:
            violations.append("reviewed_source_endpoint_contract_invalid")
    if active_g0_fingerprint is None or _SHA256.fullmatch(active_g0_fingerprint) is None:
        violations.append("active_g0_approval_missing_or_invalid")

    if evidence is not None:
        evidence_count = (
            evidence.candidate_records
            if isinstance(evidence, AppApiCandidateEvidence)
            else evidence.accepted_records
        )
        if candidate_count != evidence_count:
            violations.append("candidate_record_count_mismatch")
    if (
        evidence is not None
        and isinstance(evidence, CandidateImportEvidence)
        and review is not None
        and evidence.source_format == "powerful_pixiv_downloader_json"
        and review.observed_age_ratings != {"all_ages"}
    ):
        violations.append("candidate_rating_review_outside_source_scope")
    if review is not None:
        if review.import_report_sha256 != import_hash:
            violations.append("candidate_import_report_unbound")
        if review.candidate_file_sha256 != candidate_hash:
            violations.append("candidate_file_unbound")
        if review.candidate_record_count != candidate_count:
            violations.append("candidate_count_unbound")
        if review.reviewed_at > checked_at or review.expires_at <= checked_at:
            violations.append("candidate_visibility_review_expired_or_future")
        if (
            active_g0_fingerprint is not None
            and review.g0_approval_fingerprint != active_g0_fingerprint
        ):
            violations.append("candidate_review_g0_fingerprint_mismatch")
    if endpoint is not None:
        if endpoint.contract_expires_at <= checked_at:
            violations.append("reviewed_source_endpoint_contract_expired")
        if (
            active_g0_fingerprint is not None
            and endpoint.approval_fingerprint != active_g0_fingerprint
        ):
            violations.append("source_endpoint_g0_fingerprint_mismatch")

    authorized = not violations
    return CandidateImportReviewReport(
        generated_at=checked_at.isoformat(),
        status="authorized_for_canonical_ingest" if authorized else "blocked",
        import_report_sha256=import_hash if evidence is not None else None,
        candidate_file_sha256=candidate_hash if candidates else None,
        candidate_record_count=candidate_count,
        review_id=review.review_id if review is not None else None,
        reviewer_id=review.reviewer_id if review is not None else None,
        g0_approval_fingerprint=active_g0_fingerprint,
        source_contract_sha256=endpoint.contract_sha256 if endpoint is not None else None,
        manual_visibility_review_verified=review is not None and not any(
            violation.startswith("candidate_") for violation in violations
        ),
        source_endpoint_contract_ready=endpoint is not None and not any(
            violation.startswith("reviewed_source") or violation.startswith("source_endpoint")
            for violation in violations
        ),
        canonical_ingest_authorized=authorized,
        credentials_requested=False,
        external_network_used=False,
        media_persisted=False,
        raw_payload_persisted=False,
        violations=tuple(dict.fromkeys(violations)),
    )


def _load_candidates(candidate_bytes: bytes) -> tuple[SanitizedPublicMetadata, ...]:
    lines = [line for line in candidate_bytes.decode("utf-8-sig").splitlines() if line.strip()]
    if not lines or len(lines) > 3_000:
        raise ValueError("candidate line count is outside the bounded range")
    records = tuple(SanitizedPublicMetadata.model_validate_json(line) for line in lines)
    if len({record.work_id for record in records}) != len(records):
        raise ValueError("candidate work identifiers must be unique")
    return records


def _aware_utc(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must include a timezone")
    return value.astimezone(UTC)


def _sha256_json(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("input must be a JSON object")
    return value


def _write_report(path: Path, report: CandidateImportReviewReport) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(asdict(report), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--candidate", type=Path, required=True, help="Sanitized JSONL candidate output."
    )
    parser.add_argument("--import-report", type=Path, required=True)
    parser.add_argument("--review-artifact", type=Path, required=True)
    parser.add_argument("--source-endpoint-review", type=Path, required=True)
    parser.add_argument("--g0", type=Path, default=Path("config/g0_approval.json"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    checked_at = datetime.now(UTC)
    try:
        active_fingerprint = approval_fingerprint(
            load_active_g0_approval(args.g0.resolve(), now=checked_at)
        )
    except (OSError, ValueError, ValidationError):
        active_fingerprint = None
    try:
        report = review_candidate_import(
            candidate_bytes=args.candidate.read_bytes(),
            import_report_payload=_load_object(args.import_report),
            review_payload=_load_object(args.review_artifact),
            endpoint_report_payload=_load_object(args.source_endpoint_review),
            active_g0_fingerprint=active_fingerprint,
            now=checked_at,
        )
    except (OSError, ValueError, json.JSONDecodeError):
        report = CandidateImportReviewReport(
            generated_at=checked_at.isoformat(),
            status="blocked",
            import_report_sha256=None,
            candidate_file_sha256=None,
            candidate_record_count=0,
            review_id=None,
            reviewer_id=None,
            g0_approval_fingerprint=active_fingerprint,
            source_contract_sha256=None,
            manual_visibility_review_verified=False,
            source_endpoint_contract_ready=False,
            canonical_ingest_authorized=False,
            credentials_requested=False,
            external_network_used=False,
            media_persisted=False,
            raw_payload_persisted=False,
            violations=("candidate_review_input_invalid",),
        )
    _write_report(args.output, report)
    stream = sys.stdout if report.canonical_ingest_authorized else sys.stderr
    print(json.dumps(asdict(report), ensure_ascii=False, sort_keys=True), file=stream)
    return 0 if report.canonical_ingest_authorized else 2


if __name__ == "__main__":
    raise SystemExit(main())
