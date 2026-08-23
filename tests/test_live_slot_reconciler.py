from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from pixiv_yuri.acquisition.first_request_slot import FirstRequestSlotService
from pixiv_yuri.acquisition.live_execution_journal import LiveExecutionState
from pixiv_yuri.acquisition.live_slot_reconciler import LiveSlotReconciliationService
from pixiv_yuri.acquisition.persistence_models import (
    AcquisitionFirstRequestSlot,
    AcquisitionLiveExecutionJournal,
    AcquisitionRequestPermit,
    AcquisitionRunBudget,
)
from pixiv_yuri.acquisition.persistent_safety import PersistentAcquisitionSafety
from pixiv_yuri.governance.g0 import G0Approval, approval_fingerprint
from pixiv_yuri.ingest.models import CrawlRun
from pixiv_yuri.shared.database import Base
from tests.test_g0_governance import valid_approval_payload

NOW = datetime(2026, 8, 23, tzinfo=UTC)


def build_state(status: str) -> tuple[LiveSlotReconciliationService, int, sessionmaker[Session]]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        execution_options={"schema_translate_map": {"ingest": None}},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    approval = G0Approval.model_validate(valid_approval_payload())
    fingerprint = approval_fingerprint(approval)
    with factory.begin() as session:
        run = CrawlRun(
            run_type="live_slot_reconciliation_test",
            provider="synthetic",
            status="running",
            config_snapshot={"network": "disabled"},
            requested_by="test",
        )
        session.add(run)
        session.flush()
        run_id = run.id
    PersistentAcquisitionSafety(factory, approval, run_id).initialize(now=NOW)
    claim = FirstRequestSlotService(factory).claim(
        approval_fingerprint=fingerprint,
        run_id=run_id,
        request_key="synthetic-reconcile-key",
        now=NOW,
    )
    with factory.begin() as session:
        permit_required = status in {
            "send_started",
            "settled",
            "completed",
            "indeterminate",
        }
        permit_id = "11111111-1111-1111-1111-111111111111" if permit_required else None
        if permit_id is not None:
            budget = session.scalar(
                select(AcquisitionRunBudget).where(AcquisitionRunBudget.run_id == run_id)
            )
            assert budget is not None
            permit_is_consumed = status in {"settled", "completed"}
            budget.request_count = 1
            budget.in_flight_count = 0 if permit_is_consumed else 1
            session.add(
                AcquisitionRequestPermit(
                    permit_id=permit_id,
                    run_budget_id=budget.id,
                    sequence=1,
                    request_key_hash=claim.request_key_hash,
                    approval_fingerprint=fingerprint,
                    estimated_cost=0,
                    status="consumed" if permit_is_consumed else "authorized",
                    authorized_at=NOW,
                    consumed_at=NOW if permit_is_consumed else None,
                    response_status=200 if permit_is_consumed else None,
                )
            )
        journal = AcquisitionLiveExecutionJournal(
            approval_fingerprint=fingerprint,
            run_id=run_id,
            slot_id=claim.slot_id,
            request_binding_hash=claim.request_key_hash,
            permit_id=permit_id,
            status=status,
            claimed_at=NOW,
            send_started_at=NOW if permit_required else None,
            settled_at=NOW if status in {"settled", "completed"} else None,
            resolved_at=NOW if status in {"completed", "failed", "indeterminate"} else None,
            failure_code=(
                "synthetic_failure" if status in {"failed", "indeterminate"} else None
            ),
        )
        session.add(journal)
        session.flush()
        journal_id = journal.id
    assert journal_id is not None
    return LiveSlotReconciliationService(factory), journal_id, factory


@pytest.mark.parametrize(
    ("initial_state", "journal_state", "slot_status"),
    [
        ("claimed", LiveExecutionState.FAILED, "failed"),
        ("send_started", LiveExecutionState.INDETERMINATE, "failed"),
        ("settled", LiveExecutionState.FAILED, "failed"),
        ("failed", LiveExecutionState.FAILED, "failed"),
        ("indeterminate", LiveExecutionState.INDETERMINATE, "failed"),
        ("completed", LiveExecutionState.COMPLETED, "completed"),
    ],
)
def test_reconcile_terminalizes_without_resend_and_is_idempotent(
    initial_state: str,
    journal_state: LiveExecutionState,
    slot_status: str,
) -> None:
    service, journal_id, factory = build_state(initial_state)

    first = service.reconcile(journal_id, now=NOW)
    second = service.reconcile(journal_id, now=NOW)

    assert first == second
    assert first.journal_state == journal_state
    assert first.slot_status == slot_status
    assert first.resent is False
    assert first.network_send_confirmed is None
    with factory() as session:
        slot = session.scalar(select(AcquisitionFirstRequestSlot))
        journal = session.scalar(select(AcquisitionLiveExecutionJournal))
        assert slot is not None and slot.status == slot_status
        assert journal is not None and journal.status == journal_state.value
