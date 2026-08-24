"""Bounded daily collection of one allowlisted public JJWXC yuri ranking."""

from __future__ import annotations

import argparse
import gzip
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, date, datetime
from datetime import time as datetime_time
from html.parser import HTMLParser
from typing import Literal, cast
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from pixiv_yuri.jjwxc.models import JjwxcNovelCandidate
from pixiv_yuri.jjwxc.persistence import JjwxcRankingSnapshot
from pixiv_yuri.jjwxc.public_probe import _NoRedirect, probe_public_novel
from pixiv_yuri.jjwxc.snapshot_store import store_novel_snapshot
from pixiv_yuri.shared.database import build_engine, build_session_factory

_USER_AGENT = "JJWXC-Yuri-Research/0.1 (+mailto:ilovemiku520@outlook.com)"
_MAX_RANKING_BYTES = 1_500_000
_SHANGHAI = ZoneInfo("Asia/Shanghai")

RANKING_URLS = {
    "yuri_current": "https://www.jjwxc.net/channeltoplist.php?rchannelid=2&str=10",
    "yuri_all_time_points": "https://www.jjwxc.net/topten.php?orderstr=7&t=6",
}
RankingStatus = Literal["连载", "完结", "暂停", "锁定", "未知"]


class JjwxcRankingEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    rank: int = Field(ge=1, le=200)
    novel_id: str = Field(pattern=r"^[1-9][0-9]{0,11}$")
    author_id: str = Field(pattern=r"^[1-9][0-9]{0,11}$")
    title: str = Field(min_length=1, max_length=200)
    author_display_name: str = Field(min_length=1, max_length=80)
    novel_type: str = Field(min_length=1, max_length=100)
    status: RankingStatus
    word_count: int = Field(ge=0)
    points: int = Field(ge=0)
    published_at: datetime


class _RankingParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.entries: list[JjwxcRankingEntry] = []
        self._in_row = False
        self._in_cell = False
        self._ignored_depth = 0
        self._cells: list[str] = []
        self._cell_parts: list[str] = []
        self._novel_id: str | None = None
        self._author_id: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self._ignored_depth += 1
            return
        if self._ignored_depth:
            return
        if tag == "tr":
            self._in_row = True
            self._cells = []
            self._novel_id = None
            self._author_id = None
        elif tag == "td" and self._in_row:
            self._in_cell = True
            self._cell_parts = []
        elif tag == "a" and self._in_cell:
            href = dict(attrs).get("href") or ""
            if match := re.search(r"onebook\.php\?novelid=([1-9][0-9]{0,11})", href):
                self._novel_id = match.group(1)
            if match := re.search(r"oneauthor\.php\?authorid=([1-9][0-9]{0,11})", href):
                self._author_id = match.group(1)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self._ignored_depth:
            self._ignored_depth -= 1
            return
        if self._ignored_depth:
            return
        if tag == "td" and self._in_cell:
            self._cells.append(" ".join("".join(self._cell_parts).split()))
            self._in_cell = False
        elif tag == "tr" and self._in_row:
            self._finish_row()
            self._in_row = False

    def handle_data(self, data: str) -> None:
        if self._in_cell and not self._ignored_depth:
            self._cell_parts.append(data)

    def _finish_row(self) -> None:
        if not self._novel_id or not self._author_id or len(self._cells) < 8:
            return
        try:
            rank = _integer(self._cells[0])
            published_at = datetime.strptime(self._cells[7], "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=_SHANGHAI
            )
            status = cast(
                RankingStatus,
                self._cells[4]
                if self._cells[4] in {"连载", "完结", "暂停", "锁定"}
                else "未知",
            )
            entry = JjwxcRankingEntry(
                rank=rank,
                author_id=self._author_id,
                novel_id=self._novel_id,
                author_display_name=self._cells[1],
                title=self._cells[2],
                novel_type=self._cells[3],
                status=status,
                word_count=_integer(self._cells[5]),
                points=_integer(self._cells[6]),
                published_at=published_at,
            )
        except (ValueError, TypeError):
            return
        self.entries.append(entry)


def parse_ranking_page(payload: bytes) -> tuple[JjwxcRankingEntry, ...]:
    """Parse only table metadata; tooltip synopsis attributes are never retained."""
    if len(payload) > _MAX_RANKING_BYTES:
        raise ValueError("ranking_body_too_large")
    text = payload.decode("gb18030", errors="strict")
    parser = _RankingParser()
    parser.feed(text)
    entries = tuple(parser.entries)
    if not entries or len(entries) > 200:
        raise ValueError("ranking_entry_count_invalid")
    if [item.rank for item in entries] != list(range(1, len(entries) + 1)):
        raise ValueError("ranking_order_invalid")
    if len({item.novel_id for item in entries}) != len(entries):
        raise ValueError("ranking_novel_duplicate")
    return entries


def collect_daily_ranking(
    session: Session,
    *,
    ranking_key: str,
    hydrate_top: int,
    request_interval_seconds: float,
    now: datetime | None = None,
) -> dict[str, object]:
    if os.getenv("JJYURI_ENABLE_NETWORK", "false").lower() != "true":
        raise RuntimeError("network_disabled")
    if ranking_key not in RANKING_URLS:
        raise ValueError("ranking_key_not_allowlisted")
    if not 0 <= hydrate_top <= 20:
        raise ValueError("hydrate_top_out_of_range")
    if request_interval_seconds < 1.0:
        raise ValueError("request_interval_too_short")

    observed_at = now or datetime.now(UTC)
    local_day = observed_at.astimezone(_SHANGHAI).date()
    canonical_observed_at = datetime.combine(
        local_day, datetime_time(hour=3, minute=30), tzinfo=_SHANGHAI
    ).astimezone(UTC)
    entries = _fetch_ranking(RANKING_URLS[ranking_key])
    created_rankings = _store_ranking_entries(
        session,
        ranking_key=ranking_key,
        observation_day=local_day,
        observed_at=canonical_observed_at,
        entries=entries,
    )
    hydrated = 0
    for entry in entries[:hydrate_top]:
        time.sleep(request_interval_seconds)
        envelope = probe_public_novel(
            entry.novel_id,
            observed_at=canonical_observed_at,
        )
        candidate = envelope["candidate"]
        result = store_novel_snapshot(session, JjwxcNovelCandidate.model_validate(candidate))
        hydrated += int(result.snapshot_created)
    session.commit()
    return {
        "status": "completed",
        "ranking_key": ranking_key,
        "observation_day": local_day.isoformat(),
        "ranking_count": len(entries),
        "created_ranking_rows": created_rankings,
        "hydrated_novel_snapshots": hydrated,
        "request_count": 1 + hydrate_top,
        "raw_payload_persisted": False,
    }


def _build_request_headers(*, accept: str, referer: str | None = None) -> dict[str, str]:
    headers: dict[str, str] = {
        "Accept": accept,
        "Accept-Encoding": "gzip, identity",
        "User-Agent": _USER_AGENT,
    }
    session_cookie = os.getenv("JJYURI_SESSION_COOKIE", "").strip()
    if session_cookie:
        headers["Cookie"] = session_cookie
    if referer:
        headers["Referer"] = referer
    return headers


def _fetch_ranking(url: str) -> tuple[JjwxcRankingEntry, ...]:
    request = urllib.request.Request(
        url,
        method="GET",
        headers=_build_request_headers(accept="text/html"),
    )
    with urllib.request.build_opener(_NoRedirect()).open(request, timeout=25) as response:
        if response.status != 200 or response.geturl() != url:
            raise RuntimeError("ranking_source_status_invalid")
        if response.headers.get_content_type().lower() != "text/html":
            raise RuntimeError("ranking_source_content_type_invalid")
        payload = response.read(_MAX_RANKING_BYTES + 1)
        encoding = response.headers.get("Content-Encoding", "identity").lower()
        if encoding == "gzip":
            with gzip.GzipFile(fileobj=io.BytesIO(payload), mode="rb") as archive:
                payload = archive.read(_MAX_RANKING_BYTES + 1)
        elif encoding not in {"", "identity"}:
            raise RuntimeError("ranking_source_content_encoding_invalid")
    return parse_ranking_page(payload)


def _store_ranking_entries(
    session: Session,
    *,
    ranking_key: str,
    observation_day: date,
    observed_at: datetime,
    entries: tuple[JjwxcRankingEntry, ...],
) -> int:
    existing_ids = set(
        session.scalars(
            select(JjwxcRankingSnapshot.novel_id).where(
                JjwxcRankingSnapshot.ranking_key == ranking_key,
                JjwxcRankingSnapshot.observation_day == observation_day,
            )
        )
    )
    created = 0
    for entry in entries:
        if entry.novel_id in existing_ids:
            continue
        session.add(
            JjwxcRankingSnapshot(
                ranking_key=ranking_key,
                observation_day=observation_day,
                observed_at=observed_at,
                rank=entry.rank,
                novel_id=entry.novel_id,
                author_id=entry.author_id,
                title=entry.title,
                author_display_name=entry.author_display_name,
                novel_type=entry.novel_type,
                status=entry.status,
                word_count=entry.word_count,
                points=entry.points,
                published_at=entry.published_at,
            )
        )
        created += 1
    return created


def _integer(value: str) -> int:
    cleaned = re.sub(r"[^0-9]", "", value)
    if not cleaned:
        raise ValueError("integer_missing")
    return int(cleaned)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect one allowlisted JJWXC ranking snapshot.")
    parser.add_argument("--ranking", choices=tuple(RANKING_URLS), default="yuri_current")
    parser.add_argument("--hydrate-top", type=int, default=10)
    parser.add_argument("--request-interval-seconds", type=float, default=2.0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.dry_run:
        print(
            json.dumps(
                {
                    "status": "dry_run",
                    "ranking_key": args.ranking,
                    "ranking_url": RANKING_URLS[args.ranking],
                    "planned_request_count": 1 + args.hydrate_top,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0
    database_url = os.getenv("PYURI_DATABASE_URL")
    if not database_url:
        raise RuntimeError("database_url_missing")
    session_factory = build_session_factory(build_engine(database_url))
    try:
        with session_factory() as session:
            result = collect_daily_ranking(
                session,
                ranking_key=args.ranking,
                hydrate_top=args.hydrate_top,
                request_interval_seconds=args.request_interval_seconds,
            )
    except (RuntimeError, ValueError, urllib.error.URLError, TimeoutError):
        print(json.dumps({"status": "blocked", "error": "daily_collection_failed"}))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
