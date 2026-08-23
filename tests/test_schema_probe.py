from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from pixiv_yuri.acquisition.models import EntityType
from pixiv_yuri.acquisition.providers.fixture import FixtureProvider
from pixiv_yuri.schema_probe.analyzer import analyze_provider, fingerprint_payload
from pixiv_yuri.schema_probe.cli import main
from pixiv_yuri.schema_probe.diff import compare_reports

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = PROJECT_ROOT / "fixtures" / "manifest.json"
GENERATED_AT = datetime(2026, 8, 22, tzinfo=UTC)


class FingerprintTests(unittest.TestCase):
    def test_fingerprint_ignores_object_and_array_order(self) -> None:
        first = {"id": 1, "tags": [{"name": "a"}, {"name": "b"}]}
        second = {"tags": [{"name": "z"}, {"name": "y"}], "id": 999}
        self.assertEqual(fingerprint_payload(first), fingerprint_payload(second))

    def test_fingerprint_changes_when_type_changes(self) -> None:
        self.assertNotEqual(fingerprint_payload({"id": 1}), fingerprint_payload({"id": "1"}))


class AnalyzerTests(unittest.TestCase):
    def test_aggregate_report_tracks_availability_and_nullability(self) -> None:
        report = analyze_provider(FixtureProvider(MANIFEST), generated_at=GENERATED_AT)
        by_entity = {entity.entity_type: entity for entity in report.entity_reports}
        self.assertEqual(by_entity[EntityType.WORK].sample_count, 2)
        fields = {field.path: field for field in by_entity[EntityType.WORK].fields}
        self.assertEqual(fields["$.description"].availability, 0.5)
        self.assertFalse(fields["$.description"].required)
        self.assertEqual(fields["$.metrics.comments"].availability, 0.5)
        self.assertTrue(fields["$.tags[].translated_name"].nullable)
        self.assertEqual(fields["$.id"].examples, ())

    def test_examples_are_opt_in(self) -> None:
        report = analyze_provider(
            FixtureProvider(MANIFEST), include_examples=True, generated_at=GENERATED_AT
        )
        work = next(
            entity for entity in report.entity_reports if entity.entity_type == EntityType.WORK
        )
        fields = {field.path: field for field in work.fields}
        self.assertTrue(fields["$.id"].examples)

    def test_diff_marks_required_field_removal_as_high(self) -> None:
        baseline = analyze_provider(FixtureProvider(MANIFEST), generated_at=GENERATED_AT)
        work = next(
            entity for entity in baseline.entity_reports if entity.entity_type == EntityType.WORK
        )
        modified_work = work.model_copy(
            update={"fields": tuple(field for field in work.fields if field.path != "$.id")}
        )
        candidate = baseline.model_copy(
            update={
                "generated_at": GENERATED_AT + timedelta(days=1),
                "entity_reports": tuple(
                    modified_work if entity.entity_type == EntityType.WORK else entity
                    for entity in baseline.entity_reports
                ),
            }
        )
        diff = compare_reports(baseline, candidate)
        change = next(change for change in diff.changes if change.path == "$.id")
        self.assertEqual(change.change, "field_removed")
        self.assertEqual(change.severity, "high")
        self.assertEqual(diff.breaking_change_count, 1)

    def test_cli_writes_json_and_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict("os.environ", {"PYURI_ENABLE_NETWORK": "false"}):
                result = main(
                    [
                        "analyze",
                        "--manifest",
                        str(MANIFEST),
                        "--output",
                        directory,
                    ]
                )
            self.assertEqual(result, 0)
            self.assertTrue((Path(directory) / "schema_report.json").is_file())
            self.assertTrue((Path(directory) / "schema_report.md").is_file())

    def test_cli_diffs_two_reports(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            directory_path = Path(directory)
            with patch.dict("os.environ", {"PYURI_ENABLE_NETWORK": "false"}):
                analyze_result = main(
                    [
                        "analyze",
                        "--manifest",
                        str(MANIFEST),
                        "--output",
                        directory,
                    ]
                )
                report_path = directory_path / "schema_report.json"
                diff_result = main(
                    [
                        "diff",
                        "--baseline",
                        str(report_path),
                        "--candidate",
                        str(report_path),
                        "--output",
                        str(directory_path / "schema_diff.json"),
                    ]
                )
            self.assertEqual(analyze_result, 0)
            self.assertEqual(diff_result, 0)
            self.assertTrue((directory_path / "schema_diff.json").is_file())
            self.assertTrue((directory_path / "schema_diff.md").is_file())



if __name__ == "__main__":
    unittest.main()
