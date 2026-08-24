"""CLI entry point for the Phase 0 FastAPI service."""

from __future__ import annotations

import os
import ssl
from dataclasses import dataclass
from ipaddress import ip_address
from pathlib import Path

import uvicorn as uvicorn

PRIVATE_CONTAINER_SCOPE = "private_container"


class ApiExposureError(RuntimeError):
    """Raised when an unauthenticated API binding could escape its approved boundary."""


@dataclass(frozen=True, slots=True)
class TlsFiles:
    """Validated local certificate/key paths passed directly to Uvicorn."""

    certificate: Path
    private_key: Path


def main() -> None:
    """Run the API with environment-only operational configuration."""
    host = os.getenv("PYURI_API_HOST", "127.0.0.1")
    configured_port = os.getenv("PYURI_API_PORT") or os.getenv("PORT")
    port = int(configured_port) if configured_port else 8000
    log_level = os.getenv("PYURI_LOG_LEVEL", "INFO").lower()
    validate_api_binding(host, os.getenv("PYURI_API_DEPLOYMENT_SCOPE"))
    tls_files = validate_tls_files(
        os.getenv("PYURI_API_TLS_CERT_FILE"), os.getenv("PYURI_API_TLS_KEY_FILE")
    )
    if tls_files is None:
        uvicorn.run("pixiv_yuri.api.app:app", host=host, port=port, log_level=log_level)
    else:
        uvicorn.run(
            "pixiv_yuri.api.app:app",
            host=host,
            port=port,
            log_level=log_level,
            ssl_certfile=str(tls_files.certificate),
            ssl_keyfile=str(tls_files.private_key),
            ssl_version=ssl.PROTOCOL_TLS_SERVER,
        )


def validate_api_binding(host: str, deployment_scope: str | None) -> None:
    """Permit loopback, or wildcard only inside the declared private-container profile."""
    try:
        address = ip_address(host)
    except ValueError as exc:
        raise ApiExposureError("API host must be an explicit IP address") from exc
    if address.is_loopback:
        return
    if address.is_unspecified and deployment_scope == PRIVATE_CONTAINER_SCOPE:
        return
    raise ApiExposureError(
        "Unauthenticated API may bind only to loopback or the private-container profile"
    )


def validate_tls_files(certificate: str | None, private_key: str | None) -> TlsFiles | None:
    """Require a complete, distinct and absolute TLS file pair or no TLS options."""
    if certificate is None and private_key is None:
        return None
    if not certificate or not private_key:
        raise ApiExposureError("TLS certificate and private key must be configured together")
    certificate_path = Path(certificate)
    key_path = Path(private_key)
    if not certificate_path.is_absolute() or not key_path.is_absolute():
        raise ApiExposureError("TLS certificate and private key paths must be absolute")
    if certificate_path == key_path:
        raise ApiExposureError("TLS certificate and private key must be distinct files")
    if not certificate_path.is_file() or not key_path.is_file():
        raise ApiExposureError("TLS certificate or private key file is unavailable")
    return TlsFiles(certificate=certificate_path, private_key=key_path)
