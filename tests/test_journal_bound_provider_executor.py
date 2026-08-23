from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from email.message import Message
from urllib.request import Request

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from pixiv_yuri.acquisition.auth import SessionCapability
from pixiv_yuri.acquisition.external_transport import ExternalSessionBroker
from pixiv_yuri.acquisition.first_request_slot import (
    FirstRequestClaim,
    FirstRequestSlotService,
)
from pixiv_yuri.acquisition.journal_bound_provider_executor import (
    JournalBoundPinnedMetadataExecutor,
    JournalBoundProviderExecutionError,
)
from pixiv_yuri.acquisition.live_execution_journal import LiveExecutionJournalService
from pixiv_yuri.acquisition.models import AcquisitionRequest, EntityType
from pixiv_yuri.acquisition.operator_session import RuntimeSession
from pixiv_yuri.acquisition.persistence_models import (
    AcquisitionLiveExecutionJournal,
    AcquisitionRequestPermit,
)
from pixiv_yuri.acquisition.persistent_safety import PersistentAcquisitionSafety
from pixiv_yuri.acquisition.providers.pinned_metadata import PinnedMetadataProvider
from pixiv_yuri.governance.g0 import G0Approval, approval_fingerprint
from pixiv_yuri.ingest.models import CrawlRun
from pixiv_yuri.shared.database import Base
from tests.test_g0_governance import valid_approval_payload

NOW = datetime(2026, 8, 23, tzinfo=UTC)
HOST = "metadata.pixiv.test"
REQUEST = AcquisitionRequest(entity_type=EntityType.WORK, source_id="42")


class PlanningOnlyTransport:
    transport_kind = "exact_https_dns"
    external_network_enabled = True

    def __init__(self, safety: PersistentAcquisitionSafety) -> None:
        self._safety = safety

    def validate_origin(self, origin: str) -> None:
        assert origin == f"https://{HOST}"

    def fetch(self, *args: object, **kwargs: object) -> object:
        raise AssertionError("the legacy transport path must never be used")

    def signal_schema_drift(self, *, now: datetime | None = None) -> None:
        self._safety.signal_schema_drift(now=now)


class FakeResponse:
    status = 200

    def __init__(self, body: bytes = b'{"work_id":"42","width":1000}') -> None:
        self._body = body
        self.headers = Message()
        self.headers.add_header("Content-Type", "application/json")

    def read(self, amount: int = -1) -> bytes:
        return self._body[:amount] if amount >= 0 else self._body

    def close(self) -> None:
        return

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


class FakeOpener:
    def __init__(self, body: bytes = b'{"work_id":"42","width":1000}') -> None:
        self.body = body
        self.requests: list[Request] = []

    def __call__(self, request: Request, timeout_seconds: float) -> FakeResponse:
        assert timeout_seconds == 2
        self.requests.append(request)
        return FakeResponse(self.body)


def build_state(
    *, body: bytes = b'{"work_id":"42","width":1000}'
) -> tuple[
    JournalBoundPinnedMetadataExecutor,
    PinnedMetadataProvider,
    FirstRequestClaim,
    sessionmaker[Session],
    FakeOpener,
]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        execution_options={"schema_translate_map": {"ingest": None}},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    approval = G0Approval.model_validate(valid_approval_payload())
    with factory.begin() as session:
        run = CrawlRun(
            run_type="journal_bound_provider_executor_test",
            provider="pinned_metadata_local_contract",
            status="running",
            config_snapshot={"transport": "fake_opener_only"},
            requested_by="test",
        )
        session.add(run)
        session.flush()
        run_id = run.id
    safety = PersistentAcquisitionSafety(factory, approval, run_id)
    safety.initialize(now=NOW)
    provider = PinnedMetadataProvider(
        f"https://{HOST}",
        (REQUEST,),
        PlanningOnlyTransport(safety),  # type: ignore[arg-type]
        approval,
        clock=lambda: NOW,
    )
    capability = SessionCapability(
        established_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=5),
        allowed_age_ratings=frozenset({"all_ages", "r18", "r18g"}),
    )
    runtime_session = RuntimeSession(
        bytearray(b"session=synthetic-final-chain"),
        capability.expires_at,
        established_at=capability.established_at,
        allowed_age_ratings=capability.allowed_age_ratings,
    )
    opener = FakeOpener(body)
    broker = ExternalSessionBroker(
        capability,
        runtime_session,
        allowed_hosts=frozenset({HOST}),
        open_request=opener,
    )
    binding = provider.plan_network_free_request(REQUEST).binding
    claim = FirstRequestSlotService(factory).claim(
        approval_fingerprint=approval_fingerprint(approval),
        run_id=run_id,
        request_key=binding.request_key,
        now=NOW,
    )
    executor = JournalBoundPinnedMetadataExecutor(
        safety=safety,
        journals=LiveExecutionJournalService(factory),
        broker=broker,
        session_factory=factory,
        runtime_session_lease=runtime_session.runtime_session_lease,
        timeout_seconds=2,
        estimated_cost=Decimal("0"),
        clock=lambda: NOW,
    )
    return executor, provider, claim, factory, opener


def test_final_chain_plans_sends_settles_then_parses_once() -> None:
    executor, provider, claim, factory, opener = build_state()
    binding = provider.plan_network_free_request(REQUEST).binding

    raw = executor.execute(
        provider=provider,
        request=REQUEST,
        claim=claim,
        binding=binding,
    )

    assert raw.json_value() == {"width": 1000, "work_id": "42"}
    assert len(opener.requests) == 1
    with factory() as session:
        permit = session.scalar(select(AcquisitionRequestPermit))
        journal = session.scalar(select(AcquisitionLiveExecutionJournal))
        assert permit is not None and permit.status == "consumed"
        assert journal is not None and journal.status == "completed"


def test_schema_drift_fails_journal_and_persists_stop_without_resend() -> None:
    executor, provider, claim, factory, opener = build_state(
        body=b'{"work_id":"42","not_approved":"discard"}'
    )
    binding = provider.plan_network_free_request(REQUEST).binding

    with pytest.raises(JournalBoundProviderExecutionError, match="did not complete"):
        executor.execute(
            provider=provider,
            request=REQUEST,
            claim=claim,
            binding=binding,
        )

    assert len(opener.requests) == 1
    with factory() as session:
        journal = session.scalar(select(AcquisitionLiveExecutionJournal))
        assert journal is not None and journal.status == "failed"
        assert journal.failure_code == "response_processing_failed"
