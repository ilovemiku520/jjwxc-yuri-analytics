"""One-shot external sender gated by an already-durable live send marker.

This module deliberately owns no permit authorization and has no CLI or API
registration.  It only verifies state prepared by the journal coordinator and
then delegates one bounded request to an injected :class:`ExternalSessionBroker`.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from pixiv_yuri.acquisition.external_transport import (
    ExternalSessionBroker,
    ExternalTransportError,
)
from pixiv_yuri.acquisition.live_request_binding import CanonicalLiveRequestBinding
from pixiv_yuri.acquisition.persistence_models import (
    AcquisitionFirstRequestSlot,
    AcquisitionLiveExecutionJournal,
    AcquisitionRequestPermit,
    AcquisitionRunBudget,
)
from pixiv_yuri.acquisition.runtime_session_lease import (
    RuntimeSessionLease,
    require_same_runtime_session_lease,
)


class DurableExternalSenderError(RuntimeError):
    """Safe rejection without URL, credential, body, header, or database details."""


@dataclass(frozen=True, slots=True)
class DurableMarkerSendContext:
    """Minimum non-secret durable identities required immediately before a send."""

    journal_id: int
    permit_id: str
    request_binding_hash: str
    send_started_at: datetime


@dataclass(frozen=True, slots=True)
class DurableExternalSenderResponse:
    """Sanitized broker response returned without performing permit settlement."""

    status_code: int
    content_type: str
    body: bytes
    headers: Mapping[str, str]


class DurableMarkerExternalSender:
    """Burn once, verify the durable marker, then delegate to the bound broker."""

    __slots__ = (
        "_binding",
        "_broker",
        "_clock",
        "_consumed",
        "_lock",
        "_runtime_session_lease",
        "_session_factory",
        "_timeout_seconds",
    )

    def __init__(
        self,
        binding: CanonicalLiveRequestBinding,
        broker: ExternalSessionBroker,
        session_factory: sessionmaker[Session],
        *,
        runtime_session_lease: RuntimeSessionLease,
        timeout_seconds: float,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not 0 < timeout_seconds <= 30:
            raise ValueError("External sender timeout must be between 0 and 30 seconds.")
        broker_lease = broker.runtime_session_lease
        if broker_lease is None:
            raise DurableExternalSenderError(
                "External sender requires a runtime-session broker."
            )
        try:
            require_same_runtime_session_lease(runtime_session_lease, broker_lease)
            broker.validate_origin(binding.canonical_url)
        except Exception:
            raise DurableExternalSenderError(
                "External sender binding is unavailable."
            ) from None
        self._binding = binding
        self._broker = broker
        self._session_factory = session_factory
        self._runtime_session_lease = runtime_session_lease
        self._timeout_seconds = timeout_seconds
        self._clock = clock or (lambda: datetime.now(UTC))
        self._consumed = False
        self._lock = threading.Lock()

    @property
    def consumed(self) -> bool:
        """Return a concurrency-safe process-local use-state snapshot."""
        with self._lock:
            return self._consumed

    def send(
        self,
        context: DurableMarkerSendContext,
    ) -> DurableExternalSenderResponse:
        """Burn before validation, verify a committed marker, and delegate once."""
        self._burn()
        try:
            checked_at = _aware_utc(self._clock())
            broker_lease = self._broker.runtime_session_lease
            if broker_lease is None:
                raise DurableExternalSenderError(
                    "External sender runtime lease is unavailable."
                )
            require_same_runtime_session_lease(
                self._runtime_session_lease,
                broker_lease,
            )
            self._runtime_session_lease.ensure_active(now=checked_at)
            self._verify_durable_marker(context)
        except DurableExternalSenderError:
            raise
        except Exception:
            raise DurableExternalSenderError(
                "External sender durable authorization is unavailable."
            ) from None

        try:
            response = self._broker.fetch(
                self._binding.canonical_url,
                timeout_seconds=self._timeout_seconds,
                clock=self._clock,
            )
        except ExternalTransportError:
            raise DurableExternalSenderError("External sender transport failed.") from None
        except Exception:
            raise DurableExternalSenderError("External sender transport failed.") from None
        return DurableExternalSenderResponse(
            status_code=response.status_code,
            content_type=response.content_type,
            body=response.body,
            headers=response.headers,
        )

    def _burn(self) -> None:
        with self._lock:
            if self._consumed:
                raise DurableExternalSenderError("External sender is unavailable.")
            self._consumed = True

    def _verify_durable_marker(self, context: DurableMarkerSendContext) -> None:
        _validate_context(context)
        binding_hash = self._binding.binding_hash
        if context.request_binding_hash != binding_hash:
            raise DurableExternalSenderError(
                "External sender durable binding does not match."
            )

        with self._session_factory.begin() as session:
            journal = session.scalar(
                select(AcquisitionLiveExecutionJournal)
                .where(AcquisitionLiveExecutionJournal.id == context.journal_id)
                .with_for_update()
            )
            permit = session.scalar(
                select(AcquisitionRequestPermit)
                .where(AcquisitionRequestPermit.permit_id == context.permit_id)
                .with_for_update()
            )
            if journal is None or permit is None:
                raise DurableExternalSenderError(
                    "External sender durable marker is unavailable."
                )
            slot = session.scalar(
                select(AcquisitionFirstRequestSlot)
                .where(AcquisitionFirstRequestSlot.id == journal.slot_id)
                .with_for_update()
            )
            run_budget = session.scalar(
                select(AcquisitionRunBudget)
                .where(AcquisitionRunBudget.id == permit.run_budget_id)
                .with_for_update()
            )
            if not _durable_bindings_match(
                context,
                self._binding,
                journal,
                permit,
                slot,
                run_budget,
            ):
                raise DurableExternalSenderError(
                    "External sender durable binding does not match."
                )

    def __repr__(self) -> str:
        return (
            "DurableMarkerExternalSender(binding=[HASHED], broker=[REDACTED], "
            f"consumed={self.consumed})"
        )


def _durable_bindings_match(
    context: DurableMarkerSendContext,
    binding: CanonicalLiveRequestBinding,
    journal: AcquisitionLiveExecutionJournal,
    permit: AcquisitionRequestPermit,
    slot: AcquisitionFirstRequestSlot | None,
    run_budget: AcquisitionRunBudget | None,
) -> bool:
    if slot is None or run_budget is None:
        return False
    binding_hash = binding.binding_hash
    return (
        journal.status == "send_started"
        and journal.permit_id == context.permit_id == permit.permit_id
        and journal.request_binding_hash == context.request_binding_hash == binding_hash
        and journal.approval_fingerprint
        == permit.approval_fingerprint
        == slot.approval_fingerprint
        == run_budget.approval_fingerprint
        == binding.approval_fingerprint
        and journal.run_id == slot.run_id == run_budget.run_id
        and journal.slot_id == slot.id
        and slot.status == "claimed"
        and slot.request_key_hash == binding_hash
        and permit.status == "authorized"
        and permit.request_key_hash == binding_hash
        and _same_timestamp(journal.send_started_at, context.send_started_at)
    )


def _validate_context(context: DurableMarkerSendContext) -> None:
    if (
        isinstance(context.journal_id, bool)
        or not isinstance(context.journal_id, int)
        or context.journal_id < 1
        or not isinstance(context.permit_id, str)
        or not 1 <= len(context.permit_id) <= 36
        or not isinstance(context.request_binding_hash, str)
        or len(context.request_binding_hash) != 64
    ):
        raise DurableExternalSenderError("External sender context is invalid.")
    try:
        bytes.fromhex(context.request_binding_hash)
        _aware_utc(context.send_started_at)
    except (TypeError, ValueError):
        raise DurableExternalSenderError("External sender context is invalid.") from None


def _same_timestamp(left: datetime | None, right: datetime) -> bool:
    if left is None:
        return False
    try:
        return _aware_utc(left) == _aware_utc(right)
    except ValueError:
        # SQLite loses timezone information; its stored value is UTC in tests.
        if left.tzinfo is None and right.tzinfo is not None:
            return left.replace(tzinfo=UTC) == right.astimezone(UTC)
        return False


def _aware_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("External sender timestamps must include a timezone.")
    return value.astimezone(UTC)
