"""Bind one canonical live request to a freshly revalidated endpoint contract."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Literal
from urllib.parse import quote

from pixiv_yuri.acquisition.live_request_binding import (
    CanonicalLiveRequestBinding,
    normalize_exact_https_url,
)
from pixiv_yuri.governance.g0 import G0Approval
from pixiv_yuri.governance.source_endpoint_contract import (
    SourceEndpointContract,
    review_source_endpoint_contract,
)


@dataclass(frozen=True, slots=True)
class ReviewedEndpointRequestEvidence:
    """Non-authorizing evidence for one exact contract/request match."""

    status: Literal["passed"]
    contract_fingerprint: str
    request_binding_hash: str
    checked_at: datetime
    authorizes_network: Literal[False]


def bind_reviewed_endpoint_request(
    contract: SourceEndpointContract,
    approval: G0Approval,
    binding: CanonicalLiveRequestBinding,
    *,
    now: datetime,
) -> ReviewedEndpointRequestEvidence:
    """Freshly revalidate G0 and require the exact rendered contract URL."""
    checked_at = _aware_utc(now)
    review = review_source_endpoint_contract(contract, approval, now=checked_at)
    if binding.approval_fingerprint != review.approval_fingerprint:
        raise ValueError("Canonical request is bound to a different approval.")
    rendered_path = contract.path_template.replace(
        "{source_id}", quote(binding.source_id, safe="")
    )
    expected_url = normalize_exact_https_url(
        f"{contract.origin.rstrip('/')}{rendered_path}"
    )
    if binding.canonical_url != expected_url:
        raise ValueError("Canonical request does not match the reviewed endpoint.")
    return ReviewedEndpointRequestEvidence(
        status="passed",
        contract_fingerprint=_contract_fingerprint(contract),
        request_binding_hash=binding.binding_hash,
        checked_at=checked_at,
        authorizes_network=False,
    )


def _contract_fingerprint(contract: SourceEndpointContract) -> str:
    payload = contract.model_dump(mode="json")
    payload["allowed_fields"] = sorted(contract.allowed_fields)
    payload["allowed_age_ratings"] = sorted(contract.allowed_age_ratings)
    payload["reviewed_at"] = _aware_utc(contract.reviewed_at).isoformat()
    payload["expires_at"] = _aware_utc(contract.expires_at).isoformat()
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return sha256(canonical).hexdigest()


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Reviewed endpoint timestamps must include a timezone.")
    return value.astimezone(UTC)
