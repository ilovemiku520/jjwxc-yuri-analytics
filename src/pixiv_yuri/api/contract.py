"""Deterministic export and validation for the versioned read-only OpenAPI contract."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pixiv_yuri.api.app import create_app

CONTRACT_VERSION = "v1"
EXPECTED_API_PATH_COUNT = 33
PROHIBITED_SCHEMA_FIELDS = (
    "authorization",
    "cookie",
    "observation_metadata",
    "password",
    "payload_object_key",
    "source_observation_id",
    "source_url",
)


@dataclass(frozen=True, slots=True)
class OpenApiContractReport:
    """Payload-free evidence for one deterministic contract export."""

    generated_at: str
    status: str
    contract_version: str
    api_version: str
    sha256: str
    api_path_count: int
    operation_count: int
    mutation_routes_exposed: bool
    prohibited_fields_exposed: bool


def build_openapi_contract() -> dict[str, Any]:
    """Build the database-independent application contract."""
    return create_app(lambda: None).openapi()


def validate_openapi_contract(schema: dict[str, Any]) -> tuple[int, int]:
    """Reject drift from the reviewed v1 read-only and minimized surface."""
    paths = schema.get("paths")
    if not isinstance(paths, dict):
        raise ValueError("OpenAPI paths are missing")
    api_paths = {
        path: operations for path, operations in paths.items() if path.startswith("/api/v1")
    }
    if len(api_paths) != EXPECTED_API_PATH_COUNT:
        raise ValueError("OpenAPI v1 path count changed without contract review")
    operation_count = 0
    for operations in api_paths.values():
        if not isinstance(operations, dict):
            raise ValueError("OpenAPI path operations are invalid")
        methods = {key.lower() for key in operations if key.lower() != "parameters"}
        if methods != {"get"}:
            raise ValueError("OpenAPI v1 must expose exactly one GET operation per path")
        operation_count += 1
    components = schema.get("components", {}).get("schemas", {})
    rendered = json.dumps(components, ensure_ascii=False, sort_keys=True).lower()
    if any(field in rendered for field in PROHIBITED_SCHEMA_FIELDS):
        raise ValueError("OpenAPI v1 exposes a prohibited field")
    return len(api_paths), operation_count


def export_openapi_contract(
    output_path: Path,
    report_path: Path,
    *,
    generated_at: datetime | None = None,
) -> OpenApiContractReport:
    """Write canonical OpenAPI JSON and its checksum evidence."""
    schema = build_openapi_contract()
    api_path_count, operation_count = validate_openapi_contract(schema)
    canonical = json.dumps(schema, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    report = OpenApiContractReport(
        generated_at=(generated_at or datetime.now(UTC)).isoformat(),
        status="passed",
        contract_version=CONTRACT_VERSION,
        api_version=str(schema["info"]["version"]),
        sha256=digest,
        api_path_count=api_path_count,
        operation_count=operation_count,
        mutation_routes_exposed=False,
        prohibited_fields_exposed=False,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(f"{canonical}\n", encoding="utf-8")
    report_path.write_text(
        f"{json.dumps(asdict(report), ensure_ascii=False, indent=2, sort_keys=True)}\n",
        encoding="utf-8",
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("contracts/openapi-v1.json"))
    parser.add_argument("--report", type=Path, default=Path("var/reports/openapi_contract.json"))
    args = parser.parse_args()
    report = export_openapi_contract(args.output, args.report)
    print(json.dumps(asdict(report), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
