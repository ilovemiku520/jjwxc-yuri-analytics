from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from pixiv_yuri.api.app import _configured_consumer_authorizer, create_app
from pixiv_yuri.api.auth import (
    ConsumerAuthenticationError,
    TrustedHmacProxyAuthorizer,
    trusted_proxy_headers,
)
from tests.test_api_catalog import build_catalog_factory

SECRET = b"s" * 32
PROXY_ID = "private-edge"
ISSUED_AT = 1_800_000_000


def _headers(
    *,
    path: str = "/api/v1/analytics/freshness",
    scopes: frozenset[str] = frozenset({"analytics:read"}),
    issued_at: int = ISSUED_AT,
) -> Mapping[str, str]:
    return trusted_proxy_headers(
        secret=SECRET,
        proxy_id=PROXY_ID,
        method="GET",
        path=path,
        subject="researcher-42",
        scopes=scopes,
        issued_at=issued_at,
    )


def _request(
    headers: Mapping[str, str],
    *,
    path: str = "/api/v1/analytics/freshness",
    duplicate_subject: bool = False,
) -> Request:
    encoded = [(key.lower().encode(), value.encode()) for key, value in headers.items()]
    if duplicate_subject:
        encoded.append((b"x-pyuri-subject", b"other-researcher"))
    return Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": "https",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"ignored=literal",
            "headers": encoded,
            "client": ("127.0.0.1", 12345),
            "server": ("localhost", 443),
        }
    )


def _authorizer() -> TrustedHmacProxyAuthorizer:
    return TrustedHmacProxyAuthorizer(
        proxy_id=PROXY_ID,
        secret=SECRET,
        maximum_age_seconds=30,
        clock=lambda: float(ISSUED_AT + 10),
    )


def test_trusted_proxy_assertion_returns_only_minimized_identity() -> None:
    identity = _authorizer().authorize(_request(_headers()))

    assert identity.subject == "researcher-42"
    assert identity.scopes == frozenset({"analytics:read"})


@pytest.mark.parametrize("mutation", ["signature", "proxy", "expired", "future", "scope"])
def test_trusted_proxy_assertion_fails_closed(mutation: str) -> None:
    headers = dict(_headers())
    if mutation == "signature":
        headers["X-Pyuri-Signature"] = "0" * 64
    elif mutation == "proxy":
        headers["X-Pyuri-Proxy-ID"] = "untrusted-edge"
    elif mutation == "expired":
        headers = dict(_headers(issued_at=ISSUED_AT - 31))
    elif mutation == "future":
        headers = dict(_headers(issued_at=ISSUED_AT + 16))
    else:
        headers["X-Pyuri-Scopes"] = "analytics:read  admin"

    with pytest.raises(ConsumerAuthenticationError):
        _authorizer().authorize(_request(headers))


def test_trusted_proxy_rejects_missing_and_duplicate_headers() -> None:
    headers = dict(_headers())
    headers.pop("X-Pyuri-Signature")
    with pytest.raises(ConsumerAuthenticationError):
        _authorizer().authorize(_request(headers))
    with pytest.raises(ConsumerAuthenticationError):
        _authorizer().authorize(_request(_headers(), duplicate_subject=True))


def test_trusted_proxy_integrates_with_scope_and_security_status() -> None:
    factory = build_catalog_factory()
    path = "/api/v1/analytics/freshness"
    security_path = "/api/v1/operations/security-status"
    with TestClient(
        create_app(
            lambda: None,
            session_factory=factory,
            consumer_authorizer=_authorizer(),
        )
    ) as client:
        allowed = client.get(path, headers=_headers(path=path))
        denied = client.get(
            path,
            headers=_headers(path=path, scopes=frozenset({"other:read"})),
        )
        security = client.get(security_path, headers=_headers(path=security_path))

    assert allowed.status_code == 200
    assert denied.status_code == 403
    assert denied.json() == {"detail": "analytics_read_scope_required"}
    assert security.status_code == 200
    assert security.json()["identity_adapter_configured"] is True


def test_trusted_proxy_environment_configuration_is_default_off_and_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PYURI_CONSUMER_AUTH_MODE", raising=False)
    assert _configured_consumer_authorizer() is None

    monkeypatch.setenv("PYURI_CONSUMER_AUTH_MODE", "trusted_hmac_proxy")
    monkeypatch.setenv("PYURI_TRUSTED_PROXY_ID", PROXY_ID)
    monkeypatch.delenv("PYURI_TRUSTED_PROXY_HMAC_SECRET_FILE", raising=False)
    monkeypatch.setenv("PYURI_TRUSTED_PROXY_HMAC_SECRET", SECRET.decode())
    configured = _configured_consumer_authorizer()
    assert isinstance(configured, TrustedHmacProxyAuthorizer)

    monkeypatch.setenv("PYURI_TRUSTED_PROXY_HMAC_SECRET", "too-short")
    with pytest.raises(ValueError, match="at least 32 bytes"):
        _configured_consumer_authorizer()


def test_trusted_proxy_secret_file_is_absolute_exclusive_and_bounded(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    secret_file = tmp_path / "proxy-secret"
    secret_file.write_bytes(SECRET)
    monkeypatch.setenv("PYURI_CONSUMER_AUTH_MODE", "trusted_hmac_proxy")
    monkeypatch.setenv("PYURI_TRUSTED_PROXY_ID", PROXY_ID)
    monkeypatch.delenv("PYURI_TRUSTED_PROXY_HMAC_SECRET", raising=False)
    monkeypatch.setenv("PYURI_TRUSTED_PROXY_HMAC_SECRET_FILE", str(secret_file))
    assert isinstance(_configured_consumer_authorizer(), TrustedHmacProxyAuthorizer)

    monkeypatch.setenv("PYURI_TRUSTED_PROXY_HMAC_SECRET", SECRET.decode())
    with pytest.raises(ValueError, match="either inline or file"):
        _configured_consumer_authorizer()
