"""Fail-closed offline schema validation and exact parser selection."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from pixiv_yuri.acquisition.base import AcquisitionProvider
from pixiv_yuri.acquisition.models import EntityType, RawResponse
from pixiv_yuri.acquisition.parsers.base import ParserError
from pixiv_yuri.acquisition.parsers.registry import ParserRegistry, ParserRegistryError
from pixiv_yuri.data_quality.models import (
    SchemaDecision,
    SchemaPolicy,
    ValidationItem,
    ValidationReport,
    ValidationState,
)
from pixiv_yuri.schema_probe.analyzer import fingerprint_payload


class SchemaPolicyError(ValueError):
    """Raised when a policy file or provider binding is invalid."""


def load_schema_policy(path: Path) -> SchemaPolicy:
    """Read and strictly validate one UTF-8 JSON policy."""
    try:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
        return SchemaPolicy.model_validate(raw)
    except (OSError, UnicodeError, json.JSONDecodeError, ValidationError) as exc:
        raise SchemaPolicyError(f"Cannot load schema policy {path}: {exc}") from exc


def validate_provider(
    provider: AcquisitionProvider,
    policy: SchemaPolicy,
    parser_registry: ParserRegistry,
    *,
    generated_at: datetime | None = None,
) -> ValidationReport:
    """Apply an exact policy and parse only approved fixture structures."""
    ensure_policy_provider(policy, provider.name)

    items: list[ValidationItem] = []
    for request in provider.list_requests():
        try:
            response = provider.fetch(request)
            items.append(validate_response(response, policy, parser_registry))
        except (OSError, UnicodeError, ValueError, ParserRegistryError) as exc:
            items.append(
                ValidationItem(
                    entity_type=request.entity_type,
                    source_id=request.source_id,
                    state=ValidationState.QUARANTINED,
                    code="validation_error",
                    detail=str(exc)[:2000],
                )
            )

    valid_count = sum(item.state == ValidationState.VALID for item in items)
    return ValidationReport(
        generated_at=generated_at or datetime.now(UTC),
        provider=provider.name,
        policy_version=policy.policy_version,
        valid_count=valid_count,
        quarantined_count=len(items) - valid_count,
        items=tuple(items),
    )


def ensure_policy_provider(policy: SchemaPolicy, provider_name: str) -> None:
    """Reject accidental reuse of a policy across provider contracts."""
    if provider_name != policy.provider:
        raise SchemaPolicyError(
            f"Policy provider {policy.provider!r} does not match {provider_name!r}."
        )


def validate_response(
    response: RawResponse,
    policy: SchemaPolicy,
    parser_registry: ParserRegistry,
) -> ValidationItem:
    """Validate and transiently parse one response without exposing its body."""
    ensure_policy_provider(policy, response.provider)
    if not 200 <= response.status_code < 300:
        return ValidationItem(
            entity_type=response.entity_type,
            source_id=response.source_id,
            state=ValidationState.QUARANTINED,
            code="non_success_status",
            detail=f"HTTP-like status {response.status_code}",
            payload_sha256=response.payload_sha256,
        )

    try:
        payload = response.json_value()
        fingerprint = fingerprint_payload(payload)
        entry = policy.find(response.entity_type, fingerprint)
        if entry is None:
            return _quarantined_item(
                response.entity_type,
                response.source_id,
                response.payload_sha256,
                fingerprint,
                "unknown_schema",
                "No exact offline policy entry exists for this fingerprint.",
            )
        if entry.decision == SchemaDecision.REJECTED:
            return _quarantined_item(
                response.entity_type,
                response.source_id,
                response.payload_sha256,
                fingerprint,
                "schema_rejected",
                entry.note,
            )

        assert entry.parser_id is not None and entry.parser_version is not None
        parser = parser_registry.resolve(
            entry.parser_id,
            entry.parser_version,
            response.entity_type,
        )
        parsed = parser.parse(response)
        if parsed.schema_fingerprint != fingerprint:
            raise ParserError("Parser output fingerprint does not match the policy gate.")
        return ValidationItem(
            entity_type=response.entity_type,
            source_id=response.source_id,
            state=ValidationState.VALID,
            code="schema_approved",
            detail="Exact fixture schema and parser route approved.",
            payload_sha256=response.payload_sha256,
            schema_fingerprint=fingerprint,
            parser_id=parser.parser_id,
            parser_version=parser.version,
        )
    except (OSError, UnicodeError, ValueError, ParserRegistryError) as exc:
        return ValidationItem(
            entity_type=response.entity_type,
            source_id=response.source_id,
            state=ValidationState.QUARANTINED,
            code="validation_error",
            detail=str(exc)[:2000],
            payload_sha256=response.payload_sha256,
        )


def _quarantined_item(
    entity_type: EntityType,
    source_id: str,
    payload_sha256: str,
    fingerprint: str,
    code: str,
    detail: str,
) -> ValidationItem:
    return ValidationItem(
        entity_type=entity_type,
        source_id=source_id,
        state=ValidationState.QUARANTINED,
        code=code,
        detail=detail,
        payload_sha256=payload_sha256,
        schema_fingerprint=fingerprint,
    )
