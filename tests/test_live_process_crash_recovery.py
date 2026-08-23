from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from pixiv_yuri.acquisition.first_request_slot import (
    FirstRequestAlreadyClaimedError,
    FirstRequestSlotService,
)
from pixiv_yuri.acquisition.persistence_models import (
    AcquisitionFirstRequestSlot,
    AcquisitionLiveExecutionJournal,
    AcquisitionRequestPermit,
    AcquisitionRunBudget,
)
from tests.live_crash_process_worker import ABRUPT_EXIT_CODE

ROOT = Path(__file__).resolve().parents[1]


def _environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        (str(ROOT / "src"), str(ROOT))
    )
    environment["PYURI_ENABLE_NETWORK"] = "false"
    return environment


def _factory(database_path: Path) -> sessionmaker[Session]:
    engine = create_engine(
        f"sqlite+pysqlite:///{database_path.as_posix()}",
        execution_options={"schema_translate_map": {"ingest": None}},
    )
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.mark.parametrize(
    ("stage", "journal_state", "slot_status", "permit_status"),
    [
        ("claimed", "failed", "failed", None),
        ("send_started", "indeterminate", "failed", "transport_failed"),
        ("settled", "failed", "failed", "consumed"),
        ("completed", "completed", "completed", "consumed"),
    ],
)
def test_abrupt_process_exit_then_new_process_recovers_without_resend(
    tmp_path: Path,
    stage: str,
    journal_state: str,
    slot_status: str,
    permit_status: str | None,
) -> None:
    database_path = tmp_path / f"crash-{stage}.sqlite3"
    crashed = subprocess.run(
        [
            sys.executable,
            "-m",
            "tests.live_crash_process_worker",
            "crash",
            str(database_path),
            "--stage",
            stage,
        ],
        cwd=ROOT,
        env=_environment(),
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert crashed.returncode == ABRUPT_EXIT_CODE
    assert crashed.stdout == ""

    recovered = subprocess.run(
        [
            sys.executable,
            "-m",
            "tests.live_crash_process_worker",
            "recover",
            str(database_path),
        ],
        cwd=ROOT,
        env=_environment(),
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )
    evidence = json.loads(recovered.stdout)
    assert evidence == {
        "journal_state": journal_state,
        "resent": False,
        "sender_module_loaded": False,
        "slot_status": slot_status,
    }

    factory = _factory(database_path)
    with factory() as session:
        journal = session.scalar(select(AcquisitionLiveExecutionJournal))
        slot = session.scalar(select(AcquisitionFirstRequestSlot))
        permit = session.scalar(select(AcquisitionRequestPermit))
        budget = session.scalar(select(AcquisitionRunBudget))
        assert journal is not None and journal.status == journal_state
        assert slot is not None and slot.status == slot_status
        assert budget is not None and budget.in_flight_count == 0
        assert (permit.status if permit is not None else None) == permit_status
        fingerprint = slot.approval_fingerprint
        run_id = slot.run_id
    with pytest.raises(FirstRequestAlreadyClaimedError):
        FirstRequestSlotService(factory).claim(
            approval_fingerprint=fingerprint,
            run_id=run_id,
            request_key="attempted-reuse-must-fail",
        )
