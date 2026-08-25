from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from pixiv_yuri.jjwxc.database_catalog import _trend_points, load_author_ranking_frequency
from pixiv_yuri.jjwxc.demo import load_demo_catalog
from pixiv_yuri.jjwxc.models import JjwxcNovel
from pixiv_yuri.jjwxc.persistence import (
    JjwxcAuthorRecord,
    JjwxcChannelRankingSnapshot,
    JjwxcNovelRecord,
    JjwxcNovelSnapshot,
)
from pixiv_yuri.jjwxc.snapshot_store import (
    JjwxcSnapshotConflictError,
    store_novel_snapshot,
)
from pixiv_yuri.shared.database import Base


def _engine() -> Engine:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        execution_options={"schema_translate_map": {"ingest": None}},
    )
    Base.metadata.create_all(engine)
    return engine


def test_snapshot_store_is_idempotent_and_keeps_immutable_history() -> None:
    engine = _engine()
    first = load_demo_catalog().novels[0]
    later = first.model_copy(
        update={
            "title": "向晚潮声·修订名",
            "review_count": first.review_count + 25,
            "observed_at": first.observed_at + timedelta(hours=2),
        }
    )
    with Session(engine) as session:
        first_result = store_novel_snapshot(session, first)
        duplicate_result = store_novel_snapshot(session, first)
        later_result = store_novel_snapshot(session, later)
        session.commit()

    assert first_result.snapshot_created is True
    assert duplicate_result.snapshot_created is False
    assert later_result.snapshot_created is True
    assert later_result.current_projection_updated is True
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(JjwxcAuthorRecord)) == 1
        assert session.scalar(select(func.count()).select_from(JjwxcNovelRecord)) == 1
        assert session.scalar(select(func.count()).select_from(JjwxcNovelSnapshot)) == 2
        record = session.scalar(select(JjwxcNovelRecord))
        assert record is not None
        assert record.title == "向晚潮声·修订名"
        snapshots = session.scalars(
            select(JjwxcNovelSnapshot).order_by(JjwxcNovelSnapshot.observed_at)
        ).all()
        assert [item.review_count for item in snapshots] == [1260, 1285]
        assert snapshots[0].synopsis_theme_terms == ["都市", "成长"]


def test_database_timeline_includes_daily_cross_sectional_distributions() -> None:
    engine = _engine()
    novels = load_demo_catalog().novels
    with Session(engine) as session:
        for novel in novels:
            store_novel_snapshot(session, novel)
        session.commit()

    with Session(engine) as session:
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
            )
            .tuples()
            .all()
        )
        latest = _trend_points(rows)[-1]
    favorites = latest.metric_distributions["favorites"]

    assert favorites.observed_count == len(novels)
    assert favorites.top_group_count == len(novels)
    assert favorites.bottom_group_count == len(novels)
    assert favorites.median == 24_150
    assert favorites.lower_whisker is not None
    assert favorites.p25 is not None
    assert favorites.median is not None
    assert favorites.p75 is not None
    assert favorites.upper_whisker is not None
    assert favorites.lower_whisker <= favorites.p25 <= favorites.median
    assert favorites.median <= favorites.p75 <= favorites.upper_whisker


def test_author_ranking_frequency_counts_appearances_and_observed_days() -> None:
    engine = _engine()
    novel = load_demo_catalog().novels[0]
    with Session(engine) as session:
        store_novel_snapshot(session, novel)
        session.add_all(
            [
                JjwxcChannelRankingSnapshot(
                    ranking_key="channel_gold",
                    observation_day=date(2026, 8, 24),
                    observed_at=novel.observed_at,
                    rank=1,
                    novel_id=novel.novel_id,
                    title=novel.title,
                    source_rank_id="1001",
                ),
                JjwxcChannelRankingSnapshot(
                    ranking_key="newcomer",
                    observation_day=date(2026, 8, 24),
                    observed_at=novel.observed_at,
                    rank=2,
                    novel_id=novel.novel_id,
                    title=novel.title,
                    source_rank_id="1002",
                ),
                JjwxcChannelRankingSnapshot(
                    ranking_key="channel_gold",
                    observation_day=date(2026, 8, 25),
                    observed_at=novel.observed_at + timedelta(days=1),
                    rank=3,
                    novel_id=novel.novel_id,
                    title=novel.title,
                    source_rank_id="1003",
                ),
            ]
        )
        session.commit()

    frequency = load_author_ranking_frequency(sessionmaker(engine))

    assert frequency[novel.author_id] == (3, 2)


def test_older_snapshot_does_not_rewind_current_projection() -> None:
    engine = _engine()
    current = load_demo_catalog().novels[1]
    older = current.model_copy(
        update={
            "title": "旧标题",
            "observed_at": current.observed_at - timedelta(days=1),
        }
    )
    with Session(engine) as session:
        store_novel_snapshot(session, current)
        result = store_novel_snapshot(session, older)
        session.commit()

    assert result.current_projection_updated is False
    with Session(engine) as session:
        record = session.scalar(select(JjwxcNovelRecord))
        assert record is not None
        assert record.title == current.title


def test_same_time_with_different_values_is_rejected() -> None:
    engine = _engine()
    novel = load_demo_catalog().novels[2]
    conflicting = novel.model_copy(update={"review_count": novel.review_count + 1})
    with Session(engine) as session:
        store_novel_snapshot(session, novel)
        with pytest.raises(JjwxcSnapshotConflictError, match="observation time"):
            store_novel_snapshot(session, conflicting)
        session.rollback()


def test_snapshot_schema_cannot_store_raw_synopsis_or_source_url() -> None:
    column_names = {
        column.name
        for table in (
            JjwxcAuthorRecord.__table__,
            JjwxcNovelRecord.__table__,
            JjwxcNovelSnapshot.__table__,
        )
        for column in table.columns
    }
    assert "synopsis" not in column_names
    assert "source_url" not in column_names
    assert "raw_html" not in column_names


def test_snapshot_model_rejects_naive_observation_before_storage() -> None:
    novel = load_demo_catalog().novels[0]
    with pytest.raises(ValueError, match="timezone"):
        JjwxcNovel.model_validate({**novel.model_dump(), "observed_at": datetime(2026, 8, 23)})
