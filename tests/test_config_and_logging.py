from __future__ import annotations

import json
import logging
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from pixiv_yuri.shared.config import Settings, SettingsError
from pixiv_yuri.shared.logging import JsonFormatter, bind_request_id, redact, reset_request_id


class SettingsTests(unittest.TestCase):
    def test_defaults_resolve_from_base_directory(self) -> None:
        base = Path.cwd().resolve()
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings.from_env(base)
        self.assertFalse(settings.enable_network)
        self.assertEqual(settings.fixture_manifest, base / "fixtures" / "manifest.json")
        self.assertEqual(settings.report_dir, base / "var" / "reports")

    def test_network_true_is_rejected(self) -> None:
        with (
            patch.dict(os.environ, {"PYURI_ENABLE_NETWORK": "true"}, clear=True),
            self.assertRaises((SettingsError, ValidationError)),
        ):
            Settings.from_env()

    def test_invalid_log_level_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            Settings(log_level="verbose")


class LoggingTests(unittest.TestCase):
    def test_redact_handles_nested_secret_keys(self) -> None:
        value = {
            "Authorization": "Bearer value",
            "safe": {"api_token": "value", "count": 2},
        }
        self.assertEqual(
            redact(value),
            {
                "Authorization": "[REDACTED]",
                "safe": {"api_token": "[REDACTED]", "count": 2},
            },
        )

    def test_json_formatter_emits_valid_json(self) -> None:
        record = logging.LogRecord("test", logging.INFO, __file__, 1, "message", (), None)
        record.context = {"cookie": "secret", "count": 3}
        payload = json.loads(JsonFormatter().format(record))
        self.assertEqual(payload["message"], "message")
        self.assertEqual(payload["context"]["cookie"], "[REDACTED]")
        self.assertEqual(payload["context"]["count"], 3)

    def test_json_formatter_includes_bound_request_id(self) -> None:
        token = bind_request_id("request-123")
        try:
            record = logging.LogRecord("test", logging.INFO, __file__, 1, "message", (), None)
            payload = json.loads(JsonFormatter().format(record))
        finally:
            reset_request_id(token)
        self.assertEqual(payload["request_id"], "request-123")


if __name__ == "__main__":
    unittest.main()
