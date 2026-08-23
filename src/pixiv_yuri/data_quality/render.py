"""Human-readable rendering for offline schema validation."""

from __future__ import annotations

from pixiv_yuri.data_quality.models import ValidationReport


def render_validation_markdown(report: ValidationReport) -> str:
    """Render outcomes without including raw fixture fields or values."""
    lines = [
        "# Offline Schema Validation",
        "",
        f"- Provider: `{report.provider}`",
        f"- Policy: `{report.policy_scope}` version `{report.policy_version}`",
        f"- Generated at: `{report.generated_at.isoformat()}`",
        f"- Valid: **{report.valid_count}**",
        f"- Quarantined: **{report.quarantined_count}**",
        "",
        "|Entity|Source ID|State|Code|Schema|Parser|",
        "|-|-|-|-|-|-|",
    ]
    for item in report.items:
        fingerprint = item.schema_fingerprint[:12] if item.schema_fingerprint else "—"
        parser = (
            f"{item.parser_id}@{item.parser_version}"
            if item.parser_id and item.parser_version
            else "—"
        )
        lines.append(
            f"|{item.entity_type.value}|`{item.source_id}`|{item.state.value}|"
            f"`{item.code}`|`{fingerprint}`|`{parser}`|"
        )
    lines.append("")
    return "\n".join(lines)
