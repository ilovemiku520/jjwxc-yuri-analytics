from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from pixiv_yuri.acquisition.models import EntityType, RawResponse
from pixiv_yuri.acquisition.parsers.base import ParserError
from pixiv_yuri.acquisition.parsers.fixture_object import FixtureObjectParser
from pixiv_yuri.acquisition.parsers.registry import (
    ParserRegistry,
    ParserRegistryError,
    build_offline_fixture_registry,
)
from pixiv_yuri.acquisition.providers.fixture import FixtureProvider
from pixiv_yuri.data_quality.models import SchemaPolicy
from pixiv_yuri.data_quality.validation import (
    SchemaPolicyError,
    load_schema_policy,
    validate_provider,
)
from pixiv_yuri.schema_probe.cli import main

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = PROJECT_ROOT / "fixtures" / "manifest.json"
POLICY = PROJECT_ROOT / "fixtures" / "schema_policy.json"
GENERATED_AT = datetime(2026, 8, 22, tzinfo=UTC)


class SchemaPolicyTests(unittest.TestCase):
    def test_approved_fixture_policy_routes_every_sample(self) -> None:
        report = validate_provider(
            FixtureProvider(MANIFEST),
            load_schema_policy(POLICY),
            build_offline_fixture_registry(),
            generated_at=GENERATED_AT,
        )
        self.assertEqual(report.valid_count, 3)
        self.assertEqual(report.quarantined_count, 0)
        self.assertEqual({item.parser_id for item in report.items}, {"fixture_object"})
        self.assertTrue(all(item.payload_sha256 for item in report.items))

    def test_unknown_fingerprints_fail_closed(self) -> None:
        approved = load_schema_policy(POLICY)
        author_only = approved.model_copy(update={"entries": approved.entries[:1]})
        report = validate_provider(
            FixtureProvider(MANIFEST),
            author_only,
            build_offline_fixture_registry(),
            generated_at=GENERATED_AT,
        )
        self.assertEqual(report.valid_count, 1)
        self.assertEqual(report.quarantined_count, 2)
        self.assertEqual(
            [item.code for item in report.items if item.code == "unknown_schema"],
            ["unknown_schema", "unknown_schema"],
        )

    def test_missing_exact_parser_is_quarantined(self) -> None:
        report = validate_provider(
            FixtureProvider(MANIFEST),
            load_schema_policy(POLICY),
            ParserRegistry(),
            generated_at=GENERATED_AT,
        )
        self.assertEqual(report.valid_count, 0)
        self.assertEqual(report.quarantined_count, 3)
        self.assertTrue(all(item.code == "validation_error" for item in report.items))

    def test_explicitly_rejected_schema_never_reaches_parser(self) -> None:
        raw = json.loads(POLICY.read_text(encoding="utf-8"))
        rejected = raw["entries"][0]
        rejected["decision"] = "rejected"
        rejected.pop("parser_id")
        rejected.pop("parser_version")
        policy = SchemaPolicy.model_validate(raw)
        report = validate_provider(
            FixtureProvider(MANIFEST),
            policy,
            build_offline_fixture_registry(),
            generated_at=GENERATED_AT,
        )
        self.assertEqual(report.valid_count, 2)
        self.assertEqual(report.quarantined_count, 1)
        rejected_item = next(item for item in report.items if item.code == "schema_rejected")
        self.assertIsNone(rejected_item.parser_id)

    def test_policy_cannot_bind_to_a_different_provider(self) -> None:
        policy = load_schema_policy(POLICY).model_copy(update={"provider": "another_provider"})
        with self.assertRaises(SchemaPolicyError):
            validate_provider(
                FixtureProvider(MANIFEST),
                policy,
                build_offline_fixture_registry(),
            )

    def test_policy_rejects_duplicate_entries(self) -> None:
        raw = json.loads(POLICY.read_text(encoding="utf-8"))
        raw["entries"].append(raw["entries"][0])
        with self.assertRaises(ValidationError):
            SchemaPolicy.model_validate(raw)

    def test_cli_writes_machine_and_human_validation_reports(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict("os.environ", {"PYURI_ENABLE_NETWORK": "false"}):
                result = main(
                    [
                        "validate",
                        "--manifest",
                        str(MANIFEST),
                        "--policy",
                        str(POLICY),
                        "--output",
                        directory,
                    ]
                )
            output = Path(directory)
            self.assertEqual(result, 0)
            self.assertTrue((output / "schema_validation.json").is_file())
            self.assertTrue((output / "schema_validation.md").is_file())
            report = json.loads((output / "schema_validation.json").read_text(encoding="utf-8"))
            self.assertEqual(report["valid_count"], 3)
            self.assertEqual(report["quarantined_count"], 0)


class ParserContractTests(unittest.TestCase):
    def test_registry_rejects_duplicate_parser_versions(self) -> None:
        with self.assertRaises(ParserRegistryError):
            ParserRegistry((FixtureObjectParser(), FixtureObjectParser()))

    def test_fixture_parser_rejects_non_object_roots(self) -> None:
        response = RawResponse(
            provider="synthetic_fixture",
            entity_type=EntityType.WORK,
            source_id="scalar",
            observed_at=GENERATED_AT,
            status_code=200,
            content_type="application/json",
            body=b"[]",
        )
        with self.assertRaises(ParserError):
            FixtureObjectParser().parse(response)


if __name__ == "__main__":
    unittest.main()
