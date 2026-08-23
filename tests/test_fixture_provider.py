from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from pixiv_yuri.acquisition.models import AcquisitionRequest, EntityType
from pixiv_yuri.acquisition.providers.fixture import FixtureProvider, FixtureProviderError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = PROJECT_ROOT / "fixtures" / "manifest.json"


class FixtureProviderTests(unittest.TestCase):
    def test_lists_and_fetches_manifest_records(self) -> None:
        provider = FixtureProvider(MANIFEST)
        self.assertEqual(provider.name, "synthetic_fixture")
        self.assertEqual(len(provider.list_requests()), 3)
        self.assertEqual(len(provider.list_requests(EntityType.WORK)), 2)

        response = provider.fetch(
            AcquisitionRequest(entity_type=EntityType.WORK, source_id="synthetic-work-1001")
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json_value()["id"], "synthetic-work-1001")
        self.assertEqual(len(response.payload_sha256), 64)
        self.assertTrue(response.metadata["synthetic"])

    def test_unknown_request_is_rejected(self) -> None:
        provider = FixtureProvider(MANIFEST)
        with self.assertRaises(FixtureProviderError):
            provider.fetch(AcquisitionRequest(entity_type=EntityType.WORK, source_id="missing"))

    def test_manifest_rejects_path_traversal(self) -> None:
        manifest = {
            "version": 1,
            "provider": "fixture",
            "records": [
                {
                    "entity_type": "work",
                    "source_id": "one",
                    "observed_at": "2026-08-01T00:00:00Z",
                    "path": "../outside.json",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(FixtureProviderError):
                FixtureProvider(path)

    def test_manifest_rejects_duplicate_logical_keys(self) -> None:
        record = {
            "entity_type": "work",
            "source_id": "one",
            "observed_at": "2026-08-01T00:00:00Z",
            "path": "one.json",
        }
        manifest = {"version": 1, "provider": "fixture", "records": [record, record]}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(FixtureProviderError):
                FixtureProvider(path)


if __name__ == "__main__":
    unittest.main()

