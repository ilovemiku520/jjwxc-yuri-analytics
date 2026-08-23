from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from hashlib import sha256

import pytest
from sqlalchemy import select

from pixiv_yuri.acquisition.base import AcquisitionProvider
from pixiv_yuri.acquisition.first_request_slot import (
    FirstRequestAlreadyClaimedError,
    FirstRequestClaim,
    FirstRequestSlotService,
)
from pixiv_yuri.acquisition.models import AcquisitionRequest, EntityType, RawResponse
from pixiv_yuri.acquisition.persistence_models import (
    AcquisitionFirstRequestSlot,
    AcquisitionRequestPermit,
    AcquisitionRunBudget,
)
from pixiv_yuri.governance.first_sample_dry_run import (
    FirstSampleDryRunResult,
    run_first_sample_dry_run,
)
from pixiv_yuri.governance.g0 import G0Approval, approval_fingerprint
from tests.test_first_sample_dry_run import (
    PHRASE,
    FakeResponse,
    build_dry_run,
    run_confirmed,
)
from tests.test_g0_governance import valid_approval_payload

NOW = datetime(2026, 8, 23, tzinfo=UTC)


class ExplodingResponse(FakeResponse):
    def read(self, amount: int = -1) -> bytes:
        raise OSError("synthetic provider detail must not escape")


class ApprovalMismatchProvider(AcquisitionProvider):
    def __init__(self, delegate: AcquisitionProvider) -> None:
        self._delegate = delegate

    @property
    def name(self) -> str:
        return self._delegate.name

    @property
    def external_network_enabled(self) -> bool:
        return False

    @property
    def approval_fingerprint(self) -> str:
        return "f" * 64

    def list_requests(
        self, entity_type: EntityType | None = None
    ) -> tuple[AcquisitionRequest, ...]:
        return self._delegate.list_requests(entity_type)

    def fetch(self, request: AcquisitionRequest) -> RawResponse:
        return self._delegate.fetch(request)


class SyntheticBoundProvider(AcquisitionProvider):
    def __init__(self, fingerprint: str) -> None:
        self._fingerprint = fingerprint
        self._request = AcquisitionRequest(entity_type=EntityType.WORK, source_id="race")
        self._lock = threading.Lock()
        self.fetch_count = 0

    @property
    def name(self) -> str:
        return "synthetic_bound_provider"

    @property
    def approval_fingerprint(self) -> str:
        return self._fingerprint

    def list_requests(
        self, entity_type: EntityType | None = None
    ) -> tuple[AcquisitionRequest, ...]:
        return (self._request,) if entity_type in {None, EntityType.WORK} else ()

    def fetch(self, request: AcquisitionRequest) -> RawResponse:
        with self._lock:
            self.fetch_count += 1
        return RawResponse(
            provider=self.name,
            entity_type=request.entity_type,
            source_id=request.source_id,
            observed_at=NOW,
            status_code=200,
            content_type="application/json",
            body=b'{"work_id":"race"}',
        )


class SyntheticPermanentSlot:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._claimed = False
        self.status = "unclaimed"

    def claim(
        self,
        *,
        approval_fingerprint: str,
        run_id: int,
        request_key: str,
        now: datetime,
    ) -> FirstRequestClaim:
        with self._lock:
            if self._claimed:
                raise FirstRequestAlreadyClaimedError("Synthetic slot is permanently spent.")
            self._claimed = True
            self.status = "claimed"
        return FirstRequestClaim(
            slot_id=1,
            approval_fingerprint=approval_fingerprint,
            run_id=run_id,
            request_key_hash=sha256(request_key.encode()).hexdigest(),
            claimed_at=now,
        )

    def complete(self, _claim: FirstRequestClaim, *, now: datetime) -> None:
        del now
        with self._lock:
            self.status = "completed"

    def fail(self, _claim: FirstRequestClaim, *, now: datetime) -> None:
        del now
        with self._lock:
            self.status = "failed"


def test_confirmation_failure_creates_no_slot_permit_or_provider_call() -> None:
    provider, approval, slots, factory, run_id, opener = build_dry_run({"work_id": "42"})

    result = run_first_sample_dry_run(
        provider,
        approval,
        slots,
        run_id=run_id,
        ttl_seconds=60,
        reader=lambda _: "wrong-phrase",
        phrase_factory=lambda: PHRASE,
        now=lambda: NOW,
    )

    assert result.violations == ("confirmation_not_eligible",)
    assert result.confirmation_status == "blocked"
    assert opener.requests == []
    with factory() as session:
        assert session.scalar(select(AcquisitionFirstRequestSlot)) is None
        assert session.scalar(select(AcquisitionRequestPermit)) is None


def test_confirmation_expiry_blocks_before_claim_and_fetch() -> None:
    provider, approval, slots, factory, run_id, opener = build_dry_run({"work_id": "42"})
    times = iter((NOW, NOW + timedelta(seconds=5)))

    result = run_first_sample_dry_run(
        provider,
        approval,
        slots,
        run_id=run_id,
        ttl_seconds=5,
        reader=lambda _: PHRASE,
        phrase_factory=lambda: PHRASE,
        now=lambda: next(times),
    )

    assert result.violations == ("confirmation_not_eligible",)
    assert opener.requests == []
    with factory() as session:
        assert session.scalar(select(AcquisitionFirstRequestSlot)) is None
        assert session.scalar(select(AcquisitionRequestPermit)) is None


def test_existing_claim_conflict_blocks_before_provider_and_permit() -> None:
    provider, approval, slots, factory, run_id, opener = build_dry_run({"work_id": "42"})
    slots.claim(
        approval_fingerprint=approval_fingerprint(approval),
        run_id=run_id,
        request_key="synthetic-prior-claim",
        now=NOW,
    )

    result = run_confirmed(provider, approval, slots, run_id)

    assert result.violations == ("first_request_slot_already_spent",)
    assert opener.requests == []
    with factory() as session:
        assert session.scalar(select(AcquisitionRequestPermit)) is None


def test_provider_approval_binding_mismatch_stops_before_confirmation() -> None:
    provider, approval, slots, factory, run_id, opener = build_dry_run({"work_id": "42"})
    reader_called = False

    def reader(_: str) -> str:
        nonlocal reader_called
        reader_called = True
        return PHRASE

    result = run_first_sample_dry_run(
        ApprovalMismatchProvider(provider),
        approval,
        slots,
        run_id=run_id,
        ttl_seconds=60,
        reader=reader,
        phrase_factory=lambda: PHRASE,
        now=lambda: NOW,
    )

    assert result.violations == ("provider_approval_binding_mismatch",)
    assert reader_called is False
    assert opener.requests == []
    with factory() as session:
        assert session.scalar(select(AcquisitionFirstRequestSlot)) is None


def test_provider_exception_consumes_permit_and_permanently_fails_slot() -> None:
    provider, approval, slots, factory, run_id, opener = build_dry_run({"work_id": "42"})
    opener._response = ExplodingResponse({"work_id": "42"})

    first = run_confirmed(provider, approval, slots, run_id)
    restarted_slots = FirstRequestSlotService(factory)
    second = run_confirmed(provider, approval, restarted_slots, run_id)

    assert first.status == "blocked"
    assert first.slot_status == "failed"
    assert first.violations == ("provider_request_failed",)
    assert "synthetic provider detail" not in repr(first)
    assert second.violations == ("first_request_slot_already_spent",)
    assert len(opener.requests) == 1
    with factory() as session:
        permit = session.scalar(select(AcquisitionRequestPermit))
        slot = session.scalar(select(AcquisitionFirstRequestSlot))
        budget = session.scalar(select(AcquisitionRunBudget))
        assert permit is not None and permit.status == "transport_failed"
        assert slot is not None and slot.status == "failed"
        assert budget is not None and budget.in_flight_count == 0


@pytest.mark.parametrize(
    ("status_code", "counter_name"),
    [(403, "consecutive_403"), (429, "consecutive_429")],
)
def test_403_or_429_is_recorded_once_and_slot_prevents_retry(
    status_code: int,
    counter_name: str,
) -> None:
    provider, approval, slots, factory, run_id, opener = build_dry_run(
        {"session_token": "discarded-sensitive-body"}
    )
    opener._response.status = status_code

    first = run_confirmed(provider, approval, slots, run_id)
    second = run_confirmed(provider, approval, FirstRequestSlotService(factory), run_id)

    assert first.status == "blocked"
    assert first.completed_requests == 0
    assert first.violations == ("provider_non_success_response",)
    assert second.violations == ("first_request_slot_already_spent",)
    assert len(opener.requests) == 1
    with factory() as session:
        permit = session.scalar(select(AcquisitionRequestPermit))
        slot = session.scalar(select(AcquisitionFirstRequestSlot))
        budget = session.scalar(select(AcquisitionRunBudget))
        assert permit is not None and permit.response_status == status_code
        assert permit.status == "consumed"
        assert slot is not None and slot.status == "failed"
        assert budget is not None and getattr(budget, counter_name) == 1


def test_schema_drift_is_terminal_and_never_retries_provider() -> None:
    provider, approval, slots, factory, run_id, opener = build_dry_run(
        {"work_id": "42", "unexpected": "blocked"}
    )

    first = run_confirmed(provider, approval, slots, run_id)
    second = run_confirmed(provider, approval, FirstRequestSlotService(factory), run_id)

    assert first.status == "blocked"
    assert first.violations == ("provider_request_failed",)
    assert first.slot_status == "failed"
    assert second.violations == ("first_request_slot_already_spent",)
    assert len(opener.requests) == 1
    with factory() as session:
        slot = session.scalar(select(AcquisitionFirstRequestSlot))
        budget = session.scalar(select(AcquisitionRunBudget))
        assert slot is not None and slot.status == "failed"
        assert budget is not None and budget.stop_reason == "schema_drift"


def test_concurrent_final_chain_contenders_fetch_exactly_once() -> None:
    approval = G0Approval.model_validate(valid_approval_payload())
    provider = SyntheticBoundProvider(approval_fingerprint(approval))
    slot = SyntheticPermanentSlot()
    barrier = threading.Barrier(2, timeout=2)
    result_lock = threading.Lock()
    results: list[FirstSampleDryRunResult] = []

    def contend() -> None:
        barrier.wait()
        result = run_first_sample_dry_run(
            provider,
            approval,
            slot,  # type: ignore[arg-type]
            run_id=1,
            ttl_seconds=60,
            reader=lambda _: PHRASE,
            phrase_factory=lambda: PHRASE,
            now=lambda: NOW,
        )
        with result_lock:
            results.append(result)

    threads = [threading.Thread(target=contend) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)

    assert all(not thread.is_alive() for thread in threads)
    assert provider.fetch_count == 1
    assert slot.status == "completed"
    assert sorted(result.status for result in results) == ["blocked", "passed"]
    assert sum(result.completed_requests for result in results) == 1
