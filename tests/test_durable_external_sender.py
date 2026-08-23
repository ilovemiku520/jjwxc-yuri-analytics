from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from email.message import Message
from threading import Barrier, Lock
from urllib.request import Request

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from pixiv_yuri.acquisition.auth import SessionCapability
from pixiv_yuri.acquisition.durable_external_sender import (
    DurableExternalSenderError,
    DurableMarkerExternalSender,
    DurableMarkerSendContext,
)
from pixiv_yuri.acquisition.external_transport import ExternalSessionBroker
from pixiv_yuri.acquisition.live_request_binding import CanonicalLiveRequestBinding
from pixiv_yuri.acquisition.models import AcquisitionRequest, EntityType
from pixiv_yuri.acquisition.operator_session import RuntimeSession
from pixiv_yuri.acquisition.persistence_models import (
    AcquisitionFirstRequestSlot,
    AcquisitionLiveExecutionJournal,
    AcquisitionRequestPermit,
    AcquisitionRunBudget,
)
from pixiv_yuri.acquisition.runtime_session_lease import (
    RuntimeSessionLease,
    RuntimeSessionLeaseState,
)
from pixiv_yuri.governance.g0 import G0Approval, approval_fingerprint
from pixiv_yuri.ingest.models import CrawlRun
from pixiv_yuri.shared.database import Base
from tests.test_g0_governance import valid_approval_payload

NOW = datetime(2026, 8, 23, tzinfo=UTC)
HOST = "metadata.pixiv.test"
COOKIE = "session=durable-sender-synthetic"
PERMIT_ID = "11111111-1111-1111-1111-111111111111"


class FakeResponse:
    def __init__(self) -> None:
        self.status = 200
        self.headers = Message()
        self.headers.add_header("Content-Type", "application/json")
        self._body = b'{"work_id":"42"}'
        self.closed = False

    def read(self, amount: int = -1) -> bytes:
        return self._body[:amount] if amount >= 0 else self._body

    def close(self) -> None:
        self.closed = True

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


class FakeOpener:
    def __init__(self) -> None:
        self.requests: list[Request] = []
        self._lock = Lock()

    def __call__(self, request: Request, timeout_seconds: float) -> FakeResponse:
        del timeout_seconds
        with self._lock:
            self.requests.append(request)
        return FakeResponse()


def build_state(
    *,
    expires_at: datetime = NOW + timedelta(minutes=5),
) -> tuple[
    DurableMarkerExternalSender,
    DurableMarkerSendContext,
    sessionmaker[Session],
    FakeOpener,
    RuntimeSession,
    CanonicalLiveRequestBinding,
]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        execution_options={"schema_translate_map": {"ingest": None}},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    approval = G0Approval.model_validate(valid_approval_payload())
    fingerprint = approval_fingerprint(approval)
    binding = CanonicalLiveRequestBinding.from_request(
        approval_fingerprint=fingerprint,
        provider_id="pinned_metadata_local_contract",
        request=AcquisitionRequest(entity_type=EntityType.WORK, source_id="42"),
        exact_url=f"https://{HOST}/works/42",
    )
    with factory.begin() as session:
        run = CrawlRun(
            run_type="durable_external_sender_test",
            provider="pinned_metadata_local_contract",
            status="running",
            config_snapshot={"transport": "fake_opener_only"},
            requested_by="test",
        )
        session.add(run)
        session.flush()
        budget = AcquisitionRunBudget(
            run_id=run.id,
            approval_fingerprint=fingerprint,
            request_count=1,
            in_flight_count=1,
        )
        session.add(budget)
        session.flush()
        slot = AcquisitionFirstRequestSlot(
            approval_fingerprint=fingerprint,
            run_id=run.id,
            request_key_hash=binding.binding_hash,
            status="claimed",
            claimed_at=NOW,
        )
        session.add(slot)
        session.flush()
        permit = AcquisitionRequestPermit(
            permit_id=PERMIT_ID,
            run_budget_id=budget.id,
            sequence=1,
            request_key_hash=binding.binding_hash,
            approval_fingerprint=fingerprint,
            estimated_cost=0,
            status="authorized",
            authorized_at=NOW,
        )
        session.add(permit)
        session.flush()
        journal = AcquisitionLiveExecutionJournal(
            approval_fingerprint=fingerprint,
            run_id=run.id,
            slot_id=slot.id,
            request_binding_hash=binding.binding_hash,
            permit_id=PERMIT_ID,
            status="send_started",
            claimed_at=NOW - timedelta(seconds=1),
            send_started_at=NOW,
        )
        session.add(journal)
        session.flush()
        journal_id = journal.id
    assert journal_id is not None

    capability = SessionCapability(
        established_at=NOW - timedelta(minutes=1),
        expires_at=expires_at,
        allowed_age_ratings=frozenset({"all_ages", "r18", "r18g"}),
    )
    runtime_session = RuntimeSession(
        bytearray(COOKIE.encode()),
        expires_at,
        established_at=capability.established_at,
        allowed_age_ratings=capability.allowed_age_ratings,
    )
    opener = FakeOpener()
    broker = ExternalSessionBroker(
        capability,
        runtime_session,
        allowed_hosts=frozenset({HOST}),
        open_request=opener,
    )
    sender = DurableMarkerExternalSender(
        binding,
        broker,
        factory,
        runtime_session_lease=runtime_session.runtime_session_lease,
        timeout_seconds=2,
        clock=lambda: NOW,
    )
    context = DurableMarkerSendContext(
        journal_id=journal_id,
        permit_id=PERMIT_ID,
        request_binding_hash=binding.binding_hash,
        send_started_at=NOW,
    )
    return sender, context, factory, opener, runtime_session, binding


def test_success_verifies_marker_and_delegates_once_without_settling_permit() -> None:
    sender, context, factory, opener, runtime_session, _binding = build_state()

    response = sender.send(context)

    assert response.status_code == 200
    assert response.body == b'{"work_id":"42"}'
    assert sender.consumed is True
    assert runtime_session.runtime_session_lease.state == RuntimeSessionLeaseState.CONSUMED
    assert len(opener.requests) == 1
    assert opener.requests[0].get_header("Cookie") == COOKIE
    with factory() as session:
        permit = session.scalar(select(AcquisitionRequestPermit))
        assert permit is not None and permit.status == "authorized"

    with pytest.raises(DurableExternalSenderError, match="unavailable"):
        sender.send(context)
    assert len(opener.requests) == 1


def test_forged_context_burns_sender_before_validation() -> None:
    sender, context, _factory, opener, runtime_session, _binding = build_state()
    forged = replace(context, request_binding_hash="f" * 64)

    with pytest.raises(DurableExternalSenderError, match="binding"):
        sender.send(forged)

    assert sender.consumed is True
    assert runtime_session.runtime_session_lease.state == RuntimeSessionLeaseState.ACTIVE
    with pytest.raises(DurableExternalSenderError, match="unavailable"):
        sender.send(context)
    assert opener.requests == []


@pytest.mark.parametrize(
    "tamper",
    ["permit_status", "slot_terminal", "journal_hash", "run_fingerprint"],
)
def test_database_tampering_is_rejected_before_lease_or_broker(
    tamper: str,
) -> None:
    sender, context, factory, opener, runtime_session, _binding = build_state()
    with factory.begin() as session:
        permit = session.scalar(select(AcquisitionRequestPermit))
        journal = session.scalar(select(AcquisitionLiveExecutionJournal))
        slot = session.scalar(select(AcquisitionFirstRequestSlot))
        budget = session.scalar(select(AcquisitionRunBudget))
        assert permit is not None and journal is not None
        assert slot is not None and budget is not None
        if tamper == "permit_status":
            permit.status = "cancelled"
        elif tamper == "slot_terminal":
            slot.status = "failed"
            slot.resolved_at = NOW
        elif tamper == "journal_hash":
            journal.request_binding_hash = "e" * 64
        else:
            budget.approval_fingerprint = "d" * 64

    with pytest.raises(DurableExternalSenderError, match="binding"):
        sender.send(context)

    assert runtime_session.runtime_session_lease.state == RuntimeSessionLeaseState.ACTIVE
    assert opener.requests == []


def test_constructor_rejects_a_different_runtime_lease_identity() -> None:
    sender, _context, factory, opener, runtime_session, binding = build_state()
    del sender
    other_lease = RuntimeSessionLease(
        established_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=5),
        allowed_age_ratings=frozenset({"all_ages", "r18", "r18g"}),
    )
    capability = SessionCapability(
        established_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=5),
        allowed_age_ratings=frozenset({"all_ages", "r18", "r18g"}),
    )
    broker = ExternalSessionBroker(
        capability,
        runtime_session,
        allowed_hosts=frozenset({HOST}),
        open_request=opener,
    )

    with pytest.raises(DurableExternalSenderError, match="binding"):
        DurableMarkerExternalSender(
            binding,
            broker,
            factory,
            runtime_session_lease=other_lease,
            timeout_seconds=2,
            clock=lambda: NOW,
        )
    assert opener.requests == []


def test_expired_lease_burns_sender_without_touching_broker() -> None:
    sender, context, _factory, opener, runtime_session, _binding = build_state(
        expires_at=NOW + timedelta(seconds=1)
    )
    sender._clock = lambda: NOW + timedelta(seconds=2)

    with pytest.raises(DurableExternalSenderError, match="authorization"):
        sender.send(context)

    assert sender.consumed is True
    assert runtime_session.runtime_session_lease.state == RuntimeSessionLeaseState.BURNED
    assert opener.requests == []


def test_process_lock_allows_only_one_concurrent_fake_send() -> None:
    sender, context, _factory, opener, _runtime_session, _binding = build_state()
    barrier = Barrier(2)

    def attempt() -> str:
        barrier.wait()
        try:
            sender.send(context)
        except DurableExternalSenderError:
            return "blocked"
        return "sent"

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = (executor.submit(attempt), executor.submit(attempt))
        outcomes = [future.result() for future in futures]

    assert sorted(outcomes) == ["blocked", "sent"]
    assert len(opener.requests) == 1
