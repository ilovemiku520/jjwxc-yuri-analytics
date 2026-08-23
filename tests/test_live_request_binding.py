"""Tests for the versioned exact live-request identity."""

from __future__ import annotations

import json
from hashlib import sha256

import pytest
from pydantic import ValidationError

from pixiv_yuri.acquisition.live_request_binding import (
    CanonicalLiveRequestBinding,
    normalize_exact_https_url,
)
from pixiv_yuri.acquisition.models import AcquisitionRequest, EntityType

APPROVAL_FINGERPRINT = "a" * 64


def _binding(
    *,
    approval_fingerprint: str = APPROVAL_FINGERPRINT,
    provider_id: str = "pinned_metadata",
    entity_type: EntityType = EntityType.WORK,
    source_id: str = "42",
    exact_url: str = "https://metadata.pixiv.test/works/42",
) -> CanonicalLiveRequestBinding:
    return CanonicalLiveRequestBinding.from_request(
        approval_fingerprint=approval_fingerprint,
        provider_id=provider_id,
        request=AcquisitionRequest(entity_type=entity_type, source_id=source_id),
        exact_url=exact_url,
    )


def test_binding_is_immutable_and_has_deterministic_canonical_json() -> None:
    binding = _binding()

    assert json.loads(binding.canonical_json) == {
        "approval_fingerprint": APPROVAL_FINGERPRINT,
        "canonical_url": "https://metadata.pixiv.test/works/42",
        "entity_type": "work",
        "provider_id": "pinned_metadata",
        "source_id": "42",
        "version": 1,
    }
    assert binding.canonical_json == (
        b'{"approval_fingerprint":"'
        + APPROVAL_FINGERPRINT.encode()
        + b'","canonical_url":"https://metadata.pixiv.test/works/42",'
        b'"entity_type":"work","provider_id":"pinned_metadata",'
        b'"source_id":"42","version":1}'
    )
    assert len(binding.binding_hash) == 64
    assert sha256(binding.request_key.encode("utf-8")).hexdigest() == binding.binding_hash

    with pytest.raises(ValidationError, match="frozen"):
        binding.provider_id = "other_provider"


def test_url_normalization_produces_the_same_binding() -> None:
    noncanonical = _binding(
        exact_url="HTTPS://Metadata.Pixiv.Test:443/works/%7euser/%2fasset"
    )
    canonical = _binding(
        exact_url="https://metadata.pixiv.test/works/~user/%2Fasset"
    )

    assert noncanonical.canonical_url == canonical.canonical_url
    assert noncanonical.canonical_json == canonical.canonical_json
    assert noncanonical.binding_hash == canonical.binding_hash
    assert normalize_exact_https_url("https://metadata.pixiv.test") == (
        "https://metadata.pixiv.test/"
    )


def test_canonical_json_prevents_colon_delimiter_collisions() -> None:
    left = _binding(
        provider_id="p",
        source_id="x:https://h.test/a",
        exact_url="https://h.test/b",
    )
    right = _binding(
        provider_id="p",
        source_id="x",
        exact_url="https://h.test/a:https://h.test/b",
    )

    def unsafe_delimited(binding: CanonicalLiveRequestBinding) -> str:
        return (
            f"{binding.provider_id}:{binding.entity_type.value}:"
            f"{binding.source_id}:{binding.canonical_url}"
        )

    assert unsafe_delimited(left) == unsafe_delimited(right)
    assert left.canonical_json != right.canonical_json
    assert left.binding_hash != right.binding_hash


@pytest.mark.parametrize(
    "override",
    [
        {"approval_fingerprint": "b" * 64},
        {"provider_id": "another_provider"},
        {"entity_type": EntityType.AUTHOR},
        {"source_id": "43"},
        {"exact_url": "https://other.pixiv.test/works/42"},
        {"exact_url": "https://metadata.pixiv.test/works/43"},
    ],
)
def test_every_bound_component_changes_the_hash(override: dict[str, object]) -> None:
    defaults: dict[str, object] = {
        "approval_fingerprint": APPROVAL_FINGERPRINT,
        "provider_id": "pinned_metadata",
        "entity_type": EntityType.WORK,
        "source_id": "42",
        "exact_url": "https://metadata.pixiv.test/works/42",
    }
    defaults.update(override)

    assert _binding(**defaults).binding_hash != _binding().binding_hash  # type: ignore[arg-type]


def test_source_id_is_nfc_normalized_before_hashing() -> None:
    decomposed = _binding(source_id="Cafe\u0301")
    composed = _binding(source_id="Caf\u00e9")

    assert decomposed.source_id == composed.source_id
    assert decomposed.binding_hash == composed.binding_hash


@pytest.mark.parametrize(
    "url",
    [
        "http://metadata.pixiv.test/works/42",
        "https://metadata.pixiv.test:444/works/42",
        "https://user:secret@metadata.pixiv.test/works/42",
        "https://metadata.pixiv.test/works/42?cursor=1",
        "https://metadata.pixiv.test/works/42#payload",
        "https://127.0.0.1/works/42",
        "https://*.pixiv.test/works/42",
        "https://metadata.pixiv.test./works/42",
        "https://metadata.pixiv.test/works/../42",
        "https://metadata.pixiv.test/works/%2e%2e/42",
        "https://metadata.pixiv.test\\works\\42",
        "https://metadata.pixiv.test/works/%zz",
        "https://metadata.pixiv.test/works/\u00e9",
    ],
)
def test_url_rejects_non_exact_or_ambiguous_forms(url: str) -> None:
    with pytest.raises(ValueError):
        normalize_exact_https_url(url)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("approval_fingerprint", "A" * 64),
        ("approval_fingerprint", "g" * 64),
        ("provider_id", "PinnedMetadata"),
        ("provider_id", "pinned:metadata"),
        ("source_id", "42\n43"),
    ],
)
def test_identity_fields_fail_closed(field: str, value: str) -> None:
    arguments = {
        "approval_fingerprint": APPROVAL_FINGERPRINT,
        "provider_id": "pinned_metadata",
        "entity_type": EntityType.WORK,
        "source_id": "42",
        "canonical_url": "https://metadata.pixiv.test/works/42",
    }
    arguments[field] = value

    with pytest.raises(ValidationError):
        CanonicalLiveRequestBinding.model_validate(arguments)
