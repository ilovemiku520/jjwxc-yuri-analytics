"""Command-line entry point for the network-free schema probe."""

from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence
from pathlib import Path

from pixiv_yuri.acquisition.parsers.registry import build_offline_fixture_registry
from pixiv_yuri.acquisition.providers.fixture import FixtureProvider
from pixiv_yuri.data_quality.render import render_validation_markdown
from pixiv_yuri.data_quality.validation import load_schema_policy, validate_provider
from pixiv_yuri.schema_probe.analyzer import analyze_provider
from pixiv_yuri.schema_probe.diff import compare_reports
from pixiv_yuri.schema_probe.render import (
    load_report,
    render_diff_markdown,
    render_report_markdown,
    write_model_json,
)
from pixiv_yuri.shared.config import Settings
from pixiv_yuri.shared.logging import configure_logging

LOGGER = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    """Build the strict Phase 0 CLI."""
    parser = argparse.ArgumentParser(
        prog="pyuri-schema-probe",
        description="Analyze approved local JSON fixtures without network access.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    analyze = subparsers.add_parser("analyze", help="Analyze a fixture manifest.")
    analyze.add_argument("--manifest", type=Path, help="Fixture manifest JSON path.")
    analyze.add_argument("--output", type=Path, help="Report output directory.")
    analyze.add_argument(
        "--include-examples",
        action="store_true",
        help="Include short redacted field examples; disabled by default.",
    )

    diff = subparsers.add_parser("diff", help="Compare two generated reports.")
    diff.add_argument("--baseline", type=Path, required=True)
    diff.add_argument("--candidate", type=Path, required=True)
    diff.add_argument("--output", type=Path, required=True, help="Diff JSON output path.")
    diff.add_argument("--availability-threshold", type=float, default=0.2)

    validate = subparsers.add_parser(
        "validate", help="Apply an exact fixture schema policy and parser route."
    )
    validate.add_argument("--manifest", type=Path, help="Fixture manifest JSON path.")
    validate.add_argument("--policy", type=Path, required=True, help="Schema policy JSON path.")
    validate.add_argument("--output", type=Path, help="Validation report directory.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run one offline probe command and return a process status."""
    args = build_parser().parse_args(argv)
    settings = Settings.from_env()
    configure_logging(settings.log_level)

    if args.command == "analyze":
        manifest = (args.manifest or settings.fixture_manifest).resolve()
        output_dir = (args.output or settings.report_dir).resolve()
        provider = FixtureProvider(manifest)
        schema_report = analyze_provider(provider, include_examples=args.include_examples)
        if not schema_report.entity_reports:
            LOGGER.error("Schema probe produced no valid entity reports.")
            return 2
        write_model_json(output_dir / "schema_report.json", schema_report)
        markdown = render_report_markdown(schema_report)
        (output_dir / "schema_report.md").write_text(markdown, encoding="utf-8", newline="\n")
        LOGGER.info(
            "Offline schema probe completed.",
            extra={
                "context": {
                    "manifest": str(manifest),
                    "output_dir": str(output_dir),
                    "entities": len(schema_report.entity_reports),
                    "errors": len(schema_report.errors),
                }
            },
        )
        return 0 if not schema_report.errors else 1

    if args.command == "validate":
        manifest = (args.manifest or settings.fixture_manifest).resolve()
        output_dir = (args.output or settings.report_dir).resolve()
        validation_report = validate_provider(
            FixtureProvider(manifest),
            load_schema_policy(args.policy.resolve()),
            build_offline_fixture_registry(),
        )
        write_model_json(output_dir / "schema_validation.json", validation_report)
        (output_dir / "schema_validation.md").write_text(
            render_validation_markdown(validation_report), encoding="utf-8", newline="\n"
        )
        LOGGER.info(
            "Offline schema validation completed.",
            extra={
                "context": {
                    "manifest": str(manifest),
                    "policy": str(args.policy.resolve()),
                    "valid": validation_report.valid_count,
                    "quarantined": validation_report.quarantined_count,
                }
            },
        )
        return 4 if validation_report.quarantined_count else 0

    baseline = load_report(args.baseline.resolve())
    candidate = load_report(args.candidate.resolve())
    diff = compare_reports(
        baseline,
        candidate,
        availability_threshold=args.availability_threshold,
    )
    output_path = args.output.resolve()
    write_model_json(output_path, diff)
    output_path.with_suffix(".md").write_text(
        render_diff_markdown(diff), encoding="utf-8", newline="\n"
    )
    LOGGER.info(
        "Schema diff completed.",
        extra={
            "context": {
                "changes": len(diff.changes),
                "high_severity": diff.breaking_change_count,
                "output": str(output_path),
            }
        },
    )
    return 3 if diff.breaking_change_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
