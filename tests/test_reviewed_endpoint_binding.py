from __future__ import annotations

from datetime import UTC, datetime

import pytest

from pixiv_yuri.acquisition.live_request_binding import CanonicalLiveRequestBinding
from pixiv_yuri.acquisition.models import AcquisitionRequest, EntityType
from pixiv_yuri.governance.g0 import G0Approval, approval_fingerprint
from pixiv_yuri.governance.reviewed_endpoint_binding import (
    bind_reviewed_endpoint_request,
)
from tests.test_g0_governance import valid_approval_payload
from tests.test_source_endpoint_contract import build_contract

NOW = datetime(2026, 8, 23, tzinfo=UTC)


def binding_for(
    approval: G0Approval,
    *,
    source_id: str = "42",
    url: str = "https://metadata.source.test/works/42",
) -> CanonicalLiveRequestBinding:
    return CanonicalLiveRequestBinding.from_request(
        approval_fingerprint=approval_fingerprint(approval),
        provider_id="pinned_metadata_local_contract",
        request=AcquisitionRequest(entity_type=EntityType.WORK, source_id=source_id),
        exact_url=url,
    )


def test_exact_rendered_url_is_bound_without_authorizing_network() -> None:
    approval = G0Approval.model_validate(valid_approval_payload())
    contract = build_contract(approval)

    evidence = bind_reviewed_endpoint_request(
        contract,
        approval,
        binding_for(approval),
        now=NOW,
    )

    assert evidence.status == "passed"
    assert len(evidence.contract_fingerprint) == 64
    assert evidence.request_binding_hash == binding_for(approval).binding_hash
    assert evidence.authorizes_network is False


@pytest.mark.parametrize(
    "url",
    [
        "https://metadata.source.test/works/43",
        "https://other.source.test/works/42",
        "https://metadata.source.test/authors/42",
    ],
)
def test_origin_path_or_identity_substitution_is_rejected(url: str) -> None:
    approval = G0Approval.model_validate(valid_approval_payload())

    with pytest.raises(ValueError, match="reviewed endpoint"):
        bind_reviewed_endpoint_request(
            build_contract(approval),
            approval,
            binding_for(approval, url=url),
            now=NOW,
        )


def test_source_id_is_percent_encoded_exactly_once() -> None:
    approval = G0Approval.model_validate(valid_approval_payload())
    binding = binding_for(
        approval,
        source_id="a/b",
        url="https://metadata.source.test/works/a%2Fb",
    )

    evidence = bind_reviewed_endpoint_request(
        build_contract(approval), approval, binding, now=NOW
    )

    assert evidence.request_binding_hash == binding.binding_hash


def test_contract_fingerprint_is_deterministic_for_unordered_scopes() -> None:
    approval = G0Approval.model_validate(valid_approval_payload())
    first = build_contract(approval)
    second = build_contract(
        approval,
        allowed_fields=set(reversed(sorted(first.allowed_fields))),
        allowed_age_ratings=set(reversed(sorted(first.allowed_age_ratings))),
    )

    first_evidence = bind_reviewed_endpoint_request(
        first, approval, binding_for(approval), now=NOW
    )
    second_evidence = bind_reviewed_endpoint_request(
        second, approval, binding_for(approval), now=NOW
    )

    assert first_evidence.contract_fingerprint == second_evidence.contract_fingerprint
