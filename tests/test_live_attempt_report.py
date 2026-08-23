from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from pixiv_yuri.acquisition.live_attempt_report import build_live_attempt_operator_report
from pixiv_yuri.acquisition.persistence_models import (
    AcquisitionFirstRequestSlot,
    AcquisitionLiveExecutionJournal,
)
from pixiv_yuri.ingest.models import CrawlRun
from pixiv_yuri.shared.database import Base

NOW = datetime(2026, 8, 23, tzinfo=UTC)


def build_state() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        execution_options={"schema_translate_map": {"ingest": None}},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory.begin() as session:
        runs = [
            CrawlRun(
                run_type="live_attempt_report_test",
                provider="none",
                status="running",
                config_snapshot={"network": False},
                requested_by="test",
            )
            for _ in range(2)
        ]
        session.add_all(runs)
        session.flush()
        unresolved_slot = AcquisitionFirstRequestSlot(
            approval_fingerprint="a" * 64,
            run_id=runs[0].id,
            request_key_hash="c" * 64,
            status="claimed",
            claimed_at=NOW,
        )
        orphan_slot = AcquisitionFirstRequestSlot(
            approval_fingerprint="b" * 64,
            run_id=runs[1].id,
            request_key_hash="d" * 64,
            status="claimed",
            claimed_at=NOW,
        )
        session.add_all((unresolved_slot, orphan_slot))
        session.flush()
        session.add(
            AcquisitionLiveExecutionJournal(
                approval_fingerprint="a" * 64,
                run_id=runs[0].id,
                slot_id=unresolved_slot.id,
                request_binding_hash="c" * 64,
                status="claimed",
                claimed_at=NOW,
            )
        )
    return factory


def test_report_is_read_only_bounded_and_excludes_sensitive_bindings() -> None:
    factory = build_state()

    report = build_live_attempt_operator_report(factory, now=NOW, limit=10)
    rendered = json.dumps(asdict(report), sort_keys=True)

    assert report.journal_counts == {"claimed": 1}
    assert report.slot_counts == {"claimed": 2}
    assert len(report.unresolved_attempts) == 1
    assert len(report.orphan_claimed_slots) == 1
    assert report.read_only is True
    assert report.authorizes_live_request is False
    assert report.network_send_confirmed is None
    for forbidden in (
        "request_binding_hash",
        "approval_fingerprint",
        "permit_id",
        "canonical_url",
        "cookie",
        "authorization",
        "body",
    ):
        assert forbidden not in rendered.lower()
    with factory() as session:
        assert len(session.scalars(select(AcquisitionFirstRequestSlot)).all()) == 2
        journal = session.scalar(select(AcquisitionLiveExecutionJournal))
        assert journal is not None and journal.status == "claimed"


def test_report_limit_sets_truncated_without_mutating_rows() -> None:
    factory = build_state()

    report = build_live_attempt_operator_report(factory, now=NOW, limit=1)

    assert report.truncated is False
    assert len(report.unresolved_attempts) == 1
    assert len(report.orphan_claimed_slots) == 1
