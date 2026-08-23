"""Compare two aggregate schema reports without inspecting raw payloads."""

from __future__ import annotations

from pixiv_yuri.acquisition.models import EntityType
from pixiv_yuri.schema_probe.models import FieldChange, FieldProfile, SchemaDiff, SchemaReport


def compare_reports(
    baseline: SchemaReport,
    candidate: SchemaReport,
    *,
    availability_threshold: float = 0.2,
) -> SchemaDiff:
    """Return deterministic added, removed, type and availability changes."""
    if not 0 <= availability_threshold <= 1:
        raise ValueError("availability_threshold must be between 0 and 1")

    before = _field_index(baseline)
    after = _field_index(candidate)
    changes: list[FieldChange] = []

    for key in sorted(before.keys() | after.keys(), key=lambda item: (item[0].value, item[1])):
        entity_type, path = key
        before_field = before.get(key)
        after_field = after.get(key)
        if before_field is None and after_field is not None:
            changes.append(
                FieldChange(
                    entity_type=entity_type,
                    path=path,
                    change="field_added",
                    after=_types_label(after_field),
                    severity="low",
                )
            )
            continue
        if before_field is not None and after_field is None:
            changes.append(
                FieldChange(
                    entity_type=entity_type,
                    path=path,
                    change="field_removed",
                    before=_types_label(before_field),
                    severity="high" if before_field.required else "medium",
                )
            )
            continue
        if before_field is None or after_field is None:
            continue

        before_types = _types_label(before_field)
        after_types = _types_label(after_field)
        if before_types != after_types:
            changes.append(
                FieldChange(
                    entity_type=entity_type,
                    path=path,
                    change="types_changed",
                    before=before_types,
                    after=after_types,
                    severity="high",
                )
            )

        availability_delta = after_field.availability - before_field.availability
        if abs(availability_delta) >= availability_threshold:
            changes.append(
                FieldChange(
                    entity_type=entity_type,
                    path=path,
                    change="availability_changed",
                    before=before_field.availability,
                    after=after_field.availability,
                    severity="medium" if availability_delta < 0 else "low",
                )
            )

        if before_field.required != after_field.required:
            changes.append(
                FieldChange(
                    entity_type=entity_type,
                    path=path,
                    change="required_changed",
                    before=str(before_field.required).lower(),
                    after=str(after_field.required).lower(),
                    severity="high" if before_field.required else "medium",
                )
            )

    return SchemaDiff(
        baseline_generated_at=baseline.generated_at,
        candidate_generated_at=candidate.generated_at,
        changes=tuple(changes),
        breaking_change_count=sum(change.severity == "high" for change in changes),
    )


def _field_index(report: SchemaReport) -> dict[tuple[EntityType, str], FieldProfile]:
    return {
        (entity_report.entity_type, field.path): field
        for entity_report in report.entity_reports
        for field in entity_report.fields
    }


def _types_label(field: FieldProfile) -> str:
    return "|".join(value.value for value in field.types)

