"""Resumable yuri-channel discovery and bounded novel/chapter hydration."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
from datetime import UTC, datetime, timedelta
from datetime import time as datetime_time
from pathlib import Path
from typing import TypedDict
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from pixiv_yuri.ingest.models import DiscoveryCheckpoint
from pixiv_yuri.jjwxc.catalog_parser import (
    CHANNEL_RANKING_KEYS,
    JjwxcBookbasePage,
    JjwxcChannelCatalog,
    enrich_candidate_with_aggregate,
    enrich_candidate_with_chapters,
    parse_author_profile,
    parse_bookbase_page,
    parse_channel_catalog,
    parse_chapter_directory,
    parse_novel_aggregate_payload,
)
from pixiv_yuri.jjwxc.html_parser import parse_novel_page
from pixiv_yuri.jjwxc.persistence import (
    JjwxcAuthorRecord,
    JjwxcAuthorSnapshot,
    JjwxcCatalogIndexRecord,
    JjwxcChannelRankingSnapshot,
    JjwxcChapterSnapshot,
    JjwxcDiscoveryRecord,
    JjwxcNovelRecord,
    JjwxcNovelSnapshot,
)
from pixiv_yuri.jjwxc.snapshot_store import store_novel_snapshot
from pixiv_yuri.jjwxc.source_cache import JjwxcSourceCache
from pixiv_yuri.shared.database import build_engine, build_session_factory

CHANNEL_URL = "https://www.jjwxc.net/channel/bh.php"
_BOOKBASE_URL = "https://www.jjwxc.net/bookbase.php"
_NOVEL_URL = "https://www.jjwxc.net/onebook.php?novelid={novel_id}"
_CLICK_URL = (
    "https://s8-static.jjwxc.net/getnovelclick.php?novelid={novel_id}&jsonpcallback=novelclick"
)
_AGGREGATE_URL = (
    "https://my.jjwxc.net/lib/ajax.php?action=getNovelCollectedCount"
    "&novelid={novel_id}&callback=jjyuriAggregate"
)
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_PRIORITIES = {
    "uploaded_cohort": 120,
    "channel_gold": 100,
    "newcomer": 90,
    "channel_catalog": 50,
    "bookbase_catalog": 20,
}


class HydrationResult(TypedDict):
    requested_count: int
    hydrated_novel_snapshots: int
    created_chapter_rows: int
    failed_novels: int
    cache_hits: int
    network_request_count: int
    items: list[dict[str, str | None]]


def collect_channel_catalog(
    session: Session,
    *,
    hydrate_limit: int,
    index_page_limit: int,
    author_limit: int,
    request_interval_seconds: float,
    cache_dir: Path,
    cache_ttl_seconds: int = 24 * 60 * 60,
    now: datetime | None = None,
) -> dict[str, object]:
    if os.getenv("JJYURI_ENABLE_NETWORK", "false").lower() != "true":
        raise RuntimeError("network_disabled")
    if not 0 <= hydrate_limit <= 500:
        raise ValueError("hydrate_limit_out_of_range")
    if not 0 <= index_page_limit <= 50:
        raise ValueError("index_page_limit_out_of_range")
    if not 0 <= author_limit <= 100:
        raise ValueError("author_limit_out_of_range")
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

    (
        bookbase_network_requests,
        bookbase_cache_hits,
        bookbase_pages_scanned,
        bookbase_entries_seen,
        bookbase_entries_created,
        bookbase_total_pages,
        bookbase_failed_pages,
    ) = _scan_bookbase_pages(
        session,
        cache=cache,
        page_limit=index_page_limit,
        request_interval_seconds=request_interval_seconds,
        observed_at=observed_at,
    )
    network_requests += bookbase_network_requests
    cache_hits += bookbase_cache_hits

    hydration = _hydrate_discovery_queue(
        session,
        cache=cache,
        limit=hydrate_limit,
        request_interval_seconds=request_interval_seconds,
        observed_at=observed_at,
        canonical_observed_at=canonical_observed_at,
    )
    hydrated = hydration["hydrated_novel_snapshots"]
    failed = hydration["failed_novels"]
    chapters_created = hydration["created_chapter_rows"]
    network_requests += hydration["network_request_count"]
    cache_hits += hydration["cache_hits"]

    pending = session.scalar(
        select(JjwxcDiscoveryRecord.id)
        .where(JjwxcDiscoveryRecord.next_fetch_at <= observed_at)
        .limit(1)
    )
    (
        author_profiles_created,
        author_profiles_failed,
        author_network_requests,
        author_cache_hits,
    ) = _collect_author_profiles(
        session,
        cache=cache,
        author_limit=author_limit,
        request_interval_seconds=request_interval_seconds,
        observed_at=canonical_observed_at,
    )
    network_requests += author_network_requests
    cache_hits += author_cache_hits
    return {
        "status": "completed_with_errors" if failed else "completed",
        "observation_day": local_day.isoformat(),
        "channel_gold_count": len(catalog.rankings["channel_gold"]),
        "newcomer_count": len(catalog.rankings["newcomer"]),
        "channel_discovered_count": len(catalog.discovered_novel_ids),
        "new_discovery_records": discovered,
        "bookbase_pages_scanned": bookbase_pages_scanned,
        "bookbase_entries_seen": bookbase_entries_seen,
        "bookbase_entries_created": bookbase_entries_created,
        "bookbase_total_pages": bookbase_total_pages,
        "bookbase_failed_pages": bookbase_failed_pages,
        "created_ranking_rows": created_rankings,
        "hydrated_novel_snapshots": hydrated,
        "created_chapter_rows": chapters_created,
        "failed_novels": failed,
        "author_profiles_created": author_profiles_created,
        "author_profiles_failed": author_profiles_failed,
        "cache_hits": cache_hits,
        "network_request_count": network_requests,
        "backfill_remaining": pending is not None,
        "raw_payload_location": "private_ttl_cache",
    }


def collect_targeted_cohort_queue(
    session: Session,
    *,
    limit: int,
    request_interval_seconds: float,
    cache_dir: Path,
    cache_ttl_seconds: int = 24 * 60 * 60,
    now: datetime | None = None,
) -> dict[str, object]:
    """Hydrate only high-priority IDs supplied through the cohort import interface."""
    if os.getenv("JJYURI_ENABLE_NETWORK", "false").lower() != "true":
        raise RuntimeError("network_disabled")
    if not 1 <= limit <= 100:
        raise ValueError("targeted_limit_out_of_range")
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
    hydration = _hydrate_discovery_queue(
        session,
        cache=cache,
        limit=limit,
        request_interval_seconds=request_interval_seconds,
        observed_at=observed_at,
        canonical_observed_at=canonical_observed_at,
        source_kind="uploaded_cohort",
    )
    return {
        "status": "completed_with_errors" if hydration["failed_novels"] else "completed",
        "observation_day": local_day.isoformat(),
        **hydration,
        "raw_payload_location": "private_ttl_cache",
    }


def _hydrate_discovery_queue(
    session: Session,
    *,
    cache: JjwxcSourceCache,
    limit: int,
    request_interval_seconds: float,
    observed_at: datetime,
    canonical_observed_at: datetime,
    source_kind: str | None = None,
) -> HydrationResult:
    statement = select(JjwxcDiscoveryRecord).where(
        JjwxcDiscoveryRecord.next_fetch_at <= observed_at,
        JjwxcDiscoveryRecord.status != "running",
    )
    if source_kind is not None:
        statement = statement.where(JjwxcDiscoveryRecord.source_kind == source_kind)
    candidates = list(
        session.scalars(
            statement.order_by(JjwxcDiscoveryRecord.priority.desc(), JjwxcDiscoveryRecord.id).limit(
                limit
            )
        ).all()
    )
    hydrated = 0
    failed = 0
    chapters_created = 0
    network_requests = 0
    cache_hits = 0
    results: list[dict[str, str | None]] = []
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
            time.sleep(request_interval_seconds)
            aggregate_fetch = cache.fetch(
                _AGGREGATE_URL.format(novel_id=record.novel_id),
                allowed_hosts=frozenset({"my.jjwxc.net"}),
                expected_content_types=(
                    "application/javascript",
                    "text/javascript",
                    "text/plain",
                    "text/html",
                ),
                max_bytes=100_000,
                referer=novel_url,
            )
            aggregate = parse_novel_aggregate_payload(aggregate_fetch.payload)
            network_requests += int(not aggregate_fetch.cache_hit)
            cache_hits += int(aggregate_fetch.cache_hit)
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
            chapters = parse_chapter_directory(page_fetch.payload, click_payload=click_payload)
            candidate = parse_novel_page(
                page_fetch.payload,
                novel_id=record.novel_id,
                observed_at=canonical_observed_at,
            )
            if record.source_kind == "uploaded_cohort" and "百合" not in candidate.novel_type:
                raise ValueError("novel_outside_yuri_scope")
            candidate = enrich_candidate_with_aggregate(candidate, aggregate)
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
            results.append({"novel_id": record.novel_id, "status": "ready", "error_code": None})
            session.commit()
        except (RuntimeError, ValueError, urllib.error.URLError, TimeoutError) as exc:
            session.rollback()
            failed += 1
            error_code = _error_code(exc)
            retry = session.get(JjwxcDiscoveryRecord, record.id)
            if retry is not None:
                retry.status = "failed"
                retry.next_fetch_at = observed_at + timedelta(hours=6)
                retry.last_error_code = error_code
                session.commit()
            results.append(
                {"novel_id": record.novel_id, "status": "failed", "error_code": error_code}
            )
    return {
        "requested_count": len(candidates),
        "hydrated_novel_snapshots": hydrated,
        "created_chapter_rows": chapters_created,
        "failed_novels": failed,
        "cache_hits": cache_hits,
        "network_request_count": network_requests,
        "items": results,
    }


def _collect_author_profiles(
    session: Session,
    *,
    cache: JjwxcSourceCache,
    author_limit: int,
    request_interval_seconds: float,
    observed_at: datetime,
) -> tuple[int, int, int, int]:
    if author_limit == 0:
        return (0, 0, 0, 0)
    latest = (
        select(
            JjwxcAuthorSnapshot.author_record_id.label("author_record_id"),
            func.max(JjwxcAuthorSnapshot.observed_at).label("observed_at"),
        )
        .group_by(JjwxcAuthorSnapshot.author_record_id)
        .subquery()
    )
    public_author_ids = (
        select(JjwxcNovelRecord.author_record_id)
        .join(
            JjwxcNovelSnapshot,
            JjwxcNovelSnapshot.novel_record_id == JjwxcNovelRecord.id,
        )
        .where(JjwxcNovelSnapshot.source_mode == "public_candidate")
        .distinct()
    )
    authors = list(
        session.scalars(
            select(JjwxcAuthorRecord)
            .outerjoin(latest, latest.c.author_record_id == JjwxcAuthorRecord.id)
            .where(
                JjwxcAuthorRecord.id.in_(public_author_ids),
                or_(latest.c.observed_at.is_(None), latest.c.observed_at < observed_at),
            )
            .order_by(latest.c.observed_at.asc().nullsfirst(), JjwxcAuthorRecord.id)
            .limit(author_limit)
        ).all()
    )
    created = 0
    failed = 0
    network_requests = 0
    cache_hits = 0
    for author in authors:
        url = f"https://www.jjwxc.net/oneauthor.php?authorid={author.author_id}"
        try:
            time.sleep(request_interval_seconds)
            fetched = cache.fetch(
                url,
                allowed_hosts=frozenset({"www.jjwxc.net"}),
                expected_content_types=("text/html",),
                max_bytes=2_000_000,
            )
            network_requests += int(not fetched.cache_hit)
            cache_hits += int(fetched.cache_hit)
            candidate = parse_author_profile(
                fetched.payload,
                author_id=author.author_id,
                observed_at=observed_at,
            )
            digest = hashlib.sha256(candidate.model_dump_json().encode()).hexdigest()
            existing = session.scalar(
                select(JjwxcAuthorSnapshot.id).where(
                    or_(
                        JjwxcAuthorSnapshot.candidate_sha256 == digest,
                        (JjwxcAuthorSnapshot.author_record_id == author.id)
                        & (JjwxcAuthorSnapshot.observed_at == observed_at),
                    )
                )
            )
            if existing is None:
                session.add(
                    JjwxcAuthorSnapshot(
                        author_record_id=author.id,
                        observed_at=observed_at,
                        author_favorite_count=candidate.author_favorite_count,
                        nonlocked_work_count=candidate.nonlocked_work_count,
                        locked_work_count=candidate.locked_work_count,
                        total_word_count=candidate.total_word_count,
                        total_points=candidate.total_points,
                        candidate_sha256=digest,
                    )
                )
                created += 1
            session.commit()
        except (RuntimeError, ValueError, urllib.error.URLError, TimeoutError):
            session.rollback()
            failed += 1
    return created, failed, network_requests, cache_hits


def _scan_bookbase_pages(
    session: Session,
    *,
    cache: JjwxcSourceCache,
    page_limit: int,
    request_interval_seconds: float,
    observed_at: datetime,
) -> tuple[int, int, int, int, int, int | None, int]:
    if page_limit == 0:
        return (0, 0, 0, 0, 0, None, 0)
    checkpoint = session.scalar(
        select(DiscoveryCheckpoint).where(
            DiscoveryCheckpoint.provider == "jjwxc",
            DiscoveryCheckpoint.discovery_scope == "bookbase_yuri_all",
            DiscoveryCheckpoint.seed_version == "v1",
        )
    )
    if checkpoint is None:
        checkpoint = DiscoveryCheckpoint(
            provider="jjwxc",
            discovery_scope="bookbase_yuri_all",
            seed_version="v1",
            cursor={"next_page": 1, "completed_sweeps": 0},
            updated_at=observed_at,
        )
        session.add(checkpoint)
        session.flush()
    raw_next_page = checkpoint.cursor.get("next_page", 1)
    next_page = raw_next_page if isinstance(raw_next_page, int) and raw_next_page >= 1 else 1
    network_requests = 0
    cache_hits = 0
    pages_scanned = 0
    entries_seen = 0
    entries_created = 0
    failed_pages = 0
    total_pages: int | None = None
    completed_sweeps = int(checkpoint.cursor.get("completed_sweeps", 0) or 0)
    for _ in range(page_limit):
        query = urlencode(
            {
                "xx": 3,
                "sortType": 1,
                "isfinish": 0,
                "collectiontypes": "",
                "searchkeywords": "",
                "m_p": next_page,
                "page": next_page,
            }
        )
        url = f"{_BOOKBASE_URL}?{query}"
        try:
            time.sleep(request_interval_seconds)
            fetched = cache.fetch(
                url,
                allowed_hosts=frozenset({"www.jjwxc.net"}),
                expected_content_types=("text/html",),
                max_bytes=500_000,
            )
            network_requests += int(not fetched.cache_hit)
            cache_hits += int(fetched.cache_hit)
            page = parse_bookbase_page(fetched.payload)
            if page.current_page != next_page:
                raise ValueError("bookbase_page_cursor_mismatch")
            created = _upsert_bookbase_page(
                session,
                page=page,
                source_page=next_page,
                observed_at=observed_at,
            )
            entries_seen += len(page.entries)
            entries_created += created
            pages_scanned += 1
            total_pages = page.total_pages
            if next_page >= page.total_pages:
                next_page = 1
                completed_sweeps += 1
            else:
                next_page += 1
            checkpoint.cursor = {
                "next_page": next_page,
                "total_pages": total_pages,
                "completed_sweeps": completed_sweeps,
            }
            checkpoint.last_success_at = observed_at
            checkpoint.updated_at = observed_at
            session.commit()
        except (RuntimeError, ValueError, urllib.error.URLError, TimeoutError):
            session.rollback()
            failed_pages += 1
            break
    return (
        network_requests,
        cache_hits,
        pages_scanned,
        entries_seen,
        entries_created,
        total_pages,
        failed_pages,
    )


def _upsert_bookbase_page(
    session: Session,
    *,
    page: JjwxcBookbasePage,
    source_page: int,
    observed_at: datetime,
) -> int:
    novel_ids = [entry.novel_id for entry in page.entries]
    existing_index = {
        item.novel_id: item
        for item in session.scalars(
            select(JjwxcCatalogIndexRecord).where(JjwxcCatalogIndexRecord.novel_id.in_(novel_ids))
        ).all()
    }
    existing_queue = {
        item.novel_id: item
        for item in session.scalars(
            select(JjwxcDiscoveryRecord).where(JjwxcDiscoveryRecord.novel_id.in_(novel_ids))
        ).all()
    }
    created = 0
    for entry in page.entries:
        record = existing_index.get(entry.novel_id)
        values = {
            "title": entry.title,
            "author_id": entry.author_id,
            "author_display_name": entry.author_display_name,
            "novel_type": entry.novel_type,
            "status": entry.status,
            "word_count": entry.word_count,
            "points": entry.points,
            "published_at": entry.published_at,
            "source_page": source_page,
            "last_seen_at": observed_at,
        }
        if record is None:
            session.add(
                JjwxcCatalogIndexRecord(
                    novel_id=entry.novel_id,
                    first_seen_at=observed_at,
                    **values,
                )
            )
            created += 1
        else:
            for field, value in values.items():
                setattr(record, field, value)
        queued = existing_queue.get(entry.novel_id)
        if queued is None:
            session.add(
                JjwxcDiscoveryRecord(
                    novel_id=entry.novel_id,
                    source_kind="bookbase_catalog",
                    priority=_PRIORITIES["bookbase_catalog"],
                    status="pending",
                    discovered_at=observed_at,
                    next_fetch_at=observed_at,
                    attempt_count=0,
                )
            )
    return created


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
        character if character.isalnum() or character == "_" else "_" for character in value
    )
    return (cleaned.strip("_") or error.__class__.__name__.lower())[:80]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Discover JJWXC yuri channel lists, scan a resumable bookbase slice, "
            "and hydrate a bounded detail batch."
        )
    )
    parser.add_argument("--hydrate-limit", type=int, default=25)
    parser.add_argument("--index-pages", type=int, default=10)
    parser.add_argument("--author-limit", type=int, default=100)
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
                    "index_pages": args.index_pages,
                    "author_limit": args.author_limit,
                    "maximum_planned_requests": (
                        1 + args.index_pages + hydrate_limit * 3 + args.author_limit
                    ),
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
                index_page_limit=args.index_pages,
                author_limit=args.author_limit,
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
