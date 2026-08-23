from __future__ import annotations

import threading
from datetime import UTC, datetime

import pytest

from pixiv_yuri.acquisition.base import AcquisitionProvider
from pixiv_yuri.acquisition.models import AcquisitionRequest, EntityType, RawResponse
from pixiv_yuri.acquisition.pipeline import BoundedAcquisitionPipeline

NOW = datetime(2026, 8, 23, tzinfo=UTC)


class RecordingProvider(AcquisitionProvider):
    def __init__(self, source_ids: tuple[str, ...]) -> None:
        self.requests = tuple(
            AcquisitionRequest(entity_type=EntityType.WORK, source_id=source_id)
            for source_id in source_ids
        )
        self.fetch_count = 0
        self.active_fetches = 0
        self.peak_active_fetches = 0

    @property
    def name(self) -> str:
        return "recording"

    def list_requests(
        self, entity_type: EntityType | None = None
    ) -> tuple[AcquisitionRequest, ...]:
        return tuple(
            request
            for request in self.requests
            if entity_type is None or request.entity_type == entity_type
        )

    def fetch(self, request: AcquisitionRequest) -> RawResponse:
        self.fetch_count += 1
        self.active_fetches += 1
        self.peak_active_fetches = max(self.peak_active_fetches, self.active_fetches)
        try:
            return RawResponse(
                provider=self.name,
                entity_type=request.entity_type,
                source_id=request.source_id,
                observed_at=NOW,
                status_code=200,
                content_type="application/json",
                body=b"{}",
            )
        finally:
            self.active_fetches -= 1


def test_local_processing_overlaps_but_acquisition_stays_serial() -> None:
    provider = RecordingProvider(("0", "1", "2"))
    barrier = threading.Barrier(3, timeout=2)
    lock = threading.Lock()
    active = 0
    peak_active = 0

    def process(response: RawResponse) -> str:
        nonlocal active, peak_active
        with lock:
            active += 1
            peak_active = max(peak_active, active)
        try:
            barrier.wait()
            return response.source_id
        finally:
            with lock:
                active -= 1

    run = BoundedAcquisitionPipeline(
        provider,
        process,
        local_processing_workers=3,
        max_pending_local_tasks=3,
    ).run()

    assert run.results == ("0", "1", "2")
    assert run.acquisition_workers == 1
    assert provider.peak_active_fetches == 1
    assert peak_active == 3
    assert run.peak_pending_local_tasks == 3


def test_completion_order_does_not_change_result_order() -> None:
    provider = RecordingProvider(("0", "1", "2"))
    later_finished = threading.Event()
    lock = threading.Lock()
    completion_order: list[str] = []
    later_count = 0

    def process(response: RawResponse) -> str:
        nonlocal later_count
        if response.source_id == "0":
            assert later_finished.wait(timeout=2)
        else:
            with lock:
                completion_order.append(response.source_id)
                later_count += 1
                if later_count == 2:
                    later_finished.set()
            return f"result-{response.source_id}"
        with lock:
            completion_order.append(response.source_id)
        return f"result-{response.source_id}"

    run = BoundedAcquisitionPipeline(
        provider,
        process,
        local_processing_workers=3,
        max_pending_local_tasks=3,
    ).run()

    assert completion_order[-1] == "0"
    assert run.results == ("result-0", "result-1", "result-2")


def test_duplicate_request_is_rejected_before_fetch() -> None:
    provider = RecordingProvider(("same", "same"))
    pipeline = BoundedAcquisitionPipeline(provider, lambda response: response.source_id)

    with pytest.raises(ValueError, match="unique logical keys"):
        pipeline.run()

    assert provider.fetch_count == 0


def test_processing_failure_stops_before_next_fetch_when_backpressured() -> None:
    provider = RecordingProvider(("first", "second"))

    def fail(_response: RawResponse) -> str:
        raise RuntimeError("synthetic local failure")

    pipeline = BoundedAcquisitionPipeline(
        provider,
        fail,
        local_processing_workers=1,
        max_pending_local_tasks=1,
    )

    with pytest.raises(RuntimeError, match="synthetic local failure"):
        pipeline.run()

    assert provider.fetch_count == 1


@pytest.mark.parametrize("workers", [0, 9])
def test_local_worker_limit_is_bounded(workers: int) -> None:
    provider = RecordingProvider(("one",))

    with pytest.raises(ValueError, match="between 1 and 8"):
        BoundedAcquisitionPipeline(
            provider,
            lambda response: response.source_id,
            local_processing_workers=workers,
        )


@pytest.mark.parametrize("pending", [0, 65])
def test_pending_task_limit_is_bounded(pending: int) -> None:
    provider = RecordingProvider(("one",))

    with pytest.raises(ValueError, match="between the worker count and 64"):
        BoundedAcquisitionPipeline(
            provider,
            lambda response: response.source_id,
            local_processing_workers=1,
            max_pending_local_tasks=pending,
        )
