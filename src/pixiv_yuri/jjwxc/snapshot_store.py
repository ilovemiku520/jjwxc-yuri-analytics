"""Transactional idempotent storage for minimized JJWXC novel snapshots."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from pixiv_yuri.jjwxc.models import JjwxcNovel
from pixiv_yuri.jjwxc.persistence import (
    JjwxcAuthorRecord,
    JjwxcNovelRecord,
    JjwxcNovelSnapshot,
)


class JjwxcSnapshotConflictError(ValueError):
    """Raised when one observation time or digest is already bound elsewhere."""


@dataclass(frozen=True, slots=True)
class JjwxcSnapshotWriteResult:
    author_record_id: int
    novel_record_id: int
    snapshot_id: int
    snapshot_created: bool
    current_projection_updated: bool


def store_novel_snapshot(session: Session, novel: JjwxcNovel) -> JjwxcSnapshotWriteResult:
    """Store one minimized snapshot; the caller owns commit and rollback."""
    digest = hashlib.sha256(novel.model_dump_json().encode()).hexdigest()
    existing_digest = session.scalar(
        select(JjwxcNovelSnapshot).where(JjwxcNovelSnapshot.candidate_sha256 == digest)
    )
    if existing_digest is not None:
        record = session.get(JjwxcNovelRecord, existing_digest.novel_record_id)
        if record is None or record.novel_id != novel.novel_id:
            raise JjwxcSnapshotConflictError("candidate digest is bound to another novel")
        author = session.get(JjwxcAuthorRecord, record.author_record_id)
        if author is None:
            raise JjwxcSnapshotConflictError("snapshot references a missing author")
        return JjwxcSnapshotWriteResult(
            author_record_id=author.id,
            novel_record_id=record.id,
            snapshot_id=existing_digest.id,
            snapshot_created=False,
            current_projection_updated=False,
        )

    author = _upsert_author(session, novel)
    record = _upsert_novel(session, novel, author)
    existing_time = session.scalar(
        select(JjwxcNovelSnapshot).where(
            JjwxcNovelSnapshot.novel_record_id == record.id,
            JjwxcNovelSnapshot.observed_at == novel.observed_at,
        )
    )
    if existing_time is not None:
        raise JjwxcSnapshotConflictError("novel observation time has different minimized values")

    snapshot = JjwxcNovelSnapshot(
        novel_record_id=record.id,
        observed_at=novel.observed_at,
        word_count=novel.word_count,
        review_count=novel.review_count,
        favorite_count=novel.favorite_count,
        points=novel.points,
        average_non_v_chapter_click_count=novel.average_non_v_chapter_click_count,
        average_v_chapter_click_count=novel.average_v_chapter_click_count,
        non_v_chapter_count=novel.non_v_chapter_count,
        v_chapter_count=novel.v_chapter_count,
        chapter_click_coverage_count=novel.chapter_click_coverage_count,
        synopsis_char_count=novel.synopsis_char_count,
        synopsis_sentence_count=novel.synopsis_sentence_count,
        synopsis_theme_terms=list(novel.synopsis_theme_terms),
        source_mode=novel.source_mode,
        candidate_sha256=digest,
    )
    session.add(snapshot)
    session.flush()
    updated = _as_utc(novel.observed_at) >= _as_utc(record.latest_observed_at)
    return JjwxcSnapshotWriteResult(
        author_record_id=author.id,
        novel_record_id=record.id,
        snapshot_id=snapshot.id,
        snapshot_created=True,
        current_projection_updated=updated,
    )


def _upsert_author(session: Session, novel: JjwxcNovel) -> JjwxcAuthorRecord:
    author = session.scalar(
        select(JjwxcAuthorRecord).where(JjwxcAuthorRecord.author_id == novel.author_id)
    )
    if author is None:
        author = JjwxcAuthorRecord(
            author_id=novel.author_id,
            display_name=novel.author_display_name,
            first_seen_at=novel.observed_at,
            last_seen_at=novel.observed_at,
        )
        session.add(author)
        session.flush()
        return author
    if _as_utc(novel.observed_at) >= _as_utc(author.last_seen_at):
        author.display_name = novel.author_display_name
        author.last_seen_at = novel.observed_at
    return author


def _upsert_novel(
    session: Session,
    novel: JjwxcNovel,
    author: JjwxcAuthorRecord,
) -> JjwxcNovelRecord:
    record = session.scalar(
        select(JjwxcNovelRecord).where(JjwxcNovelRecord.novel_id == novel.novel_id)
    )
    values = {
        "title": novel.title,
        "author_record_id": author.id,
        "novel_type": novel.novel_type,
        "perspective": novel.perspective,
        "status": novel.status,
        "tags": list(novel.tags),
    }
    if record is None:
        record = JjwxcNovelRecord(
            novel_id=novel.novel_id,
            first_seen_at=novel.observed_at,
            latest_observed_at=novel.observed_at,
            **values,
        )
        session.add(record)
        session.flush()
        return record
    if _as_utc(novel.observed_at) >= _as_utc(record.latest_observed_at):
        for field, value in values.items():
            setattr(record, field, value)
        record.latest_observed_at = novel.observed_at
    return record


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
