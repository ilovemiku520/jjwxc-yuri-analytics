"""One-request, no-login probe for public JJWXC aggregate metadata."""

from __future__ import annotations

import argparse
import gzip
import io
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pixiv_yuri.jjwxc.html_parser import MAX_HTML_BYTES, JjwxcParseError, parse_novel_page

_USER_AGENT = "JJWXC-Yuri-Research/0.1 (+mailto:ilovemiku520@outlook.com)"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


def probe_public_novel(
    novel_id: str,
    *,
    timeout_seconds: float = 20.0,
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    """Perform exactly one bounded GET and return a minimized candidate envelope."""
    if os.getenv("JJYURI_ENABLE_NETWORK", "false").lower() != "true":
        raise RuntimeError("network_disabled")
    if not re.fullmatch(r"[1-9][0-9]{0,11}", novel_id):
        raise ValueError("novel_id_invalid")
    url = f"https://www.jjwxc.net/onebook.php?novelid={novel_id}"
    request = urllib.request.Request(
        url,
        method="GET",
        headers={"Accept": "text/html", "User-Agent": _USER_AGENT},
    )
    opener = urllib.request.build_opener(_NoRedirect())
    with opener.open(request, timeout=timeout_seconds) as response:
        if response.status != 200:
            raise RuntimeError("source_status_not_ok")
        final_url = response.geturl()
        if final_url != url:
            raise RuntimeError("source_redirect_blocked")
        content_type = response.headers.get_content_type().lower()
        if content_type != "text/html":
            raise RuntimeError("source_content_type_invalid")
        payload = response.read(MAX_HTML_BYTES + 1)
        if len(payload) > MAX_HTML_BYTES:
            raise RuntimeError("source_body_too_large")
        content_encoding = response.headers.get("Content-Encoding", "identity").lower()
        if content_encoding == "gzip":
            with gzip.GzipFile(fileobj=io.BytesIO(payload), mode="rb") as archive:
                payload = archive.read(MAX_HTML_BYTES + 1)
            if len(payload) > MAX_HTML_BYTES:
                raise RuntimeError("source_body_too_large")
        elif content_encoding not in {"", "identity"}:
            raise RuntimeError("source_content_encoding_invalid")
    candidate = parse_novel_page(
        payload,
        novel_id=novel_id,
        observed_at=observed_at or datetime.now(UTC),
    )
    return {
        "status": "candidate_ready",
        "candidate": candidate.model_dump(mode="json"),
        "boundary": {
            "request_count": 1,
            "network_concurrency": 1,
            "automatic_retries": 0,
            "login_used": False,
            "credentials_requested": False,
            "raw_payload_persisted": False,
            "chapter_content_persisted": False,
            "comment_content_persisted": False,
            "canonical_ingest_authorized": False,
        },
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Probe one public JJWXC novel metadata page.")
    parser.add_argument("novel_id")
    parser.add_argument("--execute-live", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("var/candidates/jjwxc-public-novel.candidate.json"),
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("var/reports/jjwxc-public-probe.json"),
    )
    args = parser.parse_args(argv)
    if not args.execute_live:
        report: dict[str, Any] = {
            "status": "dry_run",
            "request_count": 0,
            "canonical_ingest_authorized": False,
        }
        _write_json(args.report, report)
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0
    try:
        result = probe_public_novel(args.novel_id)
    except (JjwxcParseError, RuntimeError, ValueError, urllib.error.URLError, TimeoutError):
        blocked = {
            "status": "blocked",
            "violation": "jjwxc_public_probe_failed",
            "canonical_ingest_authorized": False,
        }
        _write_json(args.report, blocked)
        print(json.dumps(blocked, ensure_ascii=False, sort_keys=True))
        return 1
    _write_json(args.output, result)
    report = {
        "status": "candidate_ready",
        "candidate_count": 1,
        **result["boundary"],
    }
    _write_json(args.report, report)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
