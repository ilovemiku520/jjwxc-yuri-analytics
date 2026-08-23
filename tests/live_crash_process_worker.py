"""Subprocess worker used only for abrupt process-crash recovery tests."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from pixiv_yuri.acquisition.first_request_slot import FirstRequestSlotService
from pixiv_yuri.acquisition.live_execution_journal import LiveExecutionJournalService
from pixiv_yuri.acquisition.live_slot_reconciler import LiveSlotReconciliationService
from pixiv_yuri.acquisition.persistence_models import AcquisitionLiveExecutionJournal
from pixiv_yuri.acquisition.persistent_safety import PersistentAcquisitionSafety
from pixiv_yuri.governance.g0 import G0Approval, approval_fingerprint
from pixiv_yuri.ingest.models import CrawlRun
from pixiv_yuri.shared.database import Base
from tests.test_g0_governance import valid_approval_payload

NOW = datetime(2026, 8, 23, tzinfo=UTC)
REQUEST_KEY = "process-crash:synthetic:work:42"
ABRUPT_EXIT_CODE = 71


def _factory(database_path: Path) -> sessionmaker[Session]:
    engine = create_engine(
        f"sqlite+pysqlite:///{database_path.as_posix()}",
        execution_options={"schema_translate_map": {"ingest": None}},
    )
    return sessionmaker(bind=engine, expire_on_commit=False)


def crash_at(database_path: Path, stage: str) -> None:
    factory = _factory(database_path)
    engine = factory.kw["bind"]
    assert engine is not None
    Base.metadata.create_all(engine)
    approval = G0Approval.model_validate(valid_approval_payload())
    fingerprint = approval_fingerprint(approval)
    with factory.begin() as session:
        run = CrawlRun(
            run_type="process_crash_recovery_test",
            provider="none",
            status="running",
            config_snapshot={"network": False, "crash_stage": stage},
            requested_by="test-subprocess",
            started_at=NOW,
        )
        session.add(run)
        session.flush()
        run_id = run.id
    safety = PersistentAcquisitionSafety(factory, approval, run_id)
    safety.initialize(now=NOW)
    claim = FirstRequestSlotService(factory).claim(
        approval_fingerprint=fingerprint,
        run_id=run_id,
        request_key=REQUEST_KEY,
        now=NOW,
    )
    journals = LiveExecutionJournalService(factory)
    journal = journals.claim(
        approval_fingerprint=fingerprint,
        run_id=run_id,
        slot_id=claim.slot_id,
        request_binding_hash=claim.request_key_hash,
        now=NOW,
    )
    if stage == "claimed":
        os._exit(ABRUPT_EXIT_CODE)
    permit = safety.authorize_and_start_live_send(
        journal_id=journal.journal_id,
        request_key=REQUEST_KEY,
        now=NOW,
    )
    if stage == "send_started":
        os._exit(ABRUPT_EXIT_CODE)
    safety.record_response(permit.permit_id, 200, now=NOW)
    settled = journals.settle(journal.journal_id, permit_id=permit.permit_id, now=NOW)
    if stage == "settled":
        os._exit(ABRUPT_EXIT_CODE)
    journals.complete(settled.journal_id, now=NOW)
    os._exit(ABRUPT_EXIT_CODE)


def recover(database_path: Path) -> None:
    factory = _factory(database_path)
    with factory() as session:
        journal_id = session.scalar(select(AcquisitionLiveExecutionJournal.id))
    if journal_id is None:
        raise RuntimeError("Crash worker did not durably create a journal.")
    result = LiveSlotReconciliationService(factory).reconcile(journal_id, now=NOW)
    print(
        json.dumps(
            {
                "journal_state": result.journal_state.value,
                "slot_status": result.slot_status,
                "resent": result.resent,
                "sender_module_loaded": (
                    "pixiv_yuri.acquisition.durable_external_sender" in sys.modules
                ),
            },
            sort_keys=True,
        ),
        flush=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("crash", "recover"))
    parser.add_argument("database_path", type=Path)
    parser.add_argument(
        "--stage",
        choices=("claimed", "send_started", "settled", "completed"),
    )
    args = parser.parse_args()
    if args.mode == "crash":
        if args.stage is None:
            raise SystemExit("--stage is required in crash mode")
        crash_at(args.database_path.resolve(), args.stage)
    recover(args.database_path.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
