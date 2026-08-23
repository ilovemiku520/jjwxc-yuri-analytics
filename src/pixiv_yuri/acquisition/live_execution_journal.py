"""Transactional one-way journal for an exactly-once live send attempt."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from pixiv_yuri.acquisition.persistence_models import (
    AcquisitionFirstRequestSlot,
    AcquisitionLiveExecutionJournal,
    AcquisitionRequestPermit,
    AcquisitionRunBudget,
)

_SAFE_CODE = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")


class LiveExecutionState(StrEnum):
    """Monotonic journal states; terminal states never become sendable."""

    CLAIMED = "claimed"
    SEND_STARTED = "send_started"
    SETTLED = "settled"
    COMPLETED = "completed"
    FAILED = "failed"
    INDETERMINATE = "indeterminate"


class LiveExecutionJournalError(RuntimeError):
    """Base safe journal failure."""


class LiveExecutionBindingError(LiveExecutionJournalError):
    """A supplied durable identity does not match authoritative state."""


class LiveExecutionTransitionError(LiveExecutionJournalError):
    """A transition is invalid or would allow a resend."""


class LiveExecutionAlreadyClaimedError(LiveExecutionJournalError):
    """The permanent first-request slot already owns a journal."""


@dataclass(frozen=True, slots=True)
class LiveExecutionJournalRecord:
    """Payload-free journal state safe for orchestration and audit."""

    journal_id: int
    approval_fingerprint: str
    run_id: int
    slot_id: int
    request_binding_hash: str
    permit_id: str | None
    state: LiveExecutionState
    failure_code: str | None
    claimed_at: datetime
    send_started_at: datetime | None
    settled_at: datetime | None
    resolved_at: datetime | None
    version: int


class LiveExecutionJournalService:
    """Persist transitions before/after a send without performing any I/O."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def claim(
        self,
        *,
        approval_fingerprint: str,
        run_id: int,
        slot_id: int,
        request_binding_hash: str,
        now: datetime | None = None,
    ) -> LiveExecutionJournalRecord:
        """Create one journal bound to an existing permanent first-request slot."""
        fingerprint = _validate_hash(approval_fingerprint, "Approval fingerprint")
        binding_hash = _validate_hash(request_binding_hash, "Request binding hash")
        claimed_at = _aware_utc(now or datetime.now(UTC))
        if isinstance(run_id, bool) or not isinstance(run_id, int) or run_id < 1:
            raise ValueError("Run identifier must be positive.")
        if isinstance(slot_id, bool) or not isinstance(slot_id, int) or slot_id < 1:
            raise ValueError("Slot identifier must be positive.")
        try:
            with self._session_factory.begin() as session:
                slot = session.scalar(
                    select(AcquisitionFirstRequestSlot)
                    .where(AcquisitionFirstRequestSlot.id == slot_id)
                    .with_for_update()
                )
                if (
                    slot is None
                    or slot.approval_fingerprint != fingerprint
                    or slot.run_id != run_id
                    or slot.request_key_hash != binding_hash
                ):
                    raise LiveExecutionBindingError(
                        "Live execution slot binding does not match."
                    )
                if slot.status != "claimed":
                    raise LiveExecutionTransitionError(
                        "A terminal first-request slot cannot start execution."
                    )
                existing = session.scalar(
                    select(AcquisitionLiveExecutionJournal.id).where(
                        AcquisitionLiveExecutionJournal.slot_id == slot_id
                    )
                )
                if existing is not None:
                    raise LiveExecutionAlreadyClaimedError(
                        "The first-request slot already owns an execution journal."
                    )
                row = AcquisitionLiveExecutionJournal(
                    approval_fingerprint=fingerprint,
                    run_id=run_id,
                    slot_id=slot_id,
                    request_binding_hash=binding_hash,
                    status=LiveExecutionState.CLAIMED.value,
                    claimed_at=claimed_at,
                )
                session.add(row)
                session.flush()
                return _record(row)
        except IntegrityError:
            raise LiveExecutionAlreadyClaimedError(
                "The first-request slot already owns an execution journal."
            ) from None

    def start_send(
        self,
        journal_id: int,
        *,
        permit_id: str,
        now: datetime | None = None,
    ) -> LiveExecutionJournalRecord:
        """Bind an authorized permit and durably record send intent before I/O."""
        started_at = _aware_utc(now or datetime.now(UTC))
        _validate_identifier(journal_id, "Journal")
        _validate_permit_id(permit_id)
        with self._session_factory.begin() as session:
            row = _locked_journal(session, journal_id)
            _require_state(row, LiveExecutionState.CLAIMED)
            permit = session.scalar(
                select(AcquisitionRequestPermit).where(
                    AcquisitionRequestPermit.permit_id == permit_id
                )
            )
            if permit is None or permit.status != "authorized":
                raise LiveExecutionBindingError("An authorized request permit is required.")
            run_budget = session.get(AcquisitionRunBudget, permit.run_budget_id)
            if (
                run_budget is None
                or run_budget.run_id != row.run_id
                or permit.approval_fingerprint != row.approval_fingerprint
                or permit.request_key_hash != row.request_binding_hash
            ):
                raise LiveExecutionBindingError("Request permit binding does not match.")
            row.permit_id = permit_id
            row.status = LiveExecutionState.SEND_STARTED.value
            row.send_started_at = started_at
            row.version += 1
            session.flush()
            return _record(row)

    def settle(
        self,
        journal_id: int,
        *,
        permit_id: str,
        now: datetime | None = None,
    ) -> LiveExecutionJournalRecord:
        """Record a known response only after its permit is durably consumed."""
        settled_at = _aware_utc(now or datetime.now(UTC))
        _validate_identifier(journal_id, "Journal")
        _validate_permit_id(permit_id)
        with self._session_factory.begin() as session:
            row = _locked_journal(session, journal_id)
            _require_state(row, LiveExecutionState.SEND_STARTED)
            if row.permit_id != permit_id:
                raise LiveExecutionBindingError("Request permit binding does not match.")
            permit = session.scalar(
                select(AcquisitionRequestPermit).where(
                    AcquisitionRequestPermit.permit_id == permit_id
                )
            )
            if permit is None or permit.status != "consumed":
                raise LiveExecutionTransitionError(
                    "Only a consumed permit with a known response can settle."
                )
            row.status = LiveExecutionState.SETTLED.value
            row.settled_at = settled_at
            row.version += 1
            session.flush()
            return _record(row)

    def complete(
        self, journal_id: int, *, now: datetime | None = None
    ) -> LiveExecutionJournalRecord:
        """Resolve a settled send as completed without allowing another send."""
        return self._resolve(
            journal_id,
            LiveExecutionState.COMPLETED,
            failure_code=None,
            now=now,
        )

    def fail(
        self,
        journal_id: int,
        *,
        failure_code: str,
        now: datetime | None = None,
    ) -> LiveExecutionJournalRecord:
        """Fail before send or after settlement; send-started failures are unknown."""
        code = _validate_failure_code(failure_code)
        return self._resolve(
            journal_id,
            LiveExecutionState.FAILED,
            failure_code=code,
            now=now,
        )

    def mark_indeterminate(
        self,
        journal_id: int,
        *,
        failure_code: str = "unknown_external_effect",
        now: datetime | None = None,
    ) -> LiveExecutionJournalRecord:
        """Terminalize an exception after send start; recovery must never resend."""
        resolved_at = _aware_utc(now or datetime.now(UTC))
        code = _validate_failure_code(failure_code)
        _validate_identifier(journal_id, "Journal")
        with self._session_factory.begin() as session:
            row = _locked_journal(session, journal_id)
            _require_state(row, LiveExecutionState.SEND_STARTED)
            row.status = LiveExecutionState.INDETERMINATE.value
            row.failure_code = code
            row.resolved_at = resolved_at
            row.version += 1
            session.flush()
            return _record(row)

    def recover_without_resend(
        self, journal_id: int, *, now: datetime | None = None
    ) -> LiveExecutionJournalRecord:
        """Conservatively terminalize every unfinished state after restart."""
        resolved_at = _aware_utc(now or datetime.now(UTC))
        _validate_identifier(journal_id, "Journal")
        with self._session_factory.begin() as session:
            row = _locked_journal(session, journal_id)
            state = LiveExecutionState(row.status)
            if state in {
                LiveExecutionState.COMPLETED,
                LiveExecutionState.FAILED,
                LiveExecutionState.INDETERMINATE,
            }:
                return _record(row)
            if state == LiveExecutionState.SEND_STARTED:
                row.status = LiveExecutionState.INDETERMINATE.value
                row.failure_code = "recovery_unknown_external_effect"
            else:
                row.status = LiveExecutionState.FAILED.value
                row.failure_code = (
                    "recovery_before_send"
                    if state == LiveExecutionState.CLAIMED
                    else "recovery_after_settlement"
                )
            row.resolved_at = resolved_at
            row.version += 1
            session.flush()
            return _record(row)

    def get(self, journal_id: int) -> LiveExecutionJournalRecord:
        """Return safe journal evidence without changing state."""
        _validate_identifier(journal_id, "Journal")
        with self._session_factory() as session:
            row = session.get(AcquisitionLiveExecutionJournal, journal_id)
            if row is None:
                raise LiveExecutionJournalError("Live execution journal does not exist.")
            return _record(row)

    def _resolve(
        self,
        journal_id: int,
        target: LiveExecutionState,
        *,
        failure_code: str | None,
        now: datetime | None,
    ) -> LiveExecutionJournalRecord:
        resolved_at = _aware_utc(now or datetime.now(UTC))
        _validate_identifier(journal_id, "Journal")
        with self._session_factory.begin() as session:
            row = _locked_journal(session, journal_id)
            state = LiveExecutionState(row.status)
            allowed = (
                state == LiveExecutionState.SETTLED
                if target == LiveExecutionState.COMPLETED
                else state in {LiveExecutionState.CLAIMED, LiveExecutionState.SETTLED}
            )
            if not allowed:
                raise LiveExecutionTransitionError(
                    "Live execution state cannot transition to the requested terminal state."
                )
            row.status = target.value
            row.failure_code = failure_code
            row.resolved_at = resolved_at
            row.version += 1
            session.flush()
            return _record(row)


def _locked_journal(session: Session, journal_id: int) -> AcquisitionLiveExecutionJournal:
    row = session.scalar(
        select(AcquisitionLiveExecutionJournal)
        .where(AcquisitionLiveExecutionJournal.id == journal_id)
        .with_for_update()
    )
    if row is None:
        raise LiveExecutionJournalError("Live execution journal does not exist.")
    return row


def _require_state(
    row: AcquisitionLiveExecutionJournal, expected: LiveExecutionState
) -> None:
    if row.status != expected.value:
        raise LiveExecutionTransitionError(
            "Live execution state is terminal or out of sequence."
        )


def _record(row: AcquisitionLiveExecutionJournal) -> LiveExecutionJournalRecord:
    if row.id is None:
        raise LiveExecutionJournalError("Live execution journal has no database identity.")
    return LiveExecutionJournalRecord(
        journal_id=row.id,
        approval_fingerprint=row.approval_fingerprint,
        run_id=row.run_id,
        slot_id=row.slot_id,
        request_binding_hash=row.request_binding_hash,
        permit_id=row.permit_id,
        state=LiveExecutionState(row.status),
        failure_code=row.failure_code,
        claimed_at=_database_utc(row.claimed_at),
        send_started_at=(
            _database_utc(row.send_started_at) if row.send_started_at is not None else None
        ),
        settled_at=(
            _database_utc(row.settled_at) if row.settled_at is not None else None
        ),
        resolved_at=(
            _database_utc(row.resolved_at) if row.resolved_at is not None else None
        ),
        version=row.version,
    )


def _validate_hash(value: str, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError(f"{label} must be a 64-character SHA-256 value.")
    try:
        bytes.fromhex(value)
    except ValueError:
        raise ValueError(f"{label} must be hexadecimal.") from None
    if value != value.lower():
        raise ValueError(f"{label} must use lowercase hexadecimal.")
    return value


def _validate_failure_code(value: str) -> str:
    if not isinstance(value, str) or _SAFE_CODE.fullmatch(value) is None:
        raise ValueError("Failure code must be safe lowercase identifier text.")
    return value


def _validate_identifier(value: int, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{label} identifier must be positive.")


def _validate_permit_id(value: str) -> None:
    if not isinstance(value, str) or not 1 <= len(value) <= 36:
        raise ValueError("Permit identifier is invalid.")


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Live execution journal timestamps must include a timezone.")
    return value.astimezone(UTC)


def _database_utc(value: datetime) -> datetime:
    """Normalize UTC values returned without tzinfo by SQLite test databases."""
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
