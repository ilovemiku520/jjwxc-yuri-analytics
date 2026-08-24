"""Read minimized JJWXC snapshots into the public analytics projection."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Literal, cast
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, sessionmaker

from pixiv_yuri.jjwxc.demo import JjwxcDemoCatalog, load_demo_catalog
from pixiv_yuri.jjwxc.models import JjwxcCatalogSearchItem, JjwxcNovel, JjwxcTrendPoint
from pixiv_yuri.jjwxc.persistence import (
    JjwxcAuthorRecord,
    JjwxcAuthorSnapshot,
    JjwxcCatalogIndexRecord,
    JjwxcNovelRecord,
    JjwxcNovelSnapshot,
)

DataMode = Literal["synthetic_fixture", "database_snapshot"]
_SHANGHAI = ZoneInfo("Asia/Shanghai")


def load_catalog(
    factory: sessionmaker[Session] | None,
    *,
    selected_day: str | None = None,
) -> tuple[JjwxcDemoCatalog, DataMode]:
    """Use canonical database snapshots when present; otherwise retain explicit fixtures."""
    if factory is None:
        return load_demo_catalog(), "synthetic_fixture"
    with factory() as session:
        rows = list(
            session.execute(
                select(JjwxcNovelSnapshot, JjwxcNovelRecord, JjwxcAuthorRecord)
                .join(
                    JjwxcNovelRecord,
                    JjwxcNovelRecord.id == JjwxcNovelSnapshot.novel_record_id,
                )
                .join(
                    JjwxcAuthorRecord,
                    JjwxcAuthorRecord.id == JjwxcNovelRecord.author_record_id,
                )
                .order_by(JjwxcNovelSnapshot.observed_at.desc())
            )
            .tuples()
            .all()
        )
    # Never blend real public candidates with synthetic smoke-test rows in one cohort.
    if any(snapshot.source_mode == "public_candidate" for snapshot, _, _ in rows):
        rows = [row for row in rows if row[0].source_mode == "public_candidate"]
    if selected_day is not None:
        target_day = date.fromisoformat(selected_day)
        rows = [
            row
            for row in rows
            if row[0].observed_at.astimezone(_SHANGHAI).date() == target_day
        ]
    latest: dict[str, tuple[JjwxcNovelSnapshot, JjwxcNovelRecord, JjwxcAuthorRecord]] = {}
    for snapshot, record, author in rows:
        latest.setdefault(record.novel_id, (snapshot, record, author))
    if not latest:
        return load_demo_catalog(), "synthetic_fixture"
    novels = tuple(_novel_from_row(*row) for row in latest.values())
    trends = _trend_points(rows)
    return (
        JjwxcDemoCatalog(
            dataset_label="JJWXC canonical database snapshots",
            novels=novels,
            trends=trends,
        ),
        "database_snapshot",
    )


def available_snapshot_days(factory: sessionmaker[Session] | None) -> tuple[str, ...]:
    if factory is None:
        return ()
    with factory() as session:
        source_modes = set(session.scalars(select(JjwxcNovelSnapshot.source_mode)).all())
        statement = select(JjwxcNovelSnapshot.observed_at)
        if "public_candidate" in source_modes:
            statement = statement.where(JjwxcNovelSnapshot.source_mode == "public_candidate")
        observed = session.scalars(statement).all()
    return tuple(
        sorted({item.astimezone(_SHANGHAI).date().isoformat() for item in observed})
    )


def load_latest_author_profiles(
    factory: sessionmaker[Session] | None,
    *,
    selected_day: str | None = None,
) -> dict[str, JjwxcAuthorSnapshot]:
    if factory is None:
        return {}
    with factory() as session:
        rows = list(
            session.execute(
                select(JjwxcAuthorSnapshot, JjwxcAuthorRecord)
                .join(
                    JjwxcAuthorRecord,
                    JjwxcAuthorRecord.id == JjwxcAuthorSnapshot.author_record_id,
                )
                .order_by(JjwxcAuthorSnapshot.observed_at.desc())
            )
            .tuples()
            .all()
        )
    latest: dict[str, JjwxcAuthorSnapshot] = {}
    for snapshot, author in rows:
        if (
            selected_day is not None
            and snapshot.observed_at.astimezone(_SHANGHAI).date().isoformat() != selected_day
        ):
            continue
        latest.setdefault(author.author_id, snapshot)
    return latest


def search_catalog(
    factory: sessionmaker[Session] | None,
    *,
    query: str,
    limit: int,
    offset: int,
) -> tuple[tuple[JjwxcNovel, ...], int, DataMode]:
    """Search the canonical title/author index without loading the whole catalog."""
    if factory is None:
        catalog = load_demo_catalog()
        needle = query.casefold()
        matches = tuple(
            item
            for item in catalog.novels
            if needle in item.title.casefold() or needle in item.author_display_name.casefold()
        )
        return matches[offset : offset + limit], len(matches), "synthetic_fixture"
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped}%"
    with factory() as session:
        latest = (
            select(
                JjwxcNovelSnapshot.novel_record_id.label("novel_record_id"),
                func.max(JjwxcNovelSnapshot.observed_at).label("observed_at"),
            )
            .where(JjwxcNovelSnapshot.source_mode == "public_candidate")
            .group_by(JjwxcNovelSnapshot.novel_record_id)
            .subquery()
        )
        base = (
            select(JjwxcNovelSnapshot, JjwxcNovelRecord, JjwxcAuthorRecord)
            .join(
                latest,
                (latest.c.novel_record_id == JjwxcNovelSnapshot.novel_record_id)
                & (latest.c.observed_at == JjwxcNovelSnapshot.observed_at),
            )
            .join(
                JjwxcNovelRecord,
                JjwxcNovelRecord.id == JjwxcNovelSnapshot.novel_record_id,
            )
            .join(
                JjwxcAuthorRecord,
                JjwxcAuthorRecord.id == JjwxcNovelRecord.author_record_id,
            )
            .where(
                or_(
                    JjwxcNovelRecord.title.ilike(pattern, escape="\\"),
                    JjwxcAuthorRecord.display_name.ilike(pattern, escape="\\"),
                )
            )
        )
        total = session.scalar(select(func.count()).select_from(base.subquery())) or 0
        rows = list(
            session.execute(
                base.order_by(
                    JjwxcNovelSnapshot.favorite_count.desc(),
                    JjwxcNovelRecord.novel_id,
                )
                .offset(offset)
                .limit(limit)
            )
            .tuples()
            .all()
        )
    if not rows and total == 0:
        return (), 0, "database_snapshot"
    return tuple(_novel_from_row(*row) for row in rows), total, "database_snapshot"


def search_full_catalog_index(
    factory: sessionmaker[Session] | None,
    *,
    query: str,
    limit: int,
    offset: int,
) -> tuple[tuple[JjwxcCatalogSearchItem, ...], int, DataMode]:
    """Search the lightweight, progressively swept yuri work-library index."""
    if factory is None:
        catalog = load_demo_catalog()
        needle = query.casefold()
        matches = [
            item
            for item in catalog.novels
            if needle in item.title.casefold() or needle in item.author_display_name.casefold()
        ]
        items = tuple(
            JjwxcCatalogSearchItem(
                novel_id=item.novel_id,
                title=item.title,
                author_id=item.author_id,
                author_display_name=item.author_display_name,
                novel_type=item.novel_type,
                status=item.status,
                word_count=item.word_count,
                points=item.points,
                published_at=None,
                last_seen_at=item.observed_at,
                detail_available=True,
            )
            for item in matches[offset : offset + limit]
        )
        return items, len(matches), "synthetic_fixture"
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped}%"
    condition = or_(
        JjwxcCatalogIndexRecord.title.ilike(pattern, escape="\\"),
        JjwxcCatalogIndexRecord.author_display_name.ilike(pattern, escape="\\"),
    )
    with factory() as session:
        total = session.scalar(
            select(func.count()).select_from(JjwxcCatalogIndexRecord).where(condition)
        ) or 0
        rows = list(
            session.execute(
                select(JjwxcCatalogIndexRecord, JjwxcNovelRecord.id)
                .outerjoin(
                    JjwxcNovelRecord,
                    JjwxcNovelRecord.novel_id == JjwxcCatalogIndexRecord.novel_id,
                )
                .where(condition)
                .order_by(
                    JjwxcCatalogIndexRecord.points.desc(),
                    JjwxcCatalogIndexRecord.novel_id,
                )
                .offset(offset)
                .limit(limit)
            ).tuples()
        )
    return (
        tuple(
            JjwxcCatalogSearchItem(
                novel_id=record.novel_id,
                title=record.title,
                author_id=record.author_id,
                author_display_name=record.author_display_name,
                novel_type=record.novel_type,
                status=cast(
                    Literal["连载", "完结", "暂停", "锁定", "未知"], record.status
                ),
                word_count=record.word_count,
                points=record.points,
                published_at=record.published_at,
                last_seen_at=record.last_seen_at,
                detail_available=novel_record_id is not None,
            )
            for record, novel_record_id in rows
        ),
        total,
        "database_snapshot",
    )


def _novel_from_row(
    snapshot: JjwxcNovelSnapshot,
    record: JjwxcNovelRecord,
    author: JjwxcAuthorRecord,
) -> JjwxcNovel:
    return JjwxcNovel(
        novel_id=record.novel_id,
        title=record.title,
        author_id=author.author_id,
        author_display_name=author.display_name,
        novel_type=record.novel_type,
        perspective=record.perspective,
        status=cast(Literal["连载", "完结", "暂停", "锁定", "未知"], record.status),
        word_count=snapshot.word_count,
        review_count=snapshot.review_count,
        favorite_count=snapshot.favorite_count,
        points=snapshot.points,
        average_non_v_chapter_click_count=snapshot.average_non_v_chapter_click_count,
        average_v_chapter_click_count=snapshot.average_v_chapter_click_count,
        non_v_chapter_count=snapshot.non_v_chapter_count,
        v_chapter_count=snapshot.v_chapter_count,
        chapter_click_coverage_count=snapshot.chapter_click_coverage_count,
        synopsis_char_count=snapshot.synopsis_char_count,
        synopsis_sentence_count=snapshot.synopsis_sentence_count,
        synopsis_theme_terms=tuple(snapshot.synopsis_theme_terms),
        tags=tuple(record.tags),
        observed_at=snapshot.observed_at,
        source_mode=cast(Literal["synthetic_fixture", "public_candidate"], snapshot.source_mode),
    )


def _trend_points(
    rows: list[tuple[JjwxcNovelSnapshot, JjwxcNovelRecord, JjwxcAuthorRecord]],
) -> tuple[JjwxcTrendPoint, ...]:
    latest_per_day: dict[
        tuple[str, str], tuple[JjwxcNovelSnapshot, JjwxcNovelRecord, JjwxcAuthorRecord]
    ] = {}
    for row in rows:
        snapshot, record, _ = row
        day = snapshot.observed_at.astimezone(_SHANGHAI).date().isoformat()
        latest_per_day.setdefault((day, record.novel_id), row)
    grouped: dict[str, list[JjwxcNovelSnapshot]] = defaultdict(list)
    for (day, _), (snapshot, _, _) in latest_per_day.items():
        grouped[day].append(snapshot)
    points: list[JjwxcTrendPoint] = []
    for day, snapshots in sorted(grouped.items()):
        clicks = [
            item.average_non_v_chapter_click_count
            for item in snapshots
            if item.average_non_v_chapter_click_count is not None
        ]
        v_clicks = [
            item.average_v_chapter_click_count
            for item in snapshots
            if item.average_v_chapter_click_count is not None
        ]
        points.append(
            JjwxcTrendPoint(
                day=day,
                observed_novel_count=len(snapshots),
                total_review_count=sum(item.review_count for item in snapshots),
                total_favorite_count=sum(item.favorite_count for item in snapshots),
                total_points=sum(item.points for item in snapshots),
                total_word_count=sum(item.word_count for item in snapshots),
                click_coverage_count=len(clicks),
                mean_non_v_chapter_click_count=(sum(clicks) / len(clicks) if clicks else None),
                v_click_coverage_count=len(v_clicks),
                mean_v_chapter_click_count=(
                    sum(v_clicks) / len(v_clicks) if v_clicks else None
                ),
            )
        )
    return tuple(points)
