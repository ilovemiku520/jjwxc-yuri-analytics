from __future__ import annotations

import ssl
from pathlib import Path
from typing import Any

import pytest

from pixiv_yuri.api import cli


def test_cli_defaults_to_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.delenv("PYURI_API_HOST", raising=False)
    monkeypatch.delenv("PYURI_API_DEPLOYMENT_SCOPE", raising=False)
    monkeypatch.delenv("PYURI_API_TLS_CERT_FILE", raising=False)
    monkeypatch.delenv("PYURI_API_TLS_KEY_FILE", raising=False)
    monkeypatch.setattr(cli.uvicorn, "run", lambda *args, **kwargs: captured.update(kwargs))

    cli.main()

    assert captured["host"] == "127.0.0.1"


def test_cli_rejects_wildcard_without_private_container_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PYURI_API_HOST", "0.0.0.0")
    monkeypatch.delenv("PYURI_API_DEPLOYMENT_SCOPE", raising=False)

    with pytest.raises(cli.ApiExposureError, match="loopback"):
        cli.main()


def test_cli_allows_declared_private_container_wildcard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.setenv("PYURI_API_HOST", "0.0.0.0")
    monkeypatch.setenv("PYURI_API_DEPLOYMENT_SCOPE", "private_container")
    monkeypatch.delenv("PYURI_API_TLS_CERT_FILE", raising=False)
    monkeypatch.delenv("PYURI_API_TLS_KEY_FILE", raising=False)
    monkeypatch.setattr(cli.uvicorn, "run", lambda *args, **kwargs: captured.update(kwargs))

    cli.main()

    assert captured["host"] == "0.0.0.0"


@pytest.mark.parametrize("host", ["192.168.1.20", "8.8.8.8", "api.example.test"])
def test_cli_rejects_lan_public_and_hostname_bindings_even_with_private_scope(
    host: str,
) -> None:
    with pytest.raises(cli.ApiExposureError):
        cli.validate_api_binding(host, "private_container")


def test_cli_tls_files_are_complete_absolute_and_distinct(tmp_path: Path) -> None:
    certificate = tmp_path / "certificate.pem"
    private_key = tmp_path / "private-key.pem"
    certificate.write_text("test certificate", encoding="utf-8")
    private_key.write_text("test key", encoding="utf-8")

    configured = cli.validate_tls_files(str(certificate), str(private_key))
    assert configured == cli.TlsFiles(certificate, private_key)
    with pytest.raises(cli.ApiExposureError, match="configured together"):
        cli.validate_tls_files(str(certificate), None)
    with pytest.raises(cli.ApiExposureError, match="absolute"):
        cli.validate_tls_files("certificate.pem", "private-key.pem")
    with pytest.raises(cli.ApiExposureError, match="distinct"):
        cli.validate_tls_files(str(certificate), str(certificate))


def test_cli_passes_validated_tls_files_to_uvicorn(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, Any] = {}
    certificate = tmp_path / "certificate.pem"
    private_key = tmp_path / "private-key.pem"
    certificate.write_text("test certificate", encoding="utf-8")
    private_key.write_text("test key", encoding="utf-8")
    monkeypatch.setenv("PYURI_API_TLS_CERT_FILE", str(certificate))
    monkeypatch.setenv("PYURI_API_TLS_KEY_FILE", str(private_key))
    monkeypatch.setattr(cli.uvicorn, "run", lambda *args, **kwargs: captured.update(kwargs))

    cli.main()

    assert captured["ssl_certfile"] == str(certificate)
    assert captured["ssl_keyfile"] == str(private_key)
    assert captured["ssl_version"] == ssl.PROTOCOL_TLS_SERVER
