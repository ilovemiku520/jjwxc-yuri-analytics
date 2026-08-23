"""Read-only, payload-free operator report for durable live-attempt state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from pixiv_yuri.acquisition.persistence_models import (
    AcquisitionFirstRequestSlot,
    AcquisitionLiveExecutionJournal,
)

_UNRESOLVED_JOURNAL_STATES = ("claimed", "send_started", "settled")


@dataclass(frozen=True, slots=True)
class UnresolvedLiveAttempt:
    journal_id: int
    run_id: int
    slot_id: int
    state: str
    claimed_at: str
    send_started_at: str | None
    settled_at: str | None


@dataclass(frozen=True, slots=True)
class OrphanClaimedSlot:
    slot_id: int
    run_id: int
    claimed_at: str


@dataclass(frozen=True, slots=True)
class LiveAttemptOperatorReport:
    generated_at: str
    journal_counts: dict[str, int]
    slot_counts: dict[str, int]
    unresolved_attempts: tuple[UnresolvedLiveAttempt, ...]
    orphan_claimed_slots: tuple[OrphanClaimedSlot, ...]
    truncated: bool
    read_only: bool
    authorizes_live_request: bool
    network_send_confirmed: None


def build_live_attempt_operator_report(
    session_factory: sessionmaker[Session],
    *,
    now: datetime | None = None,
    limit: int = 100,
) -> LiveAttemptOperatorReport:
    """Inspect state without locks, mutations, credentials, request hashes, or URLs."""
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
        raise ValueError("Live-attempt report limit must be between 1 and 1000.")
    generated_at = _aware_utc(now or datetime.now(UTC))
    with session_factory() as session:
        journal_counts = {
            state: count
            for state, count in session.execute(
                select(
                    AcquisitionLiveExecutionJournal.status,
                    func.count(AcquisitionLiveExecutionJournal.id),
                ).group_by(AcquisitionLiveExecutionJournal.status)
            )
        }
        slot_counts = {
            state: count
            for state, count in session.execute(
                select(
                    AcquisitionFirstRequestSlot.status,
                    func.count(AcquisitionFirstRequestSlot.id),
                ).group_by(AcquisitionFirstRequestSlot.status)
            )
        }
        unresolved_rows = session.scalars(
            select(AcquisitionLiveExecutionJournal)
            .where(
                AcquisitionLiveExecutionJournal.status.in_(_UNRESOLVED_JOURNAL_STATES)
            )
            .order_by(AcquisitionLiveExecutionJournal.id)
            .limit(limit + 1)
        ).all()
        orphan_rows = session.execute(
            select(AcquisitionFirstRequestSlot)
            .outerjoin(
                AcquisitionLiveExecutionJournal,
                AcquisitionLiveExecutionJournal.slot_id
                == AcquisitionFirstRequestSlot.id,
            )
            .where(
                AcquisitionFirstRequestSlot.status == "claimed",
                AcquisitionLiveExecutionJournal.id.is_(None),
            )
            .order_by(AcquisitionFirstRequestSlot.id)
            .limit(limit + 1)
        ).scalars().all()
    truncated = len(unresolved_rows) > limit or len(orphan_rows) > limit
    return LiveAttemptOperatorReport(
        generated_at=generated_at.isoformat(),
        journal_counts=journal_counts,
        slot_counts=slot_counts,
        unresolved_attempts=tuple(
            UnresolvedLiveAttempt(
                journal_id=row.id,
                run_id=row.run_id,
                slot_id=row.slot_id,
                state=row.status,
                claimed_at=_database_utc(row.claimed_at).isoformat(),
                send_started_at=_optional_iso(row.send_started_at),
                settled_at=_optional_iso(row.settled_at),
            )
            for row in unresolved_rows[:limit]
        ),
        orphan_claimed_slots=tuple(
            OrphanClaimedSlot(
                slot_id=row.id,
                run_id=row.run_id,
                claimed_at=_database_utc(row.claimed_at).isoformat(),
            )
            for row in orphan_rows[:limit]
        ),
        truncated=truncated,
        read_only=True,
        authorizes_live_request=False,
        network_send_confirmed=None,
    )


def _optional_iso(value: datetime | None) -> str | None:
    return _database_utc(value).isoformat() if value is not None else None


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Live-attempt report timestamps must include a timezone.")
    return value.astimezone(UTC)


def _database_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
