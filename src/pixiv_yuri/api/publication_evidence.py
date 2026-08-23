"""Generate non-secret external-publication evidence artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pixiv_yuri.api.publication_review import PublicationDeploymentManifest

_SCHEMA_ID = "urn:pixiv-yuri-analytics:publication-deployment-manifest:v1"


def publication_manifest_schema() -> dict[str, Any]:
    """Return the versioned JSON Schema without adding secret-bearing fields."""
    schema = PublicationDeploymentManifest.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = _SCHEMA_ID
    schema["x-authoritative-review"] = "pyuri-publication-review"
    schema["x-secret-values-forbidden"] = [
        "account_password",
        "browser_cookie",
        "hmac_secret",
        "private_key",
        "session_token",
    ]
    return schema


def draft_publication_manifest(*, now: datetime | None = None) -> dict[str, Any]:
    """Build a deliberately non-authorizing manifest containing no credentials."""
    checked_at = (now or datetime.now(UTC)).astimezone(UTC)
    expires_at = checked_at + timedelta(days=30)
    return {
        "version": 1,
        "status": "draft",
        "deployment_id": "publication-draft",
        "accountable_owner": "change-me",
        "approver": "change-me",
        "reviewed_at": checked_at.isoformat(),
        "expires_at": expires_at.isoformat(),
        "identity_proxy": {
            "adapter": "trusted_hmac_proxy",
            "product": "unconfigured",
            "deployment_reference": "draft",
            "proxy_id": "private-edge",
            "direct_api_access_blocked": False,
            "secret_delivery": "unconfigured",
            "secret_rotation_days": 365,
            "assertion_max_age_seconds": 300,
            "health_monitoring_enabled": False,
        },
        "tls": {
            "hostname": "api.example.invalid",
            "certificate_authority": "unconfigured",
            "certificate_not_after": expires_at.isoformat(),
            "minimum_tls_version": "TLSv1.2",
            "private_key_storage": "unconfigured",
            "automated_renewal": False,
            "renewal_monitoring_enabled": False,
            "hsts_enabled": False,
        },
    }


def write_json_artifact(*, output: Path, payload: dict[str, Any], force: bool = False) -> None:
    """Write one artifact, refusing to overwrite by default."""
    if output.exists() and not force:
        raise FileExistsError("output already exists; pass --force to replace it")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("schema", "init"):
        command = subparsers.add_parser(name)
        command.add_argument("--output", type=Path, required=True)
        command.add_argument("--force", action="store_true")
    args = parser.parse_args()
    payload = (
        publication_manifest_schema()
        if args.command == "schema"
        else draft_publication_manifest()
    )
    try:
        write_json_artifact(output=args.output, payload=payload, force=args.force)
    except OSError as exc:
        print(f"Publication evidence artifact was not written: {exc}", file=sys.stderr)
        return 2
    print(f"Wrote non-secret publication {args.command} artifact: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
