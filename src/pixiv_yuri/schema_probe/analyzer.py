"""Deterministic JSON structure analysis over raw provider responses."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from pixiv_yuri.acquisition.base import AcquisitionProvider
from pixiv_yuri.acquisition.models import EntityType, RawResponse
from pixiv_yuri.schema_probe.models import (
    EntitySchemaReport,
    FieldProfile,
    JsonType,
    ProbeError,
    SampleProfile,
    SchemaReport,
    Stability,
)

_TYPE_ORDER = {value: index for index, value in enumerate(JsonType)}
_SENSITIVE_PATH_PARTS = ("authorization", "cookie", "password", "secret", "token")


def fingerprint_payload(payload: Any) -> str:
    """Hash JSON structure and value types, independent of key and array order."""
    descriptor = describe_payload(payload)
    canonical = json.dumps(descriptor, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def describe_payload(payload: Any) -> dict[str, Any]:
    """Return the canonical, value-free structure stored with a schema fingerprint."""
    descriptor = _structure_descriptor(payload)
    if not isinstance(descriptor, dict):
        raise TypeError("A schema descriptor must be a JSON object.")
    return descriptor


def analyze_provider(
    provider: AcquisitionProvider,
    *,
    include_examples: bool = False,
    generated_at: datetime | None = None,
) -> SchemaReport:
    """Analyze all provider fixtures and group evidence by entity type."""
    grouped: dict[EntityType, list[tuple[RawResponse, Any]]] = defaultdict(list)
    errors: list[ProbeError] = []

    for request in provider.list_requests():
        try:
            response = provider.fetch(request)
            if not 200 <= response.status_code < 300:
                errors.append(
                    ProbeError(
                        entity_type=request.entity_type,
                        source_id=request.source_id,
                        code="non_success_status",
                        detail=f"HTTP-like status {response.status_code}",
                    )
                )
                continue
            grouped[response.entity_type].append((response, response.json_value()))
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
            errors.append(
                ProbeError(
                    entity_type=request.entity_type,
                    source_id=request.source_id,
                    code="invalid_fixture",
                    detail=str(exc),
                )
            )

    entity_reports = tuple(
        _analyze_entity(entity_type, samples, include_examples=include_examples)
        for entity_type, samples in sorted(grouped.items(), key=lambda item: item[0].value)
    )
    return SchemaReport(
        generated_at=generated_at or datetime.now(UTC),
        provider=provider.name,
        entity_reports=entity_reports,
        errors=tuple(errors),
    )


def _analyze_entity(
    entity_type: EntityType,
    samples: list[tuple[RawResponse, Any]],
    *,
    include_examples: bool,
) -> EntitySchemaReport:
    sample_count = len(samples)
    present_counts: dict[str, int] = defaultdict(int)
    observed_types: dict[str, set[JsonType]] = defaultdict(set)
    examples: dict[str, list[str]] = defaultdict(list)
    sample_profiles: list[SampleProfile] = []

    for response, payload in samples:
        flattened = _flatten(payload, include_examples=include_examples)
        for path, (field_types, field_examples) in flattened.items():
            present_counts[path] += 1
            observed_types[path].update(field_types)
            for example in field_examples:
                if example not in examples[path] and len(examples[path]) < 3:
                    examples[path].append(example)
        sample_profiles.append(
            SampleProfile(
                source_id=response.source_id,
                payload_sha256=response.payload_sha256,
                schema_fingerprint=fingerprint_payload(payload),
            )
        )

    fields: list[FieldProfile] = []
    for path in sorted(present_counts):
        profile_types = tuple(sorted(observed_types[path], key=_TYPE_ORDER.__getitem__))
        present_count = present_counts[path]
        availability = present_count / sample_count
        nullable = JsonType.NULL in profile_types
        non_null_types = tuple(value for value in profile_types if value != JsonType.NULL)
        required = present_count == sample_count and not nullable
        if required and len(non_null_types) <= 1:
            stability = Stability.HIGH
        elif availability >= 0.8 and len(non_null_types) <= 1:
            stability = Stability.MEDIUM
        else:
            stability = Stability.LOW

        fields.append(
            FieldProfile(
                path=path,
                availability=round(availability, 6),
                present_count=present_count,
                sample_count=sample_count,
                types=profile_types,
                required=required,
                nullable=nullable,
                stability=stability,
                examples=tuple(examples[path]) if include_examples else (),
            )
        )

    return EntitySchemaReport(
        entity_type=entity_type,
        sample_count=sample_count,
        samples=tuple(sample_profiles),
        fields=tuple(fields),
    )


def _flatten(
    payload: Any, *, include_examples: bool
) -> dict[str, tuple[set[JsonType], list[str]]]:
    fields: dict[str, tuple[set[JsonType], list[str]]] = {}

    def visit(value: Any, path: str) -> None:
        value_type = _json_type(value)
        types, path_examples = fields.setdefault(path, (set(), []))
        types.add(value_type)
        if include_examples and len(path_examples) < 1:
            path_examples.append(_safe_example(path, value))

        if isinstance(value, Mapping):
            for key in sorted(value):
                visit(value[key], f"{path}.{key}")
        elif isinstance(value, list):
            for item in value:
                visit(item, f"{path}[]")

    visit(payload, "$")
    return fields


def _json_type(value: Any) -> JsonType:
    if value is None:
        return JsonType.NULL
    if isinstance(value, bool):
        return JsonType.BOOLEAN
    if isinstance(value, int):
        return JsonType.INTEGER
    if isinstance(value, float):
        return JsonType.NUMBER
    if isinstance(value, str):
        return JsonType.STRING
    if isinstance(value, Mapping):
        return JsonType.OBJECT
    if isinstance(value, list):
        return JsonType.ARRAY
    raise TypeError(f"Unsupported JSON value type: {type(value).__name__}")


def _structure_descriptor(value: Any) -> Any:
    value_type = _json_type(value)
    if isinstance(value, Mapping):
        return {
            "type": value_type.value,
            "fields": {key: _structure_descriptor(value[key]) for key in sorted(value)},
        }
    if isinstance(value, list):
        items = {
            json.dumps(
                _structure_descriptor(item),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            for item in value
        }
        return {"type": value_type.value, "items": sorted(items)}
    return {"type": value_type.value}


def _safe_example(path: str, value: Any) -> str:
    if any(fragment in path.lower() for fragment in _SENSITIVE_PATH_PARTS):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return "{...}"
    if isinstance(value, list):
        return "[...]"
    rendered = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return rendered if len(rendered) <= 80 else f"{rendered[:77]}..."
