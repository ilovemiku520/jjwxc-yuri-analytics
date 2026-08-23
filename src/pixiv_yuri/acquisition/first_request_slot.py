"""Atomic, permanent first-request claim per G0 approval fingerprint."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from pixiv_yuri.acquisition.persistence_models import (
    AcquisitionFirstRequestSlot,
    AcquisitionRunBudget,
)


class FirstRequestSlotError(RuntimeError):
    """Fail-closed first-request slot error without logical key disclosure."""


class FirstRequestAlreadyClaimedError(FirstRequestSlotError):
    """Raised when an approval has already spent its first-request attempt."""


class FirstRequestSlotBindingError(FirstRequestSlotError):
    """Raised when a transition does not match the durable claim binding."""


@dataclass(frozen=True, slots=True)
class FirstRequestClaim:
    """Non-secret identity required to resolve one durable claim."""

    slot_id: int
    approval_fingerprint: str
    run_id: int
    request_key_hash: str
    claimed_at: datetime


class FirstRequestSlotService:
    """Claim once across runs and processes; terminal states never release the slot."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def claim(
        self,
        *,
        approval_fingerprint: str,
        run_id: int,
        request_key: str,
        now: datetime | None = None,
    ) -> FirstRequestClaim:
        """Atomically spend the approval's only first-request slot."""
        fingerprint = _validate_fingerprint(approval_fingerprint)
        request_key_hash = _hash_request_key(request_key)
        claimed_at = _aware_utc(now or datetime.now(UTC))
        try:
            with self._session_factory.begin() as session:
                _lock_approval_transaction(session, fingerprint)
                _require_bound_run(session, run_id, fingerprint)
                existing = session.scalar(
                    select(AcquisitionFirstRequestSlot.id)
                    .where(
                        AcquisitionFirstRequestSlot.approval_fingerprint == fingerprint
                    )
                    .with_for_update()
                )
                if existing is not None:
                    raise FirstRequestAlreadyClaimedError(
                        "This G0 approval already spent its first-request slot."
                    )
                row = AcquisitionFirstRequestSlot(
                    approval_fingerprint=fingerprint,
                    run_id=run_id,
                    request_key_hash=request_key_hash,
                    status="claimed",
                    claimed_at=claimed_at,
                )
                session.add(row)
                session.flush()
                if row.id is None:
                    raise FirstRequestSlotError("First-request slot has no database identity.")
                return FirstRequestClaim(
                    slot_id=row.id,
                    approval_fingerprint=fingerprint,
                    run_id=run_id,
                    request_key_hash=request_key_hash,
                    claimed_at=claimed_at,
                )
        except IntegrityError:
            raise FirstRequestAlreadyClaimedError(
                "This G0 approval already spent its first-request slot."
            ) from None

    def complete(
        self, claim: FirstRequestClaim, *, now: datetime | None = None
    ) -> None:
        """Mark a claimed attempt completed without making it reusable."""
        self._resolve(claim, "completed", now=now)

    def fail(self, claim: FirstRequestClaim, *, now: datetime | None = None) -> None:
        """Mark a claimed attempt failed without releasing or refunding it."""
        self._resolve(claim, "failed", now=now)

    def _resolve(
        self,
        claim: FirstRequestClaim,
        status: str,
        *,
        now: datetime | None,
    ) -> None:
        resolved_at = _aware_utc(now or datetime.now(UTC))
        fingerprint = _validate_fingerprint(claim.approval_fingerprint)
        with self._session_factory.begin() as session:
            _lock_approval_transaction(session, fingerprint)
            row = session.scalar(
                select(AcquisitionFirstRequestSlot)
                .where(AcquisitionFirstRequestSlot.id == claim.slot_id)
                .with_for_update()
            )
            if (
                row is None
                or row.approval_fingerprint != fingerprint
                or row.run_id != claim.run_id
                or row.request_key_hash != claim.request_key_hash
            ):
                raise FirstRequestSlotBindingError(
                    "First-request claim does not match its durable slot."
                )
            if row.status != "claimed":
                raise FirstRequestSlotBindingError(
                    "First-request slot is already in a terminal state."
                )
            row.status = status
            row.resolved_at = resolved_at


def _require_bound_run(session: Session, run_id: int, fingerprint: str) -> None:
    bound_run = session.scalar(
        select(AcquisitionRunBudget.id)
        .where(
            AcquisitionRunBudget.run_id == run_id,
            AcquisitionRunBudget.approval_fingerprint == fingerprint,
        )
        .with_for_update()
    )
    if bound_run is None:
        raise FirstRequestSlotBindingError(
            "Crawl run is not initialized for this G0 approval."
        )


def _validate_fingerprint(value: str) -> str:
    if len(value) != 64:
        raise ValueError("Approval fingerprint must be a 64-character SHA-256 value.")
    try:
        bytes.fromhex(value)
    except ValueError:
        raise ValueError("Approval fingerprint must be hexadecimal.") from None
    return value.lower()


def _hash_request_key(request_key: str) -> str:
    if not request_key or len(request_key) > 2048:
        raise ValueError("Logical request key must contain between 1 and 2048 characters.")
    try:
        encoded = request_key.encode("utf-8")
    except UnicodeError:
        raise ValueError("Logical request key must be valid UTF-8 text.") from None
    return sha256(encoded).hexdigest()


def _lock_approval_transaction(session: Session, fingerprint: str) -> None:
    """Serialize claim and transition decisions for one approval in PostgreSQL."""
    if session.get_bind().dialect.name != "postgresql":
        return
    lock_key = int.from_bytes(bytes.fromhex(fingerprint[:16]), "big", signed=True)
    session.execute(
        text("SELECT pg_advisory_xact_lock(:lock_key)"),
        {"lock_key": lock_key},
    )


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("First-request slot timestamps must include a timezone.")
    return value.astimezone(UTC)
