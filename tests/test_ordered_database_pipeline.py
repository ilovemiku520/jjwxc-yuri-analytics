from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, insert, select
from sqlalchemy.orm import Session, sessionmaker

from pixiv_yuri.acquisition.base import AcquisitionProvider
from pixiv_yuri.acquisition.models import AcquisitionRequest, EntityType, RawResponse
from pixiv_yuri.ingest.ordered_pipeline import OrderedDatabasePipeline

NOW = datetime(2026, 8, 23, tzinfo=UTC)


class ThreadRecordingProvider(AcquisitionProvider):
    def __init__(self, source_ids: tuple[str, ...]) -> None:
        self._requests = tuple(
            AcquisitionRequest(entity_type=EntityType.WORK, source_id=source_id)
            for source_id in source_ids
        )
        self.fetch_thread_ids: list[int] = []
        self.active_fetches = 0
        self.peak_active_fetches = 0

    @property
    def name(self) -> str:
        return "ordered-pipeline-test"

    def list_requests(
        self, entity_type: EntityType | None = None
    ) -> tuple[AcquisitionRequest, ...]:
        return tuple(
            request
            for request in self._requests
            if entity_type is None or request.entity_type == entity_type
        )

    def fetch(self, request: AcquisitionRequest) -> RawResponse:
        self.fetch_thread_ids.append(threading.get_ident())
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


@dataclass(frozen=True, slots=True)
class ProcessedItem:
    source_id: str
    processor_thread_id: int


metadata = MetaData()
committed_items = Table(
    "ordered_pipeline_items",
    metadata,
    Column("sequence", Integer, primary_key=True),
    Column("source_id", String(50), nullable=False),
)


def build_factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def test_parallel_processing_is_committed_in_request_order_on_coordinator() -> None:
    coordinator_thread_id = threading.get_ident()
    provider = ThreadRecordingProvider(("0", "1", "2"))
    factory = build_factory()
    later_finished = threading.Event()
    lock = threading.Lock()
    later_count = 0
    processor_threads: set[int] = set()
    commit_threads: list[int] = []

    def process(response: RawResponse) -> ProcessedItem:
        nonlocal later_count
        thread_id = threading.get_ident()
        with lock:
            processor_threads.add(thread_id)
        if response.source_id == "0":
            assert later_finished.wait(timeout=2)
        else:
            with lock:
                later_count += 1
                if later_count == 2:
                    later_finished.set()
        return ProcessedItem(response.source_id, thread_id)

    def commit(
        session: Session, request: AcquisitionRequest, item: ProcessedItem
    ) -> str:
        commit_threads.append(threading.get_ident())
        assert request.source_id == item.source_id
        session.execute(
            insert(committed_items).values(
                sequence=int(request.source_id),
                source_id=item.source_id,
            )
        )
        return item.source_id

    result = OrderedDatabasePipeline(
        provider,
        process,
        factory,
        commit,
        local_processing_workers=3,
        max_pending_local_tasks=3,
    ).run()

    with factory() as session:
        rows = session.execute(
            select(committed_items.c.source_id).order_by(committed_items.c.sequence)
        ).scalars().all()

    assert result.committed_results == ("0", "1", "2")
    assert rows == ["0", "1", "2"]
    assert result.pipeline.acquisition_workers == 1
    assert result.pipeline.local_processing_workers == 3
    assert provider.peak_active_fetches == 1
    assert set(provider.fetch_thread_ids) == {coordinator_thread_id}
    assert processor_threads
    assert coordinator_thread_id not in processor_threads
    assert set(commit_threads) == {coordinator_thread_id}


def test_commit_failure_rolls_back_the_whole_ordered_batch() -> None:
    provider = ThreadRecordingProvider(("0", "1", "2"))
    factory = build_factory()

    def commit(
        session: Session, request: AcquisitionRequest, item: str
    ) -> str:
        if item == "1":
            raise RuntimeError("synthetic commit failure")
        session.execute(
            insert(committed_items).values(
                sequence=int(request.source_id),
                source_id=item,
            )
        )
        return item

    pipeline = OrderedDatabasePipeline(
        provider,
        lambda response: response.source_id,
        factory,
        commit,
        local_processing_workers=2,
    )

    with pytest.raises(RuntimeError, match="synthetic commit failure"):
        pipeline.run()

    with factory() as session:
        assert session.execute(select(committed_items)).all() == []


def test_processing_failure_opens_no_database_transaction() -> None:
    provider = ThreadRecordingProvider(("0",))
    factory = build_factory()
    transaction_opened = False

    def fail(_response: RawResponse) -> str:
        raise RuntimeError("synthetic processing failure")

    def commit(
        _session: Session, _request: AcquisitionRequest, item: str
    ) -> str:
        nonlocal transaction_opened
        transaction_opened = True
        return item

    pipeline = OrderedDatabasePipeline(provider, fail, factory, commit)

    with pytest.raises(RuntimeError, match="synthetic processing failure"):
        pipeline.run()

    assert transaction_opened is False
