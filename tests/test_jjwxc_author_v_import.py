from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from pixiv_yuri.api.app import create_app
from pixiv_yuri.jjwxc.author_v_import import AuthorVClickRecord, import_author_v_clicks
from pixiv_yuri.jjwxc.demo import load_demo_catalog
from pixiv_yuri.jjwxc.persistence import JjwxcChapterSnapshot, JjwxcNovelSnapshot
from pixiv_yuri.jjwxc.snapshot_store import store_novel_snapshot
from pixiv_yuri.shared.database import Base


def _factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        execution_options={"schema_translate_map": {"ingest": None}},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(engine)


def _seed(factory: sessionmaker[Session]) -> str:
    observed_at = datetime(2026, 8, 24, 3, 30, tzinfo=UTC)
    novel = load_demo_catalog().novels[0].model_copy(
        update={
            "observed_at": observed_at,
            "source_mode": "public_candidate",
            "non_v_chapter_count": 1,
            "v_chapter_count": 2,
            "chapter_click_coverage_count": 1,
            "average_non_v_chapter_click_count": 500,
            "average_v_chapter_click_count": None,
        }
    )
    with factory() as session:
        write = store_novel_snapshot(session, novel)
        for chapter_id, is_vip, clicks in ((1, False, 500), (2, True, None), (3, True, None)):
            session.add(
                JjwxcChapterSnapshot(
                    novel_record_id=write.novel_record_id,
                    observed_at=observed_at,
                    chapter_id=chapter_id,
                    position=chapter_id,
                    is_vip=is_vip,
                    word_count=3_000,
                    click_count=clicks,
                )
            )
        session.commit()
    return novel.novel_id


def test_author_export_enriches_v_clicks_without_overwriting_non_v_clicks() -> None:
    factory = _factory()
    novel_id = _seed(factory)
    imported_at = datetime(2026, 8, 24, 4, 0, tzinfo=UTC)
    with factory() as session:
        result = import_author_v_clicks(
            session,
            records=(
                AuthorVClickRecord(novel_id, 2, 300),
                AuthorVClickRecord(novel_id, 3, 200),
            ),
            observed_at=imported_at,
            authorization_attested=True,
            now=imported_at,
        )
    assert result[0].status == "imported"
    with factory() as session:
        enriched = session.scalar(
            select(JjwxcNovelSnapshot)
            .where(JjwxcNovelSnapshot.observed_at == imported_at)
        )
        latest = list(
            session.scalars(
                select(JjwxcChapterSnapshot)
                .where(JjwxcChapterSnapshot.observed_at == imported_at)
                .order_by(JjwxcChapterSnapshot.chapter_id)
            ).all()
        )
    assert enriched is not None
    assert enriched.average_non_v_chapter_click_count == 500
    assert enriched.average_v_chapter_click_count == 250
    assert enriched.chapter_click_coverage_count == 3
    assert [item.click_count for item in latest] == [500, 300, 200]


def test_author_export_rejects_incomplete_v_chapter_set() -> None:
    factory = _factory()
    novel_id = _seed(factory)
    imported_at = datetime(2026, 8, 24, 4, 0, tzinfo=UTC)
    with factory() as session:
        result = import_author_v_clicks(
            session,
            records=(AuthorVClickRecord(novel_id, 2, 300),),
            observed_at=imported_at,
            authorization_attested=True,
            now=imported_at,
        )
    assert result[0].status == "rejected"
    assert result[0].error_code == "vip_chapter_set_incomplete"


def test_internal_api_accepts_extension_contract(monkeypatch) -> None:
    factory = _factory()
    novel_id = _seed(factory)
    monkeypatch.setenv("PYURI_COHORT_IMPORT_TOKEN", "internal-test-token")
    app = create_app(lambda: None, session_factory=factory)
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/jjwxc/analytics/author-v-clicks/import",
            headers={"X-Pyuri-Internal-Operation": "internal-test-token"},
            json={
                "source_format": "pyuri_jjwxc_author_v_clicks_json",
                "schema_version": 1,
                "generated_at": "2026-08-24T04:00:00Z",
                "authorization_attestation": True,
                "records": [
                    {"novel_id": novel_id, "chapter_id": 2, "click_count": 300},
                    {"novel_id": novel_id, "chapter_id": 3, "click_count": 200},
                ],
            },
        )
    assert response.status_code == 200
    assert response.json()["accepted_novel_count"] == 1
    assert response.json()["accepted_chapter_count"] == 2
