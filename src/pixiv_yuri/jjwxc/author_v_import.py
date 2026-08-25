"""Import author-authorized VIP chapter click observations into immutable snapshots."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, cast

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pixiv_yuri.jjwxc.models import JjwxcNovel
from pixiv_yuri.jjwxc.persistence import (
    JjwxcAuthorRecord,
    JjwxcChapterSnapshot,
    JjwxcNovelRecord,
    JjwxcNovelSnapshot,
)
from pixiv_yuri.jjwxc.snapshot_store import store_novel_snapshot

MAX_AUTHOR_V_CLICK_RECORDS = 2_000
MAX_AUTHOR_V_CLICK_NOVELS = 20


@dataclass(frozen=True, slots=True)
class AuthorVClickRecord:
    novel_id: str
    chapter_id: int
    click_count: int


@dataclass(frozen=True, slots=True)
class AuthorVClickImportItem:
    novel_id: str
    status: Literal["imported", "duplicate", "rejected"]
    accepted_chapter_count: int
    error_code: str | None = None


def import_author_v_clicks(
    session: Session,
    *,
    records: tuple[AuthorVClickRecord, ...],
    observed_at: datetime,
    authorization_attested: bool,
    now: datetime | None = None,
) -> tuple[AuthorVClickImportItem, ...]:
    """Validate an author export and add one enriched snapshot per known novel."""
    if not authorization_attested:
        raise ValueError("author_v_click_authorization_required")
    if not records:
        raise ValueError("author_v_click_records_empty")
    if len(records) > MAX_AUTHOR_V_CLICK_RECORDS:
        raise ValueError("author_v_click_record_limit_exceeded")
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("author_v_click_observation_time_must_be_aware")
    reference = now or datetime.now(UTC)
    if reference.tzinfo is None or reference.utcoffset() is None:
        raise ValueError("author_v_click_reference_time_must_be_aware")
    if observed_at > reference + timedelta(minutes=5):
        raise ValueError("author_v_click_observation_time_in_future")
    if observed_at < reference - timedelta(days=30):
        raise ValueError("author_v_click_observation_time_too_old")
    grouped: dict[str, list[AuthorVClickRecord]] = defaultdict(list)
    seen: set[tuple[str, int]] = set()
    for item in records:
        if not item.novel_id.isdigit() or item.novel_id.startswith("0"):
            raise ValueError("author_v_click_novel_id_invalid")
        if not 1 <= item.chapter_id <= 1_000_000 or not 0 <= item.click_count <= 10**12:
            raise ValueError("author_v_click_value_invalid")
        key = (item.novel_id, item.chapter_id)
        if key in seen:
            raise ValueError("author_v_click_duplicate_chapter")
        seen.add(key)
        grouped[item.novel_id].append(item)
    if len(grouped) > MAX_AUTHOR_V_CLICK_NOVELS:
        raise ValueError("author_v_click_novel_limit_exceeded")

    results: list[AuthorVClickImportItem] = []
    for novel_id, novel_records in grouped.items():
        result = _import_one_novel(
            session,
            novel_id=novel_id,
            records=novel_records,
            observed_at=observed_at,
        )
        results.append(result)
    session.commit()
    return tuple(results)


def _import_one_novel(
    session: Session,
    *,
    novel_id: str,
    records: list[AuthorVClickRecord],
    observed_at: datetime,
) -> AuthorVClickImportItem:
    novel_record = session.scalar(
        select(JjwxcNovelRecord).where(JjwxcNovelRecord.novel_id == novel_id)
    )
    if novel_record is None:
        return AuthorVClickImportItem(novel_id, "rejected", 0, "novel_not_collected")
    latest_snapshot = session.scalar(
        select(JjwxcNovelSnapshot)
        .where(JjwxcNovelSnapshot.novel_record_id == novel_record.id)
        .order_by(JjwxcNovelSnapshot.observed_at.desc())
        .limit(1)
    )
    author = session.get(JjwxcAuthorRecord, novel_record.author_record_id)
    if latest_snapshot is None or author is None:
        return AuthorVClickImportItem(novel_id, "rejected", 0, "novel_snapshot_missing")

    latest_chapter_time = session.scalar(
        select(func.max(JjwxcChapterSnapshot.observed_at)).where(
            JjwxcChapterSnapshot.novel_record_id == novel_record.id
        )
    )
    if latest_chapter_time is None:
        return AuthorVClickImportItem(novel_id, "rejected", 0, "chapter_snapshot_missing")
    latest_chapters = {
        chapter.chapter_id: chapter
        for chapter in session.scalars(
            select(JjwxcChapterSnapshot).where(
                JjwxcChapterSnapshot.novel_record_id == novel_record.id,
                JjwxcChapterSnapshot.observed_at == latest_chapter_time,
            )
        ).all()
    }
    supplied = {item.chapter_id: item.click_count for item in records}
    if any(
        chapter_id not in latest_chapters or not latest_chapters[chapter_id].is_vip
        for chapter_id in supplied
    ):
        return AuthorVClickImportItem(novel_id, "rejected", 0, "vip_chapter_mismatch")

    expected_vip_ids = {item.chapter_id for item in latest_chapters.values() if item.is_vip}
    if supplied.keys() != expected_vip_ids:
        return AuthorVClickImportItem(novel_id, "rejected", 0, "vip_chapter_set_incomplete")
    v_average = sum(supplied.values()) // len(supplied)
    non_v_coverage = sum(
        item.click_count is not None for item in latest_chapters.values() if not item.is_vip
    )
    enriched = JjwxcNovel(
        novel_id=novel_record.novel_id,
        title=novel_record.title,
        author_id=author.author_id,
        author_display_name=author.display_name,
        novel_type=novel_record.novel_type,
        perspective=novel_record.perspective,
        status=cast(
            Literal["连载", "完结", "暂停", "锁定", "未知"], novel_record.status
        ),
        word_count=latest_snapshot.word_count,
        review_count=latest_snapshot.review_count,
        favorite_count=latest_snapshot.favorite_count,
        nutrition_count=latest_snapshot.nutrition_count,
        recommendation_count=latest_snapshot.recommendation_count,
        bomb_ticket_count=latest_snapshot.bomb_ticket_count,
        points=latest_snapshot.points,
        first_chapter_click_count=latest_snapshot.first_chapter_click_count,
        average_non_v_chapter_click_count=(
            latest_snapshot.average_non_v_chapter_click_count
        ),
        average_v_chapter_click_count=v_average,
        non_v_chapter_count=latest_snapshot.non_v_chapter_count,
        v_chapter_count=len(expected_vip_ids),
        chapter_click_coverage_count=non_v_coverage + len(supplied),
        synopsis_char_count=latest_snapshot.synopsis_char_count,
        synopsis_sentence_count=latest_snapshot.synopsis_sentence_count,
        synopsis_theme_terms=tuple(latest_snapshot.synopsis_theme_terms),
        tags=tuple(novel_record.tags),
        observed_at=observed_at,
        source_mode="public_candidate",
    )
    write = store_novel_snapshot(session, enriched)
    if not write.snapshot_created:
        return AuthorVClickImportItem(novel_id, "duplicate", len(supplied))
    for chapter in latest_chapters.values():
        session.add(
            JjwxcChapterSnapshot(
                novel_record_id=novel_record.id,
                observed_at=observed_at,
                chapter_id=chapter.chapter_id,
                position=chapter.position,
                is_vip=chapter.is_vip,
                word_count=chapter.word_count,
                click_count=(
                    supplied[chapter.chapter_id]
                    if chapter.is_vip
                    else chapter.click_count
                ),
            )
        )
    return AuthorVClickImportItem(novel_id, "imported", len(supplied))
