"""Transactional PostgreSQL-backed acquisition permits and circuit breakers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from uuid import uuid4

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from pixiv_yuri.acquisition.persistence_models import (
    AcquisitionDailyBudget,
    AcquisitionFirstRequestSlot,
    AcquisitionLiveExecutionJournal,
    AcquisitionRequestPermit,
    AcquisitionRunBudget,
    AcquisitionStopEvent,
)
from pixiv_yuri.acquisition.safety import (
    AcquisitionDeferredError,
    AcquisitionStoppedError,
    DuplicateRequestPermitError,
    StopReason,
)
from pixiv_yuri.governance.g0 import G0Approval, approval_fingerprint
from pixiv_yuri.ingest.models import CrawlRun


@dataclass(frozen=True, slots=True)
class PersistentRequestPermit:
    """Non-secret durable permit identity returned after a committed reservation."""

    permit_id: str
    sequence: int
    request_key_hash: str
    approval_fingerprint: str
    authorized_at: datetime
    estimated_cost: Decimal


@dataclass(frozen=True, slots=True)
class _AuthorizationDecision:
    permit: PersistentRequestPermit | None
    stopped_reason: StopReason | None
    deferred_message: str | None


class PersistentAcquisitionSafety:
    """Own short transactions that reserve and consume transport permits."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        approval: G0Approval,
        run_id: int,
    ) -> None:
        self._session_factory = session_factory
        self._approval = approval
        self._fingerprint = approval_fingerprint(approval)
        self._run_id = run_id

    def initialize(self, *, now: datetime | None = None) -> None:
        """Bind a crawl run to this approval before any worker can reserve permits."""
        checked_at = _aware_utc(now or datetime.now(UTC))
        _ensure_approval_active(self._approval, checked_at)
        with self._session_factory.begin() as session:
            run = session.get(CrawlRun, self._run_id)
            if run is None:
                raise ValueError(f"Unknown crawl run: {self._run_id}")
            run_budget = _locked_run_budget(session, self._run_id)
            if run_budget is None:
                session.add(
                    AcquisitionRunBudget(
                        run_id=self._run_id,
                        approval_fingerprint=self._fingerprint,
                    )
                )
            elif run_budget.approval_fingerprint != self._fingerprint:
                raise ValueError("Crawl run is bound to a different G0 approval.")
            _locked_daily_budget(session, self._fingerprint, checked_at.date(), create=True)

    def authorize_request(
        self,
        *,
        request_key: str,
        now: datetime | None = None,
        estimated_cost: Decimal = Decimal("0"),
    ) -> PersistentRequestPermit:
        """Atomically enforce scope limits and commit a one-use permit."""
        checked_at = _aware_utc(now or datetime.now(UTC))
        request_key_hash = _hash_request_key(request_key)
        if estimated_cost < 0:
            raise ValueError("Estimated request cost cannot be negative.")

        with self._session_factory.begin() as session:
            decision = self._reserve_request_in_session(
                session,
                request_key_hash=request_key_hash,
                checked_at=checked_at,
                estimated_cost=estimated_cost,
            )
        return _finish_authorization(decision)

    def authorize_and_start_live_send(
        self,
        *,
        journal_id: int,
        request_key: str,
        now: datetime | None = None,
        estimated_cost: Decimal = Decimal("0"),
    ) -> PersistentRequestPermit:
        """Atomically reserve a permit and commit matching durable send intent."""
        checked_at = _aware_utc(now or datetime.now(UTC))
        request_key_hash = _hash_request_key(request_key)
        if estimated_cost < 0:
            raise ValueError("Estimated request cost cannot be negative.")
        if isinstance(journal_id, bool) or not isinstance(journal_id, int) or journal_id < 1:
            raise ValueError("Live execution journal identifier must be positive.")

        with self._session_factory.begin() as session:
            decision = self._reserve_request_in_session(
                session,
                request_key_hash=request_key_hash,
                checked_at=checked_at,
                estimated_cost=estimated_cost,
            )
            if decision.permit is not None:
                session.flush()
                journal = session.scalar(
                    select(AcquisitionLiveExecutionJournal)
                    .where(AcquisitionLiveExecutionJournal.id == journal_id)
                    .with_for_update()
                )
                if (
                    journal is None
                    or journal.status != "claimed"
                    or journal.approval_fingerprint != self._fingerprint
                    or journal.run_id != self._run_id
                    or journal.request_binding_hash != request_key_hash
                ):
                    raise ValueError("Live execution journal binding does not match.")
                slot = session.scalar(
                    select(AcquisitionFirstRequestSlot)
                    .where(AcquisitionFirstRequestSlot.id == journal.slot_id)
                    .with_for_update()
                )
                if (
                    slot is None
                    or slot.status != "claimed"
                    or slot.approval_fingerprint != self._fingerprint
                    or slot.run_id != self._run_id
                    or slot.request_key_hash != request_key_hash
                ):
                    raise ValueError("First-request slot binding does not match.")
                journal.permit_id = decision.permit.permit_id
                journal.status = "send_started"
                journal.send_started_at = checked_at
                journal.version += 1
                session.flush()
        return _finish_authorization(decision)

    def _reserve_request_in_session(
        self,
        session: Session,
        *,
        request_key_hash: str,
        checked_at: datetime,
        estimated_cost: Decimal,
    ) -> _AuthorizationDecision:
        """Single in-transaction kernel shared by normal and live authorization."""
        _lock_approval_transaction(session, self._fingerprint)
        run_budget = _require_run_budget(session, self._run_id, self._fingerprint)
        daily = _locked_daily_budget(
            session, self._fingerprint, checked_at.date(), create=True
        )
        assert daily is not None
        permit: PersistentRequestPermit | None = None
        stopped_reason: StopReason | None = None
        deferred_message: str | None = None

        duplicate = session.scalar(
            select(AcquisitionRequestPermit.id).where(
                AcquisitionRequestPermit.run_budget_id == run_budget.id,
                AcquisitionRequestPermit.request_key_hash == request_key_hash,
            )
        )
        if duplicate is not None:
            raise DuplicateRequestPermitError(
                "Logical request already has a persistent permit in this run."
            )
        if run_budget.stop_reason is not None:
            stopped_reason = StopReason(run_budget.stop_reason)
        elif not _approval_is_active(self._approval, checked_at):
            stopped_reason = StopReason.APPROVAL_INACTIVE
        else:
            traffic = self._approval.traffic_limits
            cost = self._approval.cost_limits
            global_in_flight = int(
                session.scalar(
                    select(func.coalesce(func.sum(AcquisitionRunBudget.in_flight_count), 0))
                    .where(
                        AcquisitionRunBudget.approval_fingerprint == self._fingerprint
                    )
                )
                or 0
            )
            minute_count = int(
                session.scalar(
                    select(func.count())
                    .select_from(AcquisitionRequestPermit)
                    .where(
                        AcquisitionRequestPermit.approval_fingerprint == self._fingerprint,
                        AcquisitionRequestPermit.authorized_at
                        > checked_at - timedelta(minutes=1),
                    )
                )
                or 0
            )
            projected_daily = daily.estimated_cost + estimated_cost
            projected_monthly = (
                _monthly_estimated_cost(session, self._fingerprint, checked_at.date())
                + estimated_cost
            )
            if global_in_flight >= traffic.concurrency:
                deferred_message = "Approved concurrency limit reached."
            elif minute_count >= traffic.requests_per_minute:
                deferred_message = "Approved requests-per-minute limit reached."
            elif run_budget.request_count >= traffic.per_run_request_cap:
                stopped_reason = StopReason.PER_RUN_REQUEST_CAP
            elif daily.request_count >= traffic.daily_request_cap:
                stopped_reason = StopReason.DAILY_REQUEST_CAP
            elif projected_daily > Decimal(str(cost.daily_cap)):
                stopped_reason = StopReason.DAILY_COST_CAP
            elif projected_monthly > Decimal(str(cost.monthly_cap)):
                stopped_reason = StopReason.MONTHLY_COST_CAP
            else:
                sequence = run_budget.request_count + 1
                permit_row = AcquisitionRequestPermit(
                    permit_id=str(uuid4()),
                    run_budget_id=run_budget.id,
                    sequence=sequence,
                    request_key_hash=request_key_hash,
                    approval_fingerprint=self._fingerprint,
                    estimated_cost=estimated_cost,
                    status="authorized",
                    authorized_at=checked_at,
                )
                run_budget.request_count = sequence
                run_budget.in_flight_count += 1
                run_budget.version += 1
                daily.request_count += 1
                daily.estimated_cost = projected_daily
                daily.version += 1
                session.add(permit_row)
                permit = PersistentRequestPermit(
                    permit_id=permit_row.permit_id,
                    sequence=sequence,
                    request_key_hash=request_key_hash,
                    approval_fingerprint=self._fingerprint,
                    authorized_at=checked_at,
                    estimated_cost=estimated_cost,
                )
        if stopped_reason is not None and run_budget.stop_reason is None:
            _record_stop(
                session,
                run_budget,
                stopped_reason,
                checked_at,
                trigger_source=_trigger_source(stopped_reason),
            )
        return _AuthorizationDecision(permit, stopped_reason, deferred_message)

    def record_response(
        self,
        permit_id: str,
        status_code: int,
        *,
        now: datetime | None = None,
    ) -> None:
        """Consume one permit and persist consecutive 403/429 breaker state."""
        if not 100 <= status_code <= 599:
            raise ValueError("Response status must be between 100 and 599.")
        consumed_at = _aware_utc(now or datetime.now(UTC))
        with self._session_factory.begin() as session:
            permit, run_budget = self._locked_permit_and_run(session, permit_id)
            permit.status = "consumed"
            permit.consumed_at = consumed_at
            permit.response_status = status_code
            run_budget.in_flight_count -= 1
            run_budget.version += 1

            stop_reason: StopReason | None = None
            if status_code == 403:
                run_budget.consecutive_403 += 1
                run_budget.consecutive_429 = 0
                if run_budget.consecutive_403 >= 2:
                    stop_reason = StopReason.REPEATED_403
            elif status_code == 429:
                run_budget.consecutive_429 += 1
                run_budget.consecutive_403 = 0
                if run_budget.consecutive_429 >= 2:
                    stop_reason = StopReason.REPEATED_429
            else:
                run_budget.consecutive_403 = 0
                run_budget.consecutive_429 = 0
            if stop_reason is not None and run_budget.stop_reason is None:
                _record_stop(
                    session, run_budget, stop_reason, consumed_at, trigger_source="response"
                )

    def record_transport_failure(
        self, permit_id: str, *, now: datetime | None = None
    ) -> None:
        """Consume a failed permit without refunding its request or cost reservation."""
        consumed_at = _aware_utc(now or datetime.now(UTC))
        with self._session_factory.begin() as session:
            permit, run_budget = self._locked_permit_and_run(session, permit_id)
            permit.status = "transport_failed"
            permit.consumed_at = consumed_at
            run_budget.in_flight_count -= 1
            run_budget.version += 1

    def stop_manually(self, *, now: datetime | None = None) -> None:
        """Commit the operator kill switch and append one stop event."""
        stopped_at = _aware_utc(now or datetime.now(UTC))
        with self._session_factory.begin() as session:
            run_budget = _require_run_budget(session, self._run_id, self._fingerprint)
            if run_budget.stop_reason is None:
                _record_stop(
                    session,
                    run_budget,
                    StopReason.MANUAL,
                    stopped_at,
                    trigger_source="operator",
                )

    def signal_schema_drift(self, *, now: datetime | None = None) -> None:
        """Commit a Schema Drift stop before unapproved metadata can propagate."""
        stopped_at = _aware_utc(now or datetime.now(UTC))
        with self._session_factory.begin() as session:
            run_budget = _require_run_budget(session, self._run_id, self._fingerprint)
            if run_budget.stop_reason is None:
                _record_stop(
                    session,
                    run_budget,
                    StopReason.SCHEMA_DRIFT,
                    stopped_at,
                    trigger_source="schema",
                )

    def _locked_permit_and_run(
        self, session: Session, permit_id: str
    ) -> tuple[AcquisitionRequestPermit, AcquisitionRunBudget]:
        permit = session.scalar(
            select(AcquisitionRequestPermit)
            .where(AcquisitionRequestPermit.permit_id == permit_id)
            .with_for_update()
        )
        if permit is None or permit.approval_fingerprint != self._fingerprint:
            raise ValueError("Request permit is unknown or belongs to another approval.")
        if permit.status != "authorized":
            raise ValueError("Request permit was already consumed.")
        run_budget = session.scalar(
            select(AcquisitionRunBudget)
            .where(AcquisitionRunBudget.id == permit.run_budget_id)
            .with_for_update()
        )
        if run_budget is None or run_budget.run_id != self._run_id:
            raise ValueError("Request permit belongs to another crawl run.")
        if run_budget.in_flight_count < 1:
            raise ValueError("Persistent in-flight state is inconsistent.")
        return permit, run_budget


def _finish_authorization(
    decision: _AuthorizationDecision,
) -> PersistentRequestPermit:
    if decision.stopped_reason is not None:
        raise AcquisitionStoppedError(decision.stopped_reason)
    if decision.deferred_message is not None:
        raise AcquisitionDeferredError(decision.deferred_message)
    assert decision.permit is not None
    return decision.permit


def _locked_run_budget(session: Session, run_id: int) -> AcquisitionRunBudget | None:
    return session.scalar(
        select(AcquisitionRunBudget)
        .where(AcquisitionRunBudget.run_id == run_id)
        .with_for_update()
    )


def _require_run_budget(
    session: Session, run_id: int, fingerprint: str
) -> AcquisitionRunBudget:
    run_budget = _locked_run_budget(session, run_id)
    if run_budget is None:
        raise ValueError("Persistent safety state has not been initialized.")
    if run_budget.approval_fingerprint != fingerprint:
        raise ValueError("Crawl run is bound to a different G0 approval.")
    return run_budget


def _locked_daily_budget(
    session: Session,
    fingerprint: str,
    budget_day: date,
    *,
    create: bool,
) -> AcquisitionDailyBudget | None:
    daily = session.scalar(
        select(AcquisitionDailyBudget)
        .where(
            AcquisitionDailyBudget.approval_fingerprint == fingerprint,
            AcquisitionDailyBudget.budget_day == budget_day,
        )
        .with_for_update()
    )
    if daily is None and create:
        daily = AcquisitionDailyBudget(
            approval_fingerprint=fingerprint,
            budget_day=budget_day,
        )
        session.add(daily)
        session.flush()
    return daily


def _monthly_estimated_cost(session: Session, fingerprint: str, budget_day: date) -> Decimal:
    month_start = budget_day.replace(day=1)
    next_month = (
        month_start.replace(year=month_start.year + 1, month=1)
        if month_start.month == 12
        else month_start.replace(month=month_start.month + 1)
    )
    value = session.scalar(
        select(func.coalesce(func.sum(AcquisitionDailyBudget.estimated_cost), 0)).where(
            AcquisitionDailyBudget.approval_fingerprint == fingerprint,
            AcquisitionDailyBudget.budget_day >= month_start,
            AcquisitionDailyBudget.budget_day < next_month,
        )
    )
    return Decimal(str(value or 0))


def _record_stop(
    session: Session,
    run_budget: AcquisitionRunBudget,
    reason: StopReason,
    occurred_at: datetime,
    *,
    trigger_source: str,
) -> None:
    run_budget.stop_reason = reason.value
    run_budget.version += 1
    session.add(
        AcquisitionStopEvent(
            approval_fingerprint=run_budget.approval_fingerprint,
            run_id=run_budget.run_id,
            reason=reason.value,
            trigger_source=trigger_source,
            occurred_at=occurred_at,
        )
    )


def _trigger_source(reason: StopReason) -> str:
    if reason == StopReason.APPROVAL_INACTIVE:
        return "approval"
    if reason in {
        StopReason.PER_RUN_REQUEST_CAP,
        StopReason.DAILY_REQUEST_CAP,
        StopReason.DAILY_COST_CAP,
        StopReason.MONTHLY_COST_CAP,
    }:
        return "budget"
    return "system"


def _approval_is_active(approval: G0Approval, checked_at: datetime) -> bool:
    return approval.approved_at <= checked_at < approval.expires_at


def _ensure_approval_active(approval: G0Approval, checked_at: datetime) -> None:
    if not _approval_is_active(approval, checked_at):
        raise AcquisitionStoppedError(StopReason.APPROVAL_INACTIVE)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Persistent-safety timestamps must include a timezone.")
    return value.astimezone(UTC)


def _hash_request_key(request_key: str) -> str:
    if not request_key or len(request_key) > 2048:
        raise ValueError("Logical request key must contain between 1 and 2048 characters.")
    return sha256(request_key.encode("utf-8")).hexdigest()


def _lock_approval_transaction(session: Session, fingerprint: str) -> None:
    """Serialize PostgreSQL authorization decisions for one G0 fingerprint."""
    if session.get_bind().dialect.name != "postgresql":
        return
    lock_key = int.from_bytes(bytes.fromhex(fingerprint[:16]), "big", signed=True)
    session.execute(
        text("SELECT pg_advisory_xact_lock(:lock_key)"),
        {"lock_key": lock_key},
    )
