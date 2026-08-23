"""Human and machine-readable report rendering."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from pixiv_yuri.schema_probe.models import SchemaDiff, SchemaReport


def render_report_markdown(report: SchemaReport) -> str:
    """Render a concise review document without exposing raw payloads."""
    lines = [
        "# Offline Schema Probe Report",
        "",
        f"- Provider: `{report.provider}`",
        f"- Generated at: `{report.generated_at.isoformat()}`",
        f"- Report version: `{report.report_version}`",
        f"- Errors: `{len(report.errors)}`",
        "",
    ]
    for entity in report.entity_reports:
        lines.extend(
            [
                f"## {entity.entity_type.value}",
                "",
                f"Samples: **{entity.sample_count}**",
                "",
                "|Path|Types|Availability|Required|Nullable|Stability|Examples|",
                "|-|-|-:|-|-|-|-|",
            ]
        )
        for field in entity.fields:
            examples = ", ".join(field.examples).replace("|", "\\|") or "—"
            types = ", ".join(value.value for value in field.types)
            lines.append(
                "|"
                f"`{field.path}`|{types}|{field.availability:.1%}|"
                f"{_yes_no(field.required)}|{_yes_no(field.nullable)}|"
                f"{field.stability.value}|{examples}|"
            )
        lines.extend(["", "### Samples", ""])
        for sample in entity.samples:
            lines.append(
                f"- `{sample.source_id}` — payload `{sample.payload_sha256[:12]}`; "
                f"schema `{sample.schema_fingerprint[:12]}`"
            )
        lines.append("")

    if report.errors:
        lines.extend(["## Errors", ""])
        for error in report.errors:
            lines.append(
                f"- `{error.entity_type.value}/{error.source_id}`: "
                f"`{error.code}` — {error.detail}"
            )
        lines.append("")
    return "\n".join(lines)


def render_diff_markdown(diff: SchemaDiff) -> str:
    """Render a reviewable schema diff."""
    lines = [
        "# Schema Diff",
        "",
        f"- Baseline: `{diff.baseline_generated_at.isoformat()}`",
        f"- Candidate: `{diff.candidate_generated_at.isoformat()}`",
        f"- High-severity changes: **{diff.breaking_change_count}**",
        "",
        "|Entity|Path|Change|Before|After|Severity|",
        "|-|-|-|-|-|-|",
    ]
    for change in diff.changes:
        lines.append(
            f"|{change.entity_type.value}|`{change.path}`|{change.change}|"
            f"{change.before if change.before is not None else '—'}|"
            f"{change.after if change.after is not None else '—'}|{change.severity}|"
        )
    if not diff.changes:
        lines.extend(["", "No schema changes detected."])
    lines.append("")
    return "\n".join(lines)


def write_model_json(path: Path, model: BaseModel) -> None:
    """Atomically write one Pydantic model as stable, UTF-8 JSON."""
    payload = json.dumps(
        model.model_dump(mode="json"),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    _atomic_write(path, f"{payload}\n")


def load_report(path: Path) -> SchemaReport:
    """Load and validate a JSON schema report."""
    raw: Any = json.loads(path.read_text(encoding="utf-8"))
    return SchemaReport.model_validate(raw)


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        temporary.write_text(content, encoding="utf-8", newline="\n")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"

