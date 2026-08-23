"""Runtime-only Pixiv OAuth PKCE bootstrap for the bounded App API adapter."""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import queue
import re
import secrets
import socketserver
import subprocess
import threading
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol
from urllib.parse import parse_qs, urlencode, urlparse

from pixiv_yuri.acquisition.operator_session import RuntimeSession

LOGIN_URL = "https://app-api.pixiv.net/web/v1/login"
TOKEN_URL = "https://oauth.secure.pixiv.net/auth/token"
REDIRECT_URI = "https://app-api.pixiv.net/web/v1/users/auth/pixiv/callback"
USER_AGENT = "PixivAndroidApp/5.0.234 (Android 11; Pixel 5)"
LOCAL_PROXY = "http://127.0.0.1:41080"
CALLBACK_RECEIVER_HOST = "127.0.0.1"
CALLBACK_RECEIVER_PORT = 41180
CALLBACK_RECEIVER_PATH = "/oauth/callback"
CALLBACK_LOGIN_PATH = "/oauth/login"
_CODE_PATTERN = re.compile(r"^[A-Za-z0-9._~+/=-]{8,2048}$")
_EXTENSION_ORIGIN_PATTERN = re.compile(r"^chrome-extension://[a-p]{32}$")


class PixivOAuthPkceError(RuntimeError):
    """Payload-free OAuth bootstrap failure."""


class OAuthCodeExchanger(Protocol):
    """Exchange a short-lived authorization code without retaining its inputs."""

    def __call__(
        self,
        code: str,
        verifier: str,
        proxy: str | None,
    ) -> tuple[str, int]: ...


class _OAuthCallbackServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        port: int = CALLBACK_RECEIVER_PORT,
        *,
        login_url: str | None = None,
    ) -> None:
        self.callbacks: queue.Queue[str] = queue.Queue(maxsize=1)
        self.login_url = login_url
        super().__init__(
            (CALLBACK_RECEIVER_HOST, port),
            _OAuthCallbackHandler,
        )


class _OAuthCallbackHandler(http.server.BaseHTTPRequestHandler):
    server: _OAuthCallbackServer

    def do_GET(self) -> None:
        if self.path != CALLBACK_LOGIN_PATH or self.server.login_url is None:
            self.send_error(404)
            return
        self.send_response(302)
        self.send_header("Location", self.server.login_url)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()

    def do_POST(self) -> None:
        if self.path != CALLBACK_RECEIVER_PATH:
            self.send_error(404)
            return
        origin = self.headers.get("Origin", "")
        host = self.headers.get("Host", "")
        content_type = self.headers.get("Content-Type", "")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if (
            not (
                _EXTENSION_ORIGIN_PATTERN.fullmatch(origin)
                or origin == "https://app-api.pixiv.net"
            )
            or host != f"{CALLBACK_RECEIVER_HOST}:{self.server.server_port}"
            or not content_type.startswith("text/plain")
            or not 1 <= length <= 4096
        ):
            self.send_error(400)
            return
        try:
            callback = self.rfile.read(length).decode("utf-8")
            extract_authorization_code(callback)
            self.server.callbacks.put_nowait(callback)
        except (UnicodeDecodeError, PixivOAuthPkceError, queue.Full):
            self.send_error(400)
            return
        self.send_response(204)
        self.send_header("Cache-Control", "no-store")
        if origin == "https://app-api.pixiv.net":
            self.send_header("Access-Control-Allow-Origin", origin)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        del format, args


class LoopbackOAuthCallbackReceiver:
    """Receive one extension-forwarded callback on a fixed loopback-only port."""

    __slots__ = ("_server", "_thread")

    def __init__(
        self,
        *,
        port: int = CALLBACK_RECEIVER_PORT,
        login_url: str | None = None,
    ) -> None:
        try:
            self._server = _OAuthCallbackServer(port, login_url=login_url)
        except OSError:
            raise PixivOAuthPkceError("pixiv_oauth_callback_receiver_unavailable") from None
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="pyuri-oauth-loopback",
            daemon=True,
        )

    @property
    def port(self) -> int:
        return self._server.server_port

    def __enter__(self) -> LoopbackOAuthCallbackReceiver:
        self._thread.start()
        return self

    def wait(self, *, timeout_seconds: float) -> str:
        if not 1 <= timeout_seconds <= 600:
            raise ValueError("OAuth callback timeout is outside the fixed boundary.")
        try:
            return self._server.callbacks.get(timeout=timeout_seconds)
        except queue.Empty:
            raise PixivOAuthPkceError("pixiv_oauth_callback_timeout") from None

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2)

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        del exc_type, exc, traceback
        self.close()


class PixivOAuthPkceAttempt:
    """One-use PKCE verifier whose mutable buffer is cleared after exchange."""

    __slots__ = ("_consumed", "_verifier", "login_url")

    def __init__(self, verifier: bytearray, login_url: str) -> None:
        self._verifier = verifier
        self.login_url = login_url
        self._consumed = False

    @classmethod
    def create(cls, *, entropy: bytes | None = None) -> PixivOAuthPkceAttempt:
        """Create a fresh PKCE challenge; deterministic entropy is only for tests."""
        verifier_text = (
            base64.urlsafe_b64encode(entropy).rstrip(b"=").decode("ascii")
            if entropy is not None
            else secrets.token_urlsafe(48)
        )
        if not 43 <= len(verifier_text) <= 128:
            raise ValueError("PKCE verifier length is invalid.")
        verifier = bytearray(verifier_text, "ascii")
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier).digest())
            .rstrip(b"=")
            .decode("ascii")
        )
        parameters = {
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "client": "pixiv-android",
        }
        url = f"{LOGIN_URL}?{urlencode(parameters)}"
        return cls(verifier, url)

    def exchange(
        self,
        callback_value: str,
        *,
        exchanger: OAuthCodeExchanger,
        proxy: str | None,
        now: datetime | None = None,
    ) -> RuntimeSession:
        """Consume the verifier and return an access-token lease held only in memory."""
        if self._consumed:
            raise PixivOAuthPkceError("pixiv_oauth_pkce_attempt_consumed")
        self._consumed = True
        verifier = ""
        access_token = ""
        try:
            code = extract_authorization_code(callback_value)
            verifier = self._verifier.decode("ascii")
            access_token, expires_in = exchanger(code, verifier, proxy)
            if not access_token or len(access_token) > 8192:
                raise PixivOAuthPkceError("pixiv_oauth_access_token_invalid")
            if not 60 <= expires_in <= 86_400:
                raise PixivOAuthPkceError("pixiv_oauth_expiry_invalid")
            created_at = now or datetime.now(UTC)
            if created_at.tzinfo is None or created_at.utcoffset() is None:
                raise ValueError("OAuth session creation time must include a timezone.")
            lease_seconds = min(expires_in, 60 * 60)
            return RuntimeSession(
                bytearray(access_token, "utf-8"),
                created_at.astimezone(UTC) + timedelta(seconds=lease_seconds),
                established_at=created_at,
            )
        finally:
            callback_value = ""
            verifier = ""
            access_token = ""
            self.close()

    def close(self) -> None:
        """Best-effort zeroize the one-use verifier."""
        for index in range(len(self._verifier)):
            self._verifier[index] = 0
        self._consumed = True

    def __repr__(self) -> str:
        return (
            "PixivOAuthPkceAttempt(verifier=[REDACTED], "
            f"consumed={self._consumed!r})"
        )


def extract_authorization_code(value: str) -> str:
    """Accept either a callback URL or the code value without retaining other fields."""
    candidate = value.strip()
    if not candidate or len(candidate) > 4096 or any(char.isspace() for char in candidate):
        raise PixivOAuthPkceError("pixiv_oauth_callback_invalid")
    if "://" in candidate:
        parsed = urlparse(candidate)
        if (
            parsed.scheme != "https"
            or parsed.netloc != "app-api.pixiv.net"
            or parsed.path != "/web/v1/users/auth/pixiv/callback"
        ):
            raise PixivOAuthPkceError("pixiv_oauth_callback_invalid")
        values = parse_qs(parsed.query, strict_parsing=True)
        codes = values.get("code", [])
        if len(codes) != 1:
            raise PixivOAuthPkceError("pixiv_oauth_callback_invalid")
        candidate = codes[0]
    if not _CODE_PATTERN.fullmatch(candidate):
        raise PixivOAuthPkceError("pixiv_oauth_code_invalid")
    return candidate


def exchange_pixiv_oauth_code(
    code: str,
    verifier: str,
    proxy: str | None,
) -> tuple[str, int]:
    """Exchange once through the pinned library's public-client identity."""
    if proxy not in (None, LOCAL_PROXY):
        raise PixivOAuthPkceError("pixiv_oauth_proxy_not_allowed")
    try:
        from pixivpy3 import AppPixivAPI

        api = AppPixivAPI()
        response = api.requests.post(
            TOKEN_URL,
            data={
                "client_id": api.client_id,
                "client_secret": api.client_secret,
                "code": code,
                "code_verifier": verifier,
                "grant_type": "authorization_code",
                "include_policy": "true",
                "redirect_uri": REDIRECT_URI,
            },
            headers={"User-Agent": USER_AGENT},
            proxies={"https": proxy} if proxy else None,
            timeout=(10, 30),
            allow_redirects=False,
        )
        if response.status_code != 200 or len(response.content) > 65_536:
            raise PixivOAuthPkceError("pixiv_oauth_exchange_rejected")
        payload = response.json()
        if not isinstance(payload, Mapping):
            raise PixivOAuthPkceError("pixiv_oauth_response_invalid")
        access_token = payload.get("access_token")
        expires_in = payload.get("expires_in")
        if not isinstance(access_token, str) or type(expires_in) is not int:
            raise PixivOAuthPkceError("pixiv_oauth_response_invalid")
        return access_token, expires_in
    except PixivOAuthPkceError:
        raise
    except (ImportError, json.JSONDecodeError, OSError, ValueError):
        raise PixivOAuthPkceError("pixiv_oauth_exchange_failed") from None
    except Exception:
        raise PixivOAuthPkceError("pixiv_oauth_exchange_failed") from None


def launch_project_pixiv_browser(login_url: str, launcher: Path) -> None:
    """Open the PKCE login URL in the existing WARP-backed project Chrome profile."""
    parsed = urlparse(login_url)
    if parsed.scheme != "https" or parsed.netloc != "app-api.pixiv.net":
        raise PixivOAuthPkceError("pixiv_oauth_login_url_invalid")
    if not launcher.is_file():
        raise PixivOAuthPkceError("pixiv_oauth_browser_launcher_missing")
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(launcher),
            "-StartUrl",
            login_url,
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=75,
    )
    if completed.returncode != 0:
        raise PixivOAuthPkceError("pixiv_oauth_browser_launch_failed")


def open_runtime_oauth_session(
    *,
    proxy: str | None,
    callback_reader: Callable[[str], str],
    launcher: Path,
    callback_mode: str = "automatic",
) -> RuntimeSession:
    """Launch browser login, read one hidden callback, and exchange it in memory."""
    if callback_mode not in {"automatic", "hidden_paste"}:
        raise ValueError("OAuth callback mode is invalid.")
    attempt = PixivOAuthPkceAttempt.create()
    try:
        if callback_mode == "automatic":
            with LoopbackOAuthCallbackReceiver(login_url=attempt.login_url) as receiver:
                launch_project_pixiv_browser(attempt.login_url, launcher)
                print("oauth_callback_waiting")
                callback_value = receiver.wait(timeout_seconds=300)
        else:
            launch_project_pixiv_browser(attempt.login_url, launcher)
            callback_value = callback_reader(
                "Paste the short-lived callback URL or code locally (input hidden): "
            )
        return attempt.exchange(
            callback_value,
            exchanger=exchange_pixiv_oauth_code,
            proxy=proxy,
        )
    finally:
        attempt.close()
