from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from pixiv_yuri.acquisition.parsers.registry import build_offline_fixture_registry
from pixiv_yuri.acquisition.persistence_models import (
    AcquisitionDailyBudget,
    AcquisitionFirstRequestSlot,
    AcquisitionRequestPermit,
    AcquisitionRunBudget,
    AcquisitionStopEvent,
)
from pixiv_yuri.acquisition.providers.fixture import FixtureProvider
from pixiv_yuri.api.persistence_models import (
    ApiConsumerAccessAudit,
    ApiConsumerRateLimitWindow,
)
from pixiv_yuri.data_quality.validation import load_schema_policy
from pixiv_yuri.ingest.models import (
    CrawlRun,
    CrawlTask,
    QuarantineRecord,
    RawObservation,
    SchemaDefinition,
    SourceRecord,
    TaskAttempt,
)
from pixiv_yuri.ingest.service import ingest_fixture_provider
from pixiv_yuri.shared.database import Base

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = PROJECT_ROOT / "fixtures" / "manifest.json"
POLICY = PROJECT_ROOT / "fixtures" / "schema_policy.json"


def build_test_engine() -> Engine:
    """Create a disposable SQLite ledger with the ingest schema translated away."""
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        execution_options={"schema_translate_map": {"ingest": None}},
    )
    Base.metadata.create_all(engine)
    return engine


class IngestModelTests(unittest.TestCase):
    def test_expected_ingest_tables_are_registered(self) -> None:
        tables = {table.name for table in Base.metadata.tables.values()}
        self.assertEqual(
            tables,
            {
                "source_records",
                "crawl_runs",
                "crawl_tasks",
                "task_attempts",
                "raw_observations",
                "schema_definitions",
                "quarantine_records",
                "discovery_checkpoints",
                "acquisition_daily_budgets",
                "acquisition_run_budgets",
                "acquisition_request_permits",
                "acquisition_stop_events",
                "acquisition_first_request_slots",
                "acquisition_live_execution_journals",
                "catalog_authors",
                "catalog_works",
                "catalog_tags",
                "catalog_work_tags",
                "catalog_work_metric_snapshots",
                "api_consumer_rate_limit_windows",
                "api_consumer_access_audits",
                "jjwxc_authors",
                "jjwxc_novels",
                "jjwxc_catalog_index",
                "jjwxc_author_snapshots",
                "jjwxc_novel_snapshots",
                "jjwxc_ranking_snapshots",
                "jjwxc_channel_ranking_snapshots",
                "jjwxc_discovery_queue",
                "jjwxc_chapter_snapshots",
            },
        )
        self.assertNotIn("body", RawObservation.__table__.columns)
        safety_columns = {
            column.name
            for model in (
                AcquisitionDailyBudget,
                AcquisitionFirstRequestSlot,
                AcquisitionRunBudget,
                AcquisitionRequestPermit,
                AcquisitionStopEvent,
            )
            for column in model.__table__.columns
        }
        for prohibited in ("password", "cookie", "authorization", "token", "secret"):
            self.assertNotIn(prohibited, safety_columns)
        consumer_control_columns = {
            column.name
            for model in (ApiConsumerRateLimitWindow, ApiConsumerAccessAudit)
            for column in model.__table__.columns
        }
        for prohibited in ("subject", "query", "header", "cookie", "token", "authorization"):
            self.assertNotIn(prohibited, consumer_control_columns)

    def test_fixture_ingest_is_idempotent_for_raw_observations(self) -> None:
        engine = build_test_engine()
        with Session(engine) as session:
            first = ingest_fixture_provider(session, FixtureProvider(MANIFEST), requested_by="test")
            session.commit()
        with Session(engine) as session:
            second = ingest_fixture_provider(
                session, FixtureProvider(MANIFEST), requested_by="test"
            )
            session.commit()

        self.assertEqual(first.created_observations, 3)
        self.assertEqual(first.duplicate_observations, 0)
        self.assertEqual(second.created_observations, 0)
        self.assertEqual(second.duplicate_observations, 3)

        with Session(engine) as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(SourceRecord)), 3)
            self.assertEqual(session.scalar(select(func.count()).select_from(CrawlRun)), 2)
            self.assertEqual(session.scalar(select(func.count()).select_from(CrawlTask)), 6)
            self.assertEqual(session.scalar(select(func.count()).select_from(TaskAttempt)), 6)
            self.assertEqual(session.scalar(select(func.count()).select_from(RawObservation)), 3)
            self.assertEqual(session.scalar(select(func.count()).select_from(SchemaDefinition)), 3)
            self.assertEqual(session.scalar(select(func.count()).select_from(QuarantineRecord)), 0)
            sample_counts = session.scalars(select(SchemaDefinition.sample_count)).all()
            self.assertEqual(sample_counts, [1, 1, 1])

    def test_non_success_fixture_is_quarantined(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "missing.json").write_text("{}", encoding="utf-8")
            manifest = {
                "version": 1,
                "provider": "synthetic_failure_fixture",
                "records": [
                    {
                        "entity_type": "work",
                        "source_id": "missing-work",
                        "observed_at": "2026-08-22T00:00:00Z",
                        "path": "missing.json",
                        "status_code": 404,
                    }
                ],
            }
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            engine = build_test_engine()
            with Session(engine) as session:
                result = ingest_fixture_provider(session, FixtureProvider(manifest_path))
                session.commit()
            self.assertEqual(result.failed_tasks, 1)
            self.assertEqual(result.quarantine_records, 1)

            with Session(engine) as session:
                run = session.scalar(select(CrawlRun))
                source = session.scalar(select(SourceRecord))
                quarantine = session.scalar(select(QuarantineRecord))
                self.assertIsNotNone(run)
                self.assertIsNotNone(source)
                self.assertIsNotNone(quarantine)
                assert run is not None and source is not None and quarantine is not None
                self.assertEqual(run.status, "completed_with_errors")
                self.assertEqual(source.current_availability, "missing")
                self.assertEqual(quarantine.status, "open")

    def test_equal_schemas_within_one_batch_share_a_definition(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "shared.json").write_text('{"id": 1}', encoding="utf-8")
            manifest_path = root / "manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "provider": "synthetic_shared_schema",
                        "records": [
                            {
                                "entity_type": "work",
                                "source_id": source_id,
                                "observed_at": "2026-08-22T00:00:00Z",
                                "path": "shared.json",
                            }
                            for source_id in ("work-a", "work-b")
                        ],
                    }
                ),
                encoding="utf-8",
            )

            engine = build_test_engine()
            with Session(engine) as session:
                result = ingest_fixture_provider(session, FixtureProvider(manifest_path))
                session.commit()
            self.assertEqual(result.created_schema_definitions, 1)
            with Session(engine) as session:
                schema = session.scalar(select(SchemaDefinition))
                self.assertIsNotNone(schema)
                assert schema is not None
                self.assertEqual(schema.sample_count, 2)

    def test_policy_approved_ingest_records_valid_parser_provenance(self) -> None:
        engine = build_test_engine()
        with Session(engine) as session:
            result = ingest_fixture_provider(
                session,
                FixtureProvider(MANIFEST),
                schema_policy=load_schema_policy(POLICY),
                parser_registry=build_offline_fixture_registry(),
            )
            session.commit()
        self.assertEqual(result.quarantine_records, 0)
        with Session(engine) as session:
            observations = session.scalars(select(RawObservation)).all()
            self.assertEqual({item.validation_status for item in observations}, {"valid"})
            self.assertEqual({item.parser_version for item in observations}, {"0.1.0"})

    def test_unknown_policy_schemas_are_persisted_in_quarantine(self) -> None:
        policy = load_schema_policy(POLICY)
        author_only = policy.model_copy(update={"entries": policy.entries[:1]})
        engine = build_test_engine()
        with Session(engine) as session:
            result = ingest_fixture_provider(
                session,
                FixtureProvider(MANIFEST),
                schema_policy=author_only,
                parser_registry=build_offline_fixture_registry(),
            )
            session.commit()
        with Session(engine) as session:
            replay = ingest_fixture_provider(
                session,
                FixtureProvider(MANIFEST),
                schema_policy=author_only,
                parser_registry=build_offline_fixture_registry(),
            )
            session.commit()
        self.assertEqual(result.succeeded_tasks, 3)
        self.assertEqual(result.quarantine_records, 2)
        self.assertEqual(replay.quarantine_records, 0)
        with Session(engine) as session:
            runs = session.scalars(select(CrawlRun).order_by(CrawlRun.id)).all()
            quarantined = session.scalar(
                select(func.count()).select_from(RawObservation).where(
                    RawObservation.validation_status == "quarantined"
                )
            )
            errors = session.scalars(select(QuarantineRecord.error_code)).all()
            self.assertEqual(
                [run.status for run in runs],
                ["completed_with_errors", "completed_with_errors"],
            )
            self.assertEqual(quarantined, 2)
            self.assertEqual(errors, ["unknown_schema", "unknown_schema"])


if __name__ == "__main__":
    unittest.main()
