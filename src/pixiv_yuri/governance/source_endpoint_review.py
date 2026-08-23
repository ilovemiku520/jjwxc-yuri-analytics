"""Finalize and review a source endpoint contract using local evidence only."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from pixiv_yuri.governance.g0 import G0Approval, approval_fingerprint, load_active_g0_approval
from pixiv_yuri.governance.source_endpoint_contract import (
    SourceEndpointContract,
    SourceEndpointReviewEvidence,
    finalize_source_endpoint_contract,
    review_source_endpoint_contract,
)

_FORBIDDEN_KEYS = frozenset(
    {
        "account_password",
        "authorization",
        "browser_cookie",
        "cookie",
        "credential",
        "deleted_content",
        "hmac_secret",
        "media_bytes",
        "password",
        "private_content",
        "response_body",
        "secret",
        "session_token",
        "signed_url",
        "token",
    }
)


@dataclass(frozen=True, slots=True)
class SourceEndpointReviewReport:
    """Safe readiness evidence; never an authorization capability."""

    generated_at: str
    status: str
    contract_ready: bool
    approval_fingerprint: str | None
    evidence_sha256: str | None
    contract_sha256: str | None
    contract_expires_at: str | None
    violations: tuple[str, ...]
    authorizes_network: bool
    credentials_requested: bool
    external_network_used: bool


def review_source_endpoint_artifact(
    *,
    approval: G0Approval | None,
    evidence_payload: dict[str, Any] | None,
    contract_expires_at: datetime | None,
    now: datetime | None = None,
) -> SourceEndpointReviewReport:
    """Review local endpoint evidence and finalize one non-authorizing contract.

    No endpoint is inferred when evidence is absent.  The evidence payload must be
    the payload-free ``SourceEndpointReviewEvidence`` shape; response bodies,
    credentials and secret-shaped values are rejected before model validation.
    """

    report, _contract = _review_source_endpoint_artifact(
        approval=approval,
        evidence_payload=evidence_payload,
        contract_expires_at=contract_expires_at,
        now=now,
    )
    return report


def _review_source_endpoint_artifact(
    *,
    approval: G0Approval | None,
    evidence_payload: dict[str, Any] | None,
    contract_expires_at: datetime | None,
    now: datetime | None = None,
) -> tuple[SourceEndpointReviewReport, SourceEndpointContract | None]:
    checked_at = _aware_utc(now or datetime.now(UTC))
    approval_hash = approval_fingerprint(approval) if approval is not None else None
    evidence_hash = (
        _safe_sha256(evidence_payload)
        if evidence_payload is not None and not _contains_secret_shape(evidence_payload)
        else None
    )
    violations: list[str] = []
    contract: SourceEndpointContract | None = None

    if approval is None:
        violations.append("g0_approval_missing_or_invalid")
    if evidence_payload is None:
        violations.append("endpoint_evidence_missing")
    expiry_text: str | None = None
    if contract_expires_at is None:
        violations.append("contract_expiry_missing")
    else:
        try:
            expiry_text = _aware_utc(contract_expires_at).isoformat()
        except ValueError:
            violations.append("contract_expiry_invalid")
    if evidence_payload is not None and _contains_secret_shape(evidence_payload):
        violations.append("secret_shaped_endpoint_evidence_forbidden")

    if not violations:
        assert approval is not None
        assert evidence_payload is not None
        assert contract_expires_at is not None
        try:
            evidence = _validate_evidence_payload(evidence_payload)
            contract = finalize_source_endpoint_contract(
                evidence,
                approval,
                expires_at=contract_expires_at,
                now=checked_at,
            )
            review = review_source_endpoint_contract(contract, approval, now=checked_at)
            if review.authorizes_network:
                violations.append("endpoint_review_authorizes_network")
        except ValidationError:
            violations.append("endpoint_evidence_invalid")
        except ValueError:
            violations.append("endpoint_contract_review_rejected")

    if contract is not None and not violations:
        contract_hash = _contract_sha256(contract)
        report = SourceEndpointReviewReport(
            generated_at=checked_at.isoformat(),
            status="ready",
            contract_ready=True,
            approval_fingerprint=approval_hash,
            evidence_sha256=evidence_hash,
            contract_sha256=contract_hash,
            contract_expires_at=expiry_text,
            violations=(),
            authorizes_network=False,
            credentials_requested=False,
            external_network_used=False,
        )
        return report, contract

    report = SourceEndpointReviewReport(
        generated_at=checked_at.isoformat(),
        status="blocked",
        contract_ready=False,
        approval_fingerprint=approval_hash,
        evidence_sha256=evidence_hash,
        contract_sha256=None,
        contract_expires_at=expiry_text,
        violations=tuple(dict.fromkeys(violations)),
        authorizes_network=False,
        credentials_requested=False,
        external_network_used=False,
    )
    return report, None


def _contains_secret_shape(value: object) -> bool:
    if isinstance(value, dict):
        return any(
            _normalize_key(str(key)) in _FORBIDDEN_KEYS or _contains_secret_shape(child)
            for key, child in value.items()
        )
    if isinstance(value, list):
        return any(_contains_secret_shape(child) for child in value)
    if not isinstance(value, str):
        return False
    normalized = value.strip()
    return bool(
        re.search(r"-----BEGIN [A-Z ]*PRIVATE KEY-----", normalized, re.IGNORECASE)
        or re.fullmatch(r"(?i:bearer|basic)\s+\S+", normalized)
        or re.fullmatch(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", normalized)
        or re.search(r"^[a-z][a-z0-9+.-]*://[^/@:]+:[^/@]+@", normalized, re.IGNORECASE)
        or re.search(
            r"(?i)(?:password|secret|token|cookie|authorization)\s*[:=]\s*\S+",
            normalized,
        )
    )


def _normalize_key(value: str) -> str:
    return re.sub(r"[- ]+", "_", value.strip().lower())


def _safe_sha256(value: object) -> str:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            default=_json_default,
        ).encode("utf-8")
    except (TypeError, ValueError):
        return "0" * 64
    return hashlib.sha256(encoded).hexdigest()


def _validate_evidence_payload(payload: dict[str, Any]) -> SourceEndpointReviewEvidence:
    """Validate both native callers and JSON-loaded evidence under strict Pydantic."""
    try:
        return SourceEndpointReviewEvidence.model_validate(payload)
    except ValidationError as native_error:
        try:
            encoded = json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
                default=_json_default,
            )
            return SourceEndpointReviewEvidence.model_validate_json(encoded)
        except (TypeError, ValueError, ValidationError):
            raise native_error from None


def _json_default(value: object) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, set):
        return sorted(value)
    raise TypeError(f"Unsupported JSON value: {type(value).__name__}")


def _contract_sha256(contract: SourceEndpointContract) -> str:
    payload = contract.model_dump(mode="json")
    payload["allowed_fields"] = sorted(contract.allowed_fields)
    payload["allowed_age_ratings"] = sorted(contract.allowed_age_ratings)
    payload["reviewed_at"] = _aware_utc(contract.reviewed_at).isoformat()
    payload["expires_at"] = _aware_utc(contract.expires_at).isoformat()
    return _safe_sha256(payload)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Source endpoint timestamps must include a timezone.")
    return value.astimezone(UTC)


def _load_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("input must be a JSON object")
    return value


def _append_violation(
    report: SourceEndpointReviewReport, violation: str
) -> SourceEndpointReviewReport:
    return replace(
        report,
        status="blocked",
        contract_ready=False,
        contract_sha256=None,
        violations=tuple(dict.fromkeys((*report.violations, violation))),
    )


def _write_report(path: Path, report: SourceEndpointReviewReport) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(asdict(report), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _parse_expiry(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        return _aware_utc(datetime.fromisoformat(value))
    except ValueError:
        return None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--g0", type=Path, default=Path("config/g0_approval.json"))
    parser.add_argument(
        "--evidence",
        type=Path,
        default=Path("config/source_endpoint_review.json"),
        help="Local payload-free SourceEndpointReviewEvidence JSON; no default file is supplied.",
    )
    parser.add_argument(
        "--contract-expires-at",
        help="Explicit timezone-aware ISO-8601 expiry; must not exceed G0 expiry.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("var/reports/source_endpoint_review.json"),
    )
    parser.add_argument("--contract-output", type=Path)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    checked_at = datetime.now(UTC)

    approval: G0Approval | None
    approval_error: str | None = None
    try:
        approval = load_active_g0_approval(args.g0.resolve(), now=checked_at)
    except (OSError, ValueError, ValidationError):
        approval = None
        approval_error = "g0_approval_missing_or_invalid"

    evidence: dict[str, Any] | None
    evidence_error: str | None = None
    try:
        evidence = _load_json_object(args.evidence.resolve())
    except FileNotFoundError:
        evidence = None
    except (OSError, ValueError, json.JSONDecodeError):
        evidence = None
        evidence_error = "endpoint_evidence_invalid"

    expiry = _parse_expiry(args.contract_expires_at)
    expiry_error = None
    if args.contract_expires_at is None:
        expiry_error = "contract_expiry_missing"
    elif expiry is None:
        expiry_error = "contract_expiry_invalid"

    report, contract = _review_source_endpoint_artifact(
        approval=approval,
        evidence_payload=evidence,
        contract_expires_at=expiry,
        now=checked_at,
    )
    for error in (approval_error, evidence_error, expiry_error):
        if error is not None:
            report = _append_violation(report, error)

    if report.contract_ready and contract is not None and args.contract_output is not None:
        if args.contract_output.exists() and not args.force:
            report = _append_violation(report, "contract_output_exists")
        else:
            try:
                args.contract_output.parent.mkdir(parents=True, exist_ok=True)
                args.contract_output.write_text(
                    json.dumps(
                        contract.model_dump(mode="json"),
                        ensure_ascii=False,
                        indent=2,
                        sort_keys=True,
                    )
                    + "\n",
                    encoding="utf-8",
                )
            except OSError:
                report = _append_violation(report, "contract_output_write_failed")

    _write_report(args.output, report)
    stream = sys.stdout if report.status == "ready" else sys.stderr
    print(json.dumps(asdict(report), ensure_ascii=False, sort_keys=True), file=stream)
    return 0 if report.status == "ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())
