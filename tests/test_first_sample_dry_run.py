from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from email.message import Message
from urllib.request import Request

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from pixiv_yuri.acquisition.auth import SessionCapability
from pixiv_yuri.acquisition.external_transport import (
    ExternalSessionBroker,
    PermitGuardedExternalTransport,
)
from pixiv_yuri.acquisition.first_request_slot import FirstRequestSlotService
from pixiv_yuri.acquisition.models import AcquisitionRequest, EntityType
from pixiv_yuri.acquisition.persistence_models import (
    AcquisitionFirstRequestSlot,
    AcquisitionRequestPermit,
    AcquisitionRunBudget,
)
from pixiv_yuri.acquisition.persistent_safety import PersistentAcquisitionSafety
from pixiv_yuri.acquisition.providers.pinned_metadata import PinnedMetadataProvider
from pixiv_yuri.governance.first_sample_dry_run import (
    FirstSampleDryRunResult,
    run_first_sample_dry_run,
)
from pixiv_yuri.governance.g0 import G0Approval
from pixiv_yuri.ingest.models import CrawlRun
from pixiv_yuri.shared.database import Base
from tests.test_g0_governance import valid_approval_payload

NOW = datetime(2026, 8, 23, tzinfo=UTC)
HOST = "metadata.pixiv.test"
PHRASE = "CONFIRM-ONE-001122AABBCC"


class FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.status = 200
        self.headers = Message()
        self.headers.add_header("Content-Type", "application/json")
        self._body = json.dumps(payload).encode()

    def read(self, amount: int = -1) -> bytes:
        return self._body[:amount] if amount >= 0 else self._body

    def close(self) -> None:
        return

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


class FakeOpener:
    def __init__(self, payload: dict[str, object]) -> None:
        self._response = FakeResponse(payload)
        self.requests: list[Request] = []

    def __call__(self, request: Request, _timeout: float) -> FakeResponse:
        self.requests.append(request)
        return self._response


def build_dry_run(
    payload: dict[str, object],
    *,
    real_opener: bool = False,
) -> tuple[
    PinnedMetadataProvider,
    G0Approval,
    FirstRequestSlotService,
    sessionmaker[Session],
    int,
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
            run_type="first_sample_dry_run",
            provider="pinned_metadata_local_contract",
            status="running",
            config_snapshot={"external_network": False},
            requested_by="test",
        )
        session.add(run)
        session.flush()
        run_id = run.id
    safety = PersistentAcquisitionSafety(factory, approval, run_id)
    safety.initialize(now=NOW)
    capability = SessionCapability(
        established_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=5),
        allowed_age_ratings=frozenset({"all_ages", "r18", "r18g"}),
    )
    opener = FakeOpener(payload)
    broker = ExternalSessionBroker(
        capability,
        lambda: "session=synthetic-offline-only",
        allowed_hosts=frozenset({HOST}),
        open_request=None if real_opener else opener,
    )
    transport = PermitGuardedExternalTransport(safety, broker, clock=lambda: NOW)
    request = AcquisitionRequest(entity_type=EntityType.WORK, source_id="42")
    provider = PinnedMetadataProvider(
        f"https://{HOST}",
        (request,),
        transport,
        approval,
        clock=lambda: NOW,
    )
    return provider, approval, FirstRequestSlotService(factory), factory, run_id, opener


def run_confirmed(
    provider: PinnedMetadataProvider,
    approval: G0Approval,
    slot_service: FirstRequestSlotService,
    run_id: int,
) -> FirstSampleDryRunResult:
    return run_first_sample_dry_run(
        provider,
        approval,
        slot_service,
        run_id=run_id,
        ttl_seconds=60,
        reader=lambda prompt: PHRASE if PHRASE in prompt else "",
        phrase_factory=lambda: PHRASE,
        now=lambda: NOW,
    )


def test_fake_external_sample_confirms_claims_and_fetches_exactly_once() -> None:
    provider, approval, slots, factory, run_id, opener = build_dry_run(
        {"work_id": "42", "work_title": "Synthetic approved sample", "width": 1000}
    )

    result = run_confirmed(provider, approval, slots, run_id)

    assert result.status == "passed"
    assert result.slot_status == "completed"
    assert result.attempted_requests == result.completed_requests == 1
    assert result.external_network_used is False
    assert len(opener.requests) == 1
    with factory() as session:
        permit = session.scalar(select(AcquisitionRequestPermit))
        slot = session.scalar(select(AcquisitionFirstRequestSlot))
        assert permit is not None and permit.status == "consumed"
        assert slot is not None and slot.status == "completed"


def test_real_external_opener_is_blocked_before_confirmation_or_permit() -> None:
    provider, approval, slots, factory, run_id, _ = build_dry_run(
        {"work_id": "42"}, real_opener=True
    )
    reader_called = False

    def reader(_prompt: str) -> str:
        nonlocal reader_called
        reader_called = True
        return PHRASE

    result = run_first_sample_dry_run(
        provider,
        approval,
        slots,
        run_id=run_id,
        ttl_seconds=60,
        reader=reader,
        phrase_factory=lambda: PHRASE,
        now=lambda: NOW,
    )

    assert result.violations == ("external_network_not_allowed",)
    assert reader_called is False
    with factory() as session:
        assert session.scalar(select(AcquisitionRequestPermit)) is None
        assert session.scalar(select(AcquisitionFirstRequestSlot)) is None


def test_schema_drift_fails_slot_and_stops_run_without_retry() -> None:
    provider, approval, slots, factory, run_id, opener = build_dry_run(
        {"work_id": "42", "unapproved": "blocked"}
    )

    result = run_confirmed(provider, approval, slots, run_id)

    assert result.status == "blocked"
    assert result.slot_status == "failed"
    assert len(opener.requests) == 1
    with factory() as session:
        slot = session.scalar(select(AcquisitionFirstRequestSlot))
        budget = session.scalar(select(AcquisitionRunBudget))
        assert slot is not None and slot.status == "failed"
        assert budget is not None and budget.stop_reason == "schema_drift"


def test_spent_slot_blocks_second_attempt_before_fetch() -> None:
    provider, approval, slots, factory, run_id, opener = build_dry_run({"work_id": "42"})
    first = run_confirmed(provider, approval, slots, run_id)
    second = run_confirmed(provider, approval, slots, run_id)

    assert first.status == "passed"
    assert second.violations == ("first_request_slot_already_spent",)
    assert len(opener.requests) == 1
    with factory() as session:
        assert len(session.scalars(select(AcquisitionRequestPermit)).all()) == 1
