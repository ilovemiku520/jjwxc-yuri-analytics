"""Private bounded response cache for resumable JJWXC metadata collection."""

from __future__ import annotations

import gzip
import hashlib
import io
import os
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from pixiv_yuri.jjwxc.public_probe import _NoRedirect

_USER_AGENT = "JJWXC-Yuri-Research/0.1 (+mailto:ilovemiku520@outlook.com)"


@dataclass(frozen=True, slots=True)
class CachedFetch:
    payload: bytes
    cache_hit: bool
    sha256: str


class JjwxcSourceCache:
    """Store short-lived raw responses outside the public application tree."""

    def __init__(self, root: Path, *, ttl_seconds: int) -> None:
        if ttl_seconds < 60 or ttl_seconds > 7 * 24 * 60 * 60:
            raise ValueError("cache_ttl_out_of_range")
        self.root = root.resolve()
        self.ttl_seconds = ttl_seconds

    def fetch(
        self,
        url: str,
        *,
        allowed_hosts: frozenset[str],
        expected_content_types: tuple[str, ...],
        max_bytes: int,
        referer: str | None = None,
    ) -> CachedFetch:
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.hostname not in allowed_hosts or parts.fragment:
            raise ValueError("cache_source_url_not_allowlisted")
        if max_bytes < 1 or max_bytes > 2_000_000:
            raise ValueError("cache_max_bytes_out_of_range")
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        target = self.root / digest[:2] / f"{digest}.html.gz"
        if target.is_file() and time.time() - target.stat().st_mtime <= self.ttl_seconds:
            payload = gzip.decompress(target.read_bytes())
            if 0 < len(payload) <= max_bytes:
                return CachedFetch(
                    payload=payload,
                    cache_hit=True,
                    sha256=hashlib.sha256(payload).hexdigest(),
                )
        headers = {
            "Accept": ", ".join(expected_content_types),
            "Accept-Encoding": "gzip, identity",
            "User-Agent": _USER_AGENT,
        }
        if referer:
            headers["Referer"] = referer
        request = urllib.request.Request(url, method="GET", headers=headers)
        with urllib.request.build_opener(_NoRedirect()).open(request, timeout=25) as response:
            if response.status != 200 or response.geturl() != url:
                raise RuntimeError("cache_source_status_invalid")
            content_type = response.headers.get_content_type().lower()
            if not any(content_type.startswith(item) for item in expected_content_types):
                raise RuntimeError("cache_source_content_type_invalid")
            payload = response.read(max_bytes + 1)
            encoding = response.headers.get("Content-Encoding", "identity").lower()
            if encoding == "gzip":
                with gzip.GzipFile(fileobj=io.BytesIO(payload), mode="rb") as archive:
                    payload = archive.read(max_bytes + 1)
            elif encoding not in {"", "identity"}:
                raise RuntimeError("cache_source_content_encoding_invalid")
        if not payload or len(payload) > max_bytes:
            raise RuntimeError("cache_source_body_size_invalid")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f"{target.name}.{os.getpid()}.tmp")
        temporary.write_bytes(gzip.compress(payload, compresslevel=6))
        temporary.replace(target)
        return CachedFetch(
            payload=payload,
            cache_hit=False,
            sha256=hashlib.sha256(payload).hexdigest(),
        )
