from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from pixiv_yuri.api.publication_evidence import (
    draft_publication_manifest,
    publication_manifest_schema,
    write_json_artifact,
)
from pixiv_yuri.api.publication_review import PublicationDeploymentManifest, review_publication

NOW = datetime(2026, 8, 23, tzinfo=UTC)


def _phase2() -> dict[str, object]:
    return {
        "status": "passed_private_only",
        "private_read_api_ready": True,
        "trusted_proxy_adapter_verified": True,
        "loopback_tls_verified": True,
        "shared_consumer_controls_verified": True,
        "real_source_collection_count": 0,
    }


def test_manifest_schema_is_versioned_and_forbids_unknown_fields() -> None:
    schema = publication_manifest_schema()

    assert schema["$id"].endswith(":v1")
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["additionalProperties"] is False
    assert schema["$defs"]["IdentityProxyDeployment"]["additionalProperties"] is False
    assert schema["$defs"]["TlsDeployment"]["additionalProperties"] is False
    assert "hmac_secret" in schema["x-secret-values-forbidden"]


def test_generated_draft_is_valid_but_remains_fail_closed() -> None:
    payload = draft_publication_manifest(now=NOW)
    PublicationDeploymentManifest.model_validate(payload)

    report = review_publication(phase2_report=_phase2(), manifest_payload=payload, now=NOW)

    assert report.status == "blocked"
    assert not report.external_publication_approved
    assert not report.real_source_collection_authorized
    assert "deployment_manifest_not_approved" in report.violations


def test_writer_refuses_overwrite_by_default(tmp_path: Path) -> None:
    output = tmp_path / "manifest.json"
    write_json_artifact(output=output, payload={"version": 1})

    with pytest.raises(FileExistsError, match="already exists"):
        write_json_artifact(output=output, payload={"version": 2})

    assert json.loads(output.read_text(encoding="utf-8")) == {"version": 1}


def test_writer_can_explicitly_replace_generated_artifact(tmp_path: Path) -> None:
    output = tmp_path / "schema.json"
    write_json_artifact(output=output, payload={"version": 1})
    write_json_artifact(output=output, payload={"version": 2}, force=True)

    assert json.loads(output.read_text(encoding="utf-8")) == {"version": 2}
