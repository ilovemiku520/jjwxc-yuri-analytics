"""Resumable yuri-channel discovery and bounded novel/chapter hydration."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
from datetime import UTC, datetime, timedelta
from datetime import time as datetime_time
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from pixiv_yuri.jjwxc.catalog_parser import (
    CHANNEL_RANKING_KEYS,
    JjwxcChannelCatalog,
    enrich_candidate_with_chapters,
    parse_channel_catalog,
    parse_chapter_directory,
)
from pixiv_yuri.jjwxc.html_parser import parse_novel_page
from pixiv_yuri.jjwxc.persistence import (
    JjwxcChannelRankingSnapshot,
    JjwxcChapterSnapshot,
    JjwxcDiscoveryRecord,
)
from pixiv_yuri.jjwxc.snapshot_store import store_novel_snapshot
from pixiv_yuri.jjwxc.source_cache import JjwxcSourceCache
from pixiv_yuri.shared.database import build_engine, build_session_factory

CHANNEL_URL = "https://www.jjwxc.net/channel/bh.php"
_NOVEL_URL = "https://www.jjwxc.net/onebook.php?novelid={novel_id}"
_CLICK_URL = (
    "https://s8-static.jjwxc.net/getnovelclick.php?novelid={novel_id}"
    "&jsonpcallback=novelclick"
)
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_PRIORITIES = {"channel_gold": 100, "newcomer": 90, "channel_catalog": 50}


def collect_channel_catalog(
    session: Session,
    *,
    hydrate_limit: int,
    request_interval_seconds: float,
    cache_dir: Path,
    cache_ttl_seconds: int = 24 * 60 * 60,
    now: datetime | None = None,
) -> dict[str, object]:
    if os.getenv("JJYURI_ENABLE_NETWORK", "false").lower() != "true":
        raise RuntimeError("network_disabled")
    if not 0 <= hydrate_limit <= 500:
        raise ValueError("hydrate_limit_out_of_range")
    if request_interval_seconds < 1.0:
        raise ValueError("request_interval_too_short")
    observed_at = now or datetime.now(UTC)
    if observed_at.tzinfo is None:
        raise ValueError("observation_time_must_be_aware")
    local_day = observed_at.astimezone(_SHANGHAI).date()
    canonical_observed_at = datetime.combine(
        local_day, datetime_time(hour=3, minute=30), tzinfo=_SHANGHAI
    ).astimezone(UTC)
    cache = JjwxcSourceCache(cache_dir, ttl_seconds=cache_ttl_seconds)
    network_requests = 0
    cache_hits = 0

    channel_fetch = cache.fetch(
        CHANNEL_URL,
        allowed_hosts=frozenset({"www.jjwxc.net"}),
        expected_content_types=("text/html",),
        max_bytes=1_500_000,
    )
    network_requests += int(not channel_fetch.cache_hit)
    cache_hits += int(channel_fetch.cache_hit)
    catalog = parse_channel_catalog(channel_fetch.payload)
    created_rankings = _store_channel_rankings(
        session,
        catalog=catalog,
        observed_at=canonical_observed_at,
    )
    discovered = _upsert_discovery_queue(session, catalog=catalog, observed_at=observed_at)
    session.commit()

    hydrated = 0
    failed = 0
    chapters_created = 0
    candidates = list(
        session.scalars(
            select(JjwxcDiscoveryRecord)
            .where(JjwxcDiscoveryRecord.next_fetch_at <= observed_at)
            .order_by(JjwxcDiscoveryRecord.priority.desc(), JjwxcDiscoveryRecord.id)
            .limit(hydrate_limit)
        ).all()
    )
    for record in candidates:
        record.status = "running"
        record.attempt_count += 1
        session.commit()
        novel_url = _NOVEL_URL.format(novel_id=record.novel_id)
        try:
            time.sleep(request_interval_seconds)
            page_fetch = cache.fetch(
                novel_url,
                allowed_hosts=frozenset({"www.jjwxc.net"}),
                expected_content_types=("text/html",),
                max_bytes=1_500_000,
            )
            network_requests += int(not page_fetch.cache_hit)
            cache_hits += int(page_fetch.cache_hit)
            click_payload: bytes | None = None
            try:
                time.sleep(request_interval_seconds)
                click_fetch = cache.fetch(
                    _CLICK_URL.format(novel_id=record.novel_id),
                    allowed_hosts=frozenset({"s8-static.jjwxc.net"}),
                    expected_content_types=(
                        "application/javascript",
                        "text/javascript",
                        "text/plain",
                        "text/html",
                    ),
                    max_bytes=500_000,
                    referer=novel_url,
                )
                click_payload = click_fetch.payload
                network_requests += int(not click_fetch.cache_hit)
                cache_hits += int(click_fetch.cache_hit)
            except (RuntimeError, ValueError, urllib.error.URLError, TimeoutError):
                click_payload = None
            chapters = parse_chapter_directory(
                page_fetch.payload,
                click_payload=click_payload,
            )
            candidate = parse_novel_page(
                page_fetch.payload,
                novel_id=record.novel_id,
                observed_at=canonical_observed_at,
            )
            candidate = enrich_candidate_with_chapters(candidate, chapters)
            write = store_novel_snapshot(session, candidate)
            if write.snapshot_created:
                for chapter in chapters:
                    session.add(
                        JjwxcChapterSnapshot(
                            novel_record_id=write.novel_record_id,
                            observed_at=canonical_observed_at,
                            chapter_id=chapter.chapter_id,
                            position=chapter.position,
                            is_vip=chapter.is_vip,
                            word_count=chapter.word_count,
                            click_count=chapter.click_count,
                        )
                    )
                chapters_created += len(chapters)
            record.status = "completed"
            record.last_fetched_at = observed_at
            record.next_fetch_at = observed_at + timedelta(days=1)
            record.last_error_code = None
            hydrated += int(write.snapshot_created)
            session.commit()
        except (RuntimeError, ValueError, urllib.error.URLError, TimeoutError) as exc:
            session.rollback()
            failed += 1
            retry = session.get(JjwxcDiscoveryRecord, record.id)
            if retry is not None:
                retry.status = "failed"
                retry.next_fetch_at = observed_at + timedelta(hours=6)
                retry.last_error_code = _error_code(exc)
                session.commit()

    pending = session.scalar(
        select(JjwxcDiscoveryRecord.id)
        .where(JjwxcDiscoveryRecord.next_fetch_at <= observed_at)
        .limit(1)
    )
    return {
        "status": "completed_with_errors" if failed else "completed",
        "observation_day": local_day.isoformat(),
        "channel_gold_count": len(catalog.rankings["channel_gold"]),
        "newcomer_count": len(catalog.rankings["newcomer"]),
        "channel_discovered_count": len(catalog.discovered_novel_ids),
        "new_discovery_records": discovered,
        "created_ranking_rows": created_rankings,
        "hydrated_novel_snapshots": hydrated,
        "created_chapter_rows": chapters_created,
        "failed_novels": failed,
        "cache_hits": cache_hits,
        "network_request_count": network_requests,
        "backfill_remaining": pending is not None,
        "raw_payload_location": "private_ttl_cache",
    }


def _store_channel_rankings(
    session: Session,
    *,
    catalog: JjwxcChannelCatalog,
    observed_at: datetime,
) -> int:
    local_day = observed_at.astimezone(_SHANGHAI).date()
    created = 0
    for ranking_key in CHANNEL_RANKING_KEYS:
        existing = set(
            session.scalars(
                select(JjwxcChannelRankingSnapshot.novel_id).where(
                    JjwxcChannelRankingSnapshot.ranking_key == ranking_key,
                    JjwxcChannelRankingSnapshot.observation_day == local_day,
                )
            ).all()
        )
        for entry in catalog.rankings[ranking_key]:
            if entry.novel_id in existing:
                continue
            session.add(
                JjwxcChannelRankingSnapshot(
                    ranking_key=ranking_key,
                    observation_day=local_day,
                    observed_at=observed_at,
                    rank=entry.rank,
                    novel_id=entry.novel_id,
                    title=entry.title,
                    source_rank_id=entry.source_rank_id,
                )
            )
            created += 1
    return created


def _upsert_discovery_queue(
    session: Session,
    *,
    catalog: JjwxcChannelCatalog,
    observed_at: datetime,
) -> int:
    sources: dict[str, tuple[str, int]] = {
        novel_id: ("channel_catalog", _PRIORITIES["channel_catalog"])
        for novel_id in catalog.discovered_novel_ids
    }
    for ranking_key in CHANNEL_RANKING_KEYS:
        for entry in catalog.rankings[ranking_key]:
            current = sources.get(entry.novel_id)
            if current is None or _PRIORITIES[ranking_key] > current[1]:
                sources[entry.novel_id] = (ranking_key, _PRIORITIES[ranking_key])
    existing = {
        item.novel_id: item
        for item in session.scalars(
            select(JjwxcDiscoveryRecord).where(JjwxcDiscoveryRecord.novel_id.in_(sources))
        ).all()
    }
    created = 0
    for novel_id, (source_kind, priority) in sources.items():
        record = existing.get(novel_id)
        if record is None:
            session.add(
                JjwxcDiscoveryRecord(
                    novel_id=novel_id,
                    source_kind=source_kind,
                    priority=priority,
                    status="pending",
                    discovered_at=observed_at,
                    next_fetch_at=observed_at,
                    attempt_count=0,
                )
            )
            created += 1
        elif priority > record.priority:
            record.priority = priority
            record.source_kind = source_kind
    return created


def _error_code(error: Exception) -> str:
    value = str(error).strip().lower()
    cleaned = "".join(
        character if character.isalnum() or character == "_" else "_"
        for character in value
    )
    return (cleaned.strip("_") or error.__class__.__name__.lower())[:80]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Discover both JJWXC yuri channel lists and hydrate a resumable batch."
    )
    parser.add_argument("--hydrate-limit", type=int, default=25)
    parser.add_argument("--request-interval-seconds", type=float, default=2.0)
    parser.add_argument("--cache-ttl-hours", type=int, default=24)
    parser.add_argument("--cache-dir", default=os.getenv("JJYURI_CACHE_DIR", "var/cache/jjwxc"))
    parser.add_argument("--discover-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    hydrate_limit = 0 if args.discover_only else args.hydrate_limit
    if args.dry_run:
        print(
            json.dumps(
                {
                    "status": "dry_run",
                    "channel_url": CHANNEL_URL,
                    "hydrate_limit": hydrate_limit,
                    "maximum_planned_requests": 1 + hydrate_limit * 2,
                    "ranking_keys": CHANNEL_RANKING_KEYS,
                    "cache_dir": args.cache_dir,
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
            result = collect_channel_catalog(
                session,
                hydrate_limit=hydrate_limit,
                request_interval_seconds=args.request_interval_seconds,
                cache_dir=Path(args.cache_dir),
                cache_ttl_seconds=args.cache_ttl_hours * 60 * 60,
            )
    except (RuntimeError, ValueError, urllib.error.URLError, TimeoutError):
        print(json.dumps({"status": "blocked", "error": "catalog_collection_failed"}))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
