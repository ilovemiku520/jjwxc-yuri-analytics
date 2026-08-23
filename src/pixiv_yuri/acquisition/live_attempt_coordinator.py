"""Internal journal-bound coordinator for one injected live send attempt."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from typing import Protocol

from pixiv_yuri.acquisition.first_request_slot import FirstRequestClaim
from pixiv_yuri.acquisition.live_execution_journal import (
    LiveExecutionAlreadyClaimedError,
    LiveExecutionJournalError,
    LiveExecutionJournalRecord,
    LiveExecutionJournalService,
    LiveExecutionState,
)
from pixiv_yuri.acquisition.live_request_binding import CanonicalLiveRequestBinding
from pixiv_yuri.acquisition.persistent_safety import (
    PersistentAcquisitionSafety,
    PersistentRequestPermit,
)


class JournalBoundAttemptError(RuntimeError):
    """Safe coordinator rejection without request or transport details."""


@dataclass(frozen=True, slots=True)
class JournalBoundSendContext:
    """Non-secret proof that permit and durable send intent already exist."""

    journal_id: int
    permit_id: str
    request_binding_hash: str
    send_started_at: datetime


@dataclass(frozen=True, slots=True)
class InjectedTransportResponse:
    """Bounded sanitized response processed only after durable settlement."""

    status_code: int
    content_type: str = "application/octet-stream"
    body: bytes = b""
    headers: Mapping[str, str] = field(default_factory=dict)


class SettledResponseProcessor(Protocol):
    """Process a known settled response before the journal becomes terminal."""

    def process(self, response: InjectedTransportResponse) -> None: ...


class InjectedOneShotSender(Protocol):
    """Testable transport port called exactly once after durable send intent."""

    def send(self, context: JournalBoundSendContext) -> InjectedTransportResponse: ...


@dataclass(frozen=True, slots=True)
class JournalBoundAttemptResult:
    """Payload-free lifecycle evidence safe for internal orchestration."""

    journal_id: int
    permit_id: str | None
    state: LiveExecutionState
    response_status: int | None
    source_transport_attempted: bool
    network_send_confirmed: None
    failure_code: str | None


class JournalBoundLiveAttemptCoordinator:
    """Bind journal, permit, send intent, response settlement, and terminal state.

    The class has no endpoint or CLI registration and imports no network client.
    Its sender is injected; production integration must provide a separately
    capability-guarded one-shot sender.
    """

    def __init__(
        self,
        safety: PersistentAcquisitionSafety,
        journals: LiveExecutionJournalService,
        sender: InjectedOneShotSender,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._safety = safety
        self._journals = journals
        self._sender = sender
        self._clock = clock or (lambda: datetime.now(UTC))

    def execute(
        self,
        claim: FirstRequestClaim,
        *,
        request_key: str,
        estimated_cost: Decimal = Decimal("0"),
        response_processor: SettledResponseProcessor | None = None,
    ) -> JournalBoundAttemptResult:
        """Execute at most one injected send and terminalize every started journal."""
        binding_hash = _hash_request_key(request_key)
        if binding_hash != claim.request_key_hash:
            raise JournalBoundAttemptError("Request binding does not match the durable slot.")

        try:
            journal = self._journals.claim(
                approval_fingerprint=claim.approval_fingerprint,
                run_id=claim.run_id,
                slot_id=claim.slot_id,
                request_binding_hash=binding_hash,
                now=self._now(),
            )
        except LiveExecutionAlreadyClaimedError:
            raise JournalBoundAttemptError(
                "The live attempt journal already exists; resend is forbidden."
            ) from None
        except LiveExecutionJournalError:
            raise JournalBoundAttemptError("The live attempt journal is unavailable.") from None

        try:
            permit = self._safety.authorize_and_start_live_send(
                journal_id=journal.journal_id,
                request_key=request_key,
                estimated_cost=estimated_cost,
                now=self._now(),
            )
        except Exception:
            failed = self._journals.fail(
                journal.journal_id,
                failure_code="permit_authorization_failed",
                now=self._now(),
            )
            return _result(failed, None, None, attempted=False)

        if (
            permit.approval_fingerprint != claim.approval_fingerprint
            or permit.request_key_hash != binding_hash
        ):
            self._consume_failed_permit(permit)
            failed = self._terminalize_before_send(journal.journal_id)
            return _result(failed, permit, None, attempted=False)

        started = self._journals.get(journal.journal_id)
        if (
            started.state != LiveExecutionState.SEND_STARTED
            or started.permit_id != permit.permit_id
        ):
            self._consume_failed_permit(permit)
            failed = self._terminalize_before_send(journal.journal_id)
            return _result(failed, permit, None, attempted=False)

        assert started.send_started_at is not None
        context = JournalBoundSendContext(
            journal_id=started.journal_id,
            permit_id=permit.permit_id,
            request_binding_hash=binding_hash,
            send_started_at=started.send_started_at,
        )
        try:
            response = self._sender.send(context)
            _validate_response_status(response.status_code)
        except Exception:
            self._consume_failed_permit(permit)
            unknown = self._mark_indeterminate(started.journal_id, "transport_result_unknown")
            return _result(unknown, permit, None, attempted=True)

        try:
            self._safety.record_response(
                permit.permit_id,
                response.status_code,
                now=self._now(),
            )
        except Exception:
            unknown = self._mark_indeterminate(
                started.journal_id,
                "permit_settlement_unknown",
            )
            return _result(unknown, permit, response.status_code, attempted=True)

        try:
            settled = self._journals.settle(
                started.journal_id,
                permit_id=permit.permit_id,
                now=self._now(),
            )
        except LiveExecutionJournalError:
            unknown = self._mark_indeterminate(
                started.journal_id,
                "journal_settlement_failed",
            )
            return _result(unknown, permit, response.status_code, attempted=True)

        try:
            if not 200 <= response.status_code < 300:
                terminal = self._journals.fail(
                    settled.journal_id,
                    failure_code="non_success_response",
                    now=self._now(),
                )
            elif response_processor is None:
                terminal = self._journals.complete(settled.journal_id, now=self._now())
            else:
                try:
                    response_processor.process(response)
                except Exception:
                    terminal = self._journals.fail(
                        settled.journal_id,
                        failure_code="response_processing_failed",
                        now=self._now(),
                    )
                else:
                    terminal = self._journals.complete(
                        settled.journal_id, now=self._now()
                    )
        except LiveExecutionJournalError:
            terminal = self._journals.recover_without_resend(
                settled.journal_id,
                now=self._now(),
            )
        return _result(terminal, permit, response.status_code, attempted=True)

    def execute_binding(
        self,
        claim: FirstRequestClaim,
        *,
        binding: CanonicalLiveRequestBinding,
        estimated_cost: Decimal = Decimal("0"),
        response_processor: SettledResponseProcessor | None = None,
    ) -> JournalBoundAttemptResult:
        """Use the canonical endpoint-aware identity for all durable hashes."""
        if binding.approval_fingerprint != claim.approval_fingerprint:
            raise JournalBoundAttemptError(
                "Request binding does not match the durable approval."
            )
        return self.execute(
            claim,
            request_key=binding.request_key,
            estimated_cost=estimated_cost,
            response_processor=response_processor,
        )

    def _now(self) -> datetime:
        return _aware_utc(self._clock())

    def _consume_failed_permit(self, permit: PersistentRequestPermit) -> None:
        try:
            self._safety.record_transport_failure(permit.permit_id, now=self._now())
        except Exception:
            return

    def _terminalize_before_send(self, journal_id: int) -> LiveExecutionJournalRecord:
        current = self._journals.get(journal_id)
        if current.state == LiveExecutionState.CLAIMED:
            return self._journals.fail(
                journal_id,
                failure_code="send_start_failed",
                now=self._now(),
            )
        if current.state == LiveExecutionState.SEND_STARTED:
            return self._mark_indeterminate(journal_id, "send_start_commit_unknown")
        return self._journals.recover_without_resend(journal_id, now=self._now())

    def _mark_indeterminate(
        self, journal_id: int, failure_code: str
    ) -> LiveExecutionJournalRecord:
        try:
            return self._journals.mark_indeterminate(
                journal_id,
                failure_code=failure_code,
                now=self._now(),
            )
        except LiveExecutionJournalError:
            return self._journals.recover_without_resend(journal_id, now=self._now())


def _result(
    journal: LiveExecutionJournalRecord,
    permit: PersistentRequestPermit | None,
    response_status: int | None,
    *,
    attempted: bool,
) -> JournalBoundAttemptResult:
    return JournalBoundAttemptResult(
        journal_id=journal.journal_id,
        permit_id=permit.permit_id if permit is not None else None,
        state=journal.state,
        response_status=response_status,
        source_transport_attempted=attempted,
        network_send_confirmed=None,
        failure_code=journal.failure_code,
    )


def _hash_request_key(request_key: str) -> str:
    if not isinstance(request_key, str) or not request_key or len(request_key) > 2048:
        raise ValueError("Logical request key must contain between 1 and 2048 characters.")
    try:
        encoded = request_key.encode("utf-8")
    except UnicodeError:
        raise ValueError("Logical request key must be valid UTF-8 text.") from None
    return sha256(encoded).hexdigest()


def _validate_response_status(status_code: int) -> None:
    if isinstance(status_code, bool) or not isinstance(status_code, int):
        raise ValueError("Injected response status is invalid.")
    if not 100 <= status_code <= 599:
        raise ValueError("Injected response status is invalid.")


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Journal-bound attempt timestamps must include a timezone.")
    return value.astimezone(UTC)
