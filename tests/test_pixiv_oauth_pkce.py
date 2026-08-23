from __future__ import annotations

import http.client
import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from pixiv_yuri.acquisition.providers.pixiv_oauth_pkce import (
    LoopbackOAuthCallbackReceiver,
    PixivOAuthPkceAttempt,
    PixivOAuthPkceError,
    extract_authorization_code,
)


def test_pkce_attempt_exposes_challenge_but_not_verifier() -> None:
    attempt = PixivOAuthPkceAttempt.create(entropy=b"a" * 32)
    parsed = urlparse(attempt.login_url)
    values = parse_qs(parsed.query)

    assert parsed.scheme == "https"
    assert parsed.netloc == "app-api.pixiv.net"
    assert values["code_challenge_method"] == ["S256"]
    assert values["client"] == ["pixiv-android"]
    assert "YWFh" not in attempt.login_url
    assert "REDACTED" in repr(attempt)


def test_callback_url_is_minimized_to_one_short_lived_code() -> None:
    callback = (
        "https://app-api.pixiv.net/web/v1/users/auth/pixiv/callback"
        "?state=discard-me&code=abcDEF123_-"
    )

    assert extract_authorization_code(callback) == "abcDEF123_-"
    assert extract_authorization_code("abcDEF123_-") == "abcDEF123_-"

    with pytest.raises(PixivOAuthPkceError, match="callback_invalid"):
        extract_authorization_code("https://example.invalid/callback?code=abcDEF123_-")


def test_exchange_returns_memory_only_access_lease_and_burns_verifier() -> None:
    attempt = PixivOAuthPkceAttempt.create(entropy=b"b" * 32)
    received: list[tuple[str, str, str | None]] = []

    def exchange(code: str, verifier: str, proxy: str | None) -> tuple[str, int]:
        received.append((code, verifier, proxy))
        return "runtime-access-value", 3600

    session = attempt.exchange(
        "abcDEF123_-",
        exchanger=exchange,
        proxy="http://127.0.0.1:41080",
        now=datetime(2026, 8, 23, tzinfo=UTC),
    )

    assert received[0][0] == "abcDEF123_-"
    assert len(received[0][1]) == 43
    assert session.reveal_for_request(now=datetime(2026, 8, 23, tzinfo=UTC)) == (
        "runtime-access-value"
    )
    session.close()
    assert session.closed is True
    assert "runtime-access-value" not in repr(session)
    assert "consumed=True" in repr(attempt)

    with pytest.raises(PixivOAuthPkceError, match="attempt_consumed"):
        attempt.exchange(
            "abcDEF123_-",
            exchanger=exchange,
            proxy=None,
        )


def test_extension_callback_receiver_accepts_one_exact_loopback_handoff() -> None:
    callback = (
        "https://app-api.pixiv.net/web/v1/users/auth/pixiv/callback"
        "?state=discard-me&code=abcDEF123_-"
    )
    with LoopbackOAuthCallbackReceiver(port=0) as receiver:
        connection = http.client.HTTPConnection("127.0.0.1", receiver.port, timeout=2)
        connection.request(
            "POST",
            "/oauth/callback",
            body=callback,
            headers={
                "Content-Type": "text/plain",
                "Origin": f"chrome-extension://{'a' * 32}",
            },
        )
        response = connection.getresponse()
        response.read()
        connection.close()

        assert response.status == 204
        assert receiver.wait(timeout_seconds=1) == callback


def test_callback_receiver_exposes_only_a_no_store_login_redirect() -> None:
    attempt = PixivOAuthPkceAttempt.create(entropy=b"c" * 32)
    with LoopbackOAuthCallbackReceiver(port=0, login_url=attempt.login_url) as receiver:
        connection = http.client.HTTPConnection("127.0.0.1", receiver.port, timeout=2)
        connection.request("GET", "/oauth/login")
        response = connection.getresponse()
        response.read()
        connection.close()

        assert response.status == 302
        assert response.getheader("Location") == attempt.login_url
        assert response.getheader("Cache-Control") == "no-store"
        assert response.getheader("Referrer-Policy") == "no-referrer"


def test_extension_manifest_has_narrow_callback_bridge_without_storage() -> None:
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads(
        (root / "apps" / "browser-extension" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    worker = (root / "apps" / "browser-extension" / "oauth-callback.js").read_text(
        encoding="utf-8"
    )

    assert manifest["background"] == {"service_worker": "oauth-callback.js"}
    assert "webRequest" in manifest["permissions"]
    assert "storage" not in manifest["permissions"]
    assert "http://127.0.0.1/*" in manifest["host_permissions"]
    assert "downloads" not in worker
    assert "storage" not in worker
    assert "127.0.0.1:41180/oauth/callback" in worker
