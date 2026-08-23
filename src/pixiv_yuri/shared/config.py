"""Fail-closed Phase 0 settings."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SettingsError(ValueError):
    """Raised when settings violate the approved Phase 0 boundary."""


class Settings(BaseModel):
    """Runtime settings for the offline probe."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    enable_network: bool = False
    fixture_manifest: Path = Field(default=Path("fixtures/manifest.json"))
    report_dir: Path = Field(default=Path("var/reports"))
    log_level: str = "INFO"

    @field_validator("enable_network")
    @classmethod
    def network_must_remain_disabled(cls, value: bool) -> bool:
        """Reject live access until the separate G0 decision is complete."""
        if value:
            raise SettingsError("Network access is disabled in Phase 0; complete G0 first.")
        return value

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        """Normalize and validate the structured log level."""
        normalized = value.upper()
        if normalized not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError(f"Unsupported log level: {value}")
        return normalized

    @classmethod
    def from_env(cls, base_dir: Path | None = None) -> Settings:
        """Load the small, non-secret Phase 0 environment surface."""
        root = (base_dir or Path.cwd()).resolve()
        network_value = os.getenv("PYURI_ENABLE_NETWORK", "false").strip().lower()
        if network_value not in {"true", "false", "1", "0", "yes", "no"}:
            raise SettingsError("PYURI_ENABLE_NETWORK must be a boolean value.")

        settings = cls(
            enable_network=network_value in {"true", "1", "yes"},
            fixture_manifest=Path(
                os.getenv("PYURI_FIXTURE_MANIFEST", "fixtures/manifest.json")
            ),
            report_dir=Path(os.getenv("PYURI_REPORT_DIR", "var/reports")),
            log_level=os.getenv("PYURI_LOG_LEVEL", "INFO"),
        )
        return settings.model_copy(
            update={
                "fixture_manifest": _resolve_from(root, settings.fixture_manifest),
                "report_dir": _resolve_from(root, settings.report_dir),
            }
        )


def _resolve_from(root: Path, path: Path) -> Path:
    """Resolve a relative setting from a known application directory."""
    return path.resolve() if path.is_absolute() else (root / path).resolve()
