"""Idempotent no-resend reconciliation from a durable journal to its first slot."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from pixiv_yuri.acquisition.first_request_slot import (
    FirstRequestClaim,
    FirstRequestSlotBindingError,
    FirstRequestSlotService,
)
from pixiv_yuri.acquisition.live_execution_journal import (
    LiveExecutionJournalRecord,
    LiveExecutionJournalService,
    LiveExecutionState,
)
from pixiv_yuri.acquisition.persistence_models import (
    AcquisitionFirstRequestSlot,
    AcquisitionRequestPermit,
    AcquisitionRunBudget,
)


class LiveSlotReconciliationError(RuntimeError):
    """Safe failure when durable journal and permanent slot disagree."""


@dataclass(frozen=True, slots=True)
class LiveSlotReconciliationResult:
    journal_id: int
    journal_state: LiveExecutionState
    slot_status: str
    resent: bool
    network_send_confirmed: None


class LiveSlotReconciliationService:
    """Resolve a claimed slot from journal evidence and never invoke a sender."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory
        self._journals = LiveExecutionJournalService(session_factory)
        self._slots = FirstRequestSlotService(session_factory)

    def reconcile(
        self, journal_id: int, *, now: datetime | None = None
    ) -> LiveSlotReconciliationResult:
        checked_at = _aware_utc(now or datetime.now(UTC))
        try:
            journal = self._journals.recover_without_resend(
                journal_id,
                now=checked_at,
            )
            target = (
                "completed"
                if journal.state == LiveExecutionState.COMPLETED
                else "failed"
            )
            self._consume_uncertain_permit(journal, checked_at)
            claim = FirstRequestClaim(
                slot_id=journal.slot_id,
                approval_fingerprint=journal.approval_fingerprint,
                run_id=journal.run_id,
                request_key_hash=journal.request_binding_hash,
                claimed_at=journal.claimed_at,
            )
            try:
                if target == "completed":
                    self._slots.complete(claim, now=checked_at)
                else:
                    self._slots.fail(claim, now=checked_at)
            except FirstRequestSlotBindingError:
                if self._read_slot_status(claim) != target:
                    raise
        except Exception:
            raise LiveSlotReconciliationError(
                "Live journal and first-request slot could not be reconciled."
            ) from None
        return LiveSlotReconciliationResult(
            journal_id=journal.journal_id,
            journal_state=journal.state,
            slot_status=target,
            resent=False,
            network_send_confirmed=None,
        )

    def _read_slot_status(self, claim: FirstRequestClaim) -> str | None:
        with self._session_factory() as session:
            return session.scalar(
                select(AcquisitionFirstRequestSlot.status).where(
                    AcquisitionFirstRequestSlot.id == claim.slot_id,
                    AcquisitionFirstRequestSlot.approval_fingerprint
                    == claim.approval_fingerprint,
                    AcquisitionFirstRequestSlot.run_id == claim.run_id,
                    AcquisitionFirstRequestSlot.request_key_hash
                    == claim.request_key_hash,
                )
            )

    def _consume_uncertain_permit(
        self, journal: LiveExecutionJournalRecord, consumed_at: datetime
    ) -> None:
        permit_id = journal.permit_id
        state = journal.state
        if permit_id is None or state not in {
            LiveExecutionState.FAILED,
            LiveExecutionState.INDETERMINATE,
        }:
            return
        with self._session_factory.begin() as session:
            permit = session.scalar(
                select(AcquisitionRequestPermit)
                .where(AcquisitionRequestPermit.permit_id == permit_id)
                .with_for_update()
            )
            if permit is None:
                raise LiveSlotReconciliationError("Durable request permit is unavailable.")
            if permit.status in {"consumed", "transport_failed"}:
                return
            if permit.status != "authorized":
                raise LiveSlotReconciliationError("Durable request permit state is invalid.")
            run_budget = session.scalar(
                select(AcquisitionRunBudget)
                .where(AcquisitionRunBudget.id == permit.run_budget_id)
                .with_for_update()
            )
            if run_budget is None or run_budget.in_flight_count < 1:
                raise LiveSlotReconciliationError("Durable run budget is unavailable.")
            permit.status = "transport_failed"
            permit.consumed_at = consumed_at
            run_budget.in_flight_count -= 1
            run_budget.version += 1


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Reconciliation timestamps must include a timezone.")
    return value.astimezone(UTC)
