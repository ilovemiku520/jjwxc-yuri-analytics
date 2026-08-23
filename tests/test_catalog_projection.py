from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from pixiv_yuri.acquisition.parsers.registry import build_offline_fixture_registry
from pixiv_yuri.acquisition.providers.fixture import FixtureProvider
from pixiv_yuri.analytics.models import (
    CatalogAuthor,
    CatalogTag,
    CatalogWork,
    CatalogWorkMetricSnapshot,
    CatalogWorkTag,
)
from pixiv_yuri.analytics.projection import FixtureProjectionError, project_fixture_catalog
from pixiv_yuri.data_quality.validation import load_schema_policy
from pixiv_yuri.ingest.service import ingest_fixture_provider
from pixiv_yuri.shared.database import Base

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = PROJECT_ROOT / "fixtures" / "manifest.json"
POLICY = PROJECT_ROOT / "fixtures" / "schema_policy.json"


def build_engine() -> Engine:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        execution_options={"schema_translate_map": {"ingest": None}},
    )
    Base.metadata.create_all(engine)
    return engine


def ingest_valid_fixtures(session: Session) -> FixtureProvider:
    provider = FixtureProvider(MANIFEST)
    ingest_fixture_provider(
        session,
        provider,
        schema_policy=load_schema_policy(POLICY),
        parser_registry=build_offline_fixture_registry(),
    )
    return provider


def test_projection_is_normalized_minimized_and_idempotent() -> None:
    engine = build_engine()
    with Session(engine) as session:
        provider = ingest_valid_fixtures(session)
        first = project_fixture_catalog(session, provider)
        session.commit()
    with Session(engine) as session:
        second = project_fixture_catalog(session, FixtureProvider(MANIFEST))
        session.commit()

    assert first == second
    assert (
        first.authors,
        first.works,
        first.tags,
        first.work_tags,
        first.metric_snapshots,
    ) == (1, 2, 2, 3, 2)
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(CatalogAuthor)) == 1
        assert session.scalar(select(func.count()).select_from(CatalogWork)) == 2
        assert session.scalar(select(func.count()).select_from(CatalogTag)) == 2
        assert session.scalar(select(func.count()).select_from(CatalogWorkTag)) == 3
        assert session.scalar(
            select(func.count()).select_from(CatalogWorkMetricSnapshot)
        ) == 2
        works = session.scalars(select(CatalogWork).order_by(CatalogWork.work_id)).all()
        assert [work.public_like_count for work in works] == [120, 98]
        assert [work.public_bookmark_count for work in works] == [75, 61]
        assert all(work.public_view_count is None for work in works)

    column_names = {
        column.name
        for table in (CatalogAuthor.__table__, CatalogWork.__table__, CatalogTag.__table__)
        for column in table.columns
    }
    for forbidden in (
        "description",
        "comments",
        "followers",
        "profile",
        "region",
        "source_url",
        "payload",
    ):
        assert forbidden not in column_names


def test_projection_requires_an_exact_valid_observation() -> None:
    engine = build_engine()
    with Session(engine) as session:
        with pytest.raises(FixtureProjectionError, match="exact valid observation"):
            project_fixture_catalog(session, FixtureProvider(MANIFEST))
        session.rollback()

    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(CatalogWork)) == 0
