from __future__ import annotations

from email.message import Message
from pathlib import Path

from pixiv_yuri.jjwxc.source_cache import JjwxcSourceCache


class _Response:
    status = 200

    def __init__(self, url: str, payload: bytes) -> None:
        self._url = url
        self._payload = payload
        self.headers = Message()
        self.headers["Content-Type"] = "text/html"

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def geturl(self) -> str:
        return self._url

    def read(self, _limit: int) -> bytes:
        return self._payload


class _Opener:
    def __init__(self, payloads: list[bytes]) -> None:
        self.payloads = payloads
        self.requests = []

    def open(self, request: object, timeout: int) -> _Response:
        del timeout
        self.requests.append(request)
        return _Response(request.full_url, self.payloads.pop(0))


def test_authenticated_fetch_bypasses_public_cache_and_stays_memory_only(
    tmp_path: Path, monkeypatch
) -> None:
    url = "https://www.jjwxc.net/onebook.php?novelid=88"
    opener = _Opener([b"public", b"authenticated", b"public-next"])
    monkeypatch.setattr("urllib.request.build_opener", lambda *_args: opener)
    cache = JjwxcSourceCache(tmp_path, ttl_seconds=60)

    public = cache.fetch(
        url,
        allowed_hosts=frozenset({"www.jjwxc.net"}),
        expected_content_types=("text/html",),
        max_bytes=100,
    )
    monkeypatch.setenv("JJYURI_SESSION_COOKIE", "session=private")
    authenticated = cache.fetch(
        url,
        allowed_hosts=frozenset({"www.jjwxc.net"}),
        expected_content_types=("text/html",),
        max_bytes=100,
    )
    monkeypatch.delenv("JJYURI_SESSION_COOKIE")
    cached_public = cache.fetch(
        url,
        allowed_hosts=frozenset({"www.jjwxc.net"}),
        expected_content_types=("text/html",),
        max_bytes=100,
    )

    assert public.payload == b"public"
    assert authenticated.payload == b"authenticated"
    assert authenticated.cache_hit is False
    assert cached_public.payload == b"public"
    assert cached_public.cache_hit is True
    assert len(opener.requests) == 2
    assert opener.requests[1].get_header("Cookie") == "session=private"
