"""Bridge bounded local processing to one ordered database transaction."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from threading import get_ident

from sqlalchemy.orm import Session, sessionmaker

from pixiv_yuri.acquisition.base import AcquisitionProvider
from pixiv_yuri.acquisition.models import AcquisitionRequest, EntityType, RawResponse
from pixiv_yuri.acquisition.pipeline import BoundedAcquisitionPipeline, PipelineRun


@dataclass(frozen=True, slots=True)
class OrderedDatabaseRun[ProcessedT, CommittedT]:
    """Ordered processing and commit evidence for one atomic run."""

    pipeline: PipelineRun[ProcessedT]
    committed_results: tuple[CommittedT, ...]
    coordinator_thread_id: int


class OrderedDatabasePipeline[ProcessedT, CommittedT]:
    """Process responses in parallel, then commit them in request order.

    The processor never receives a database Session. The only Session is opened
    after all local futures have completed, on the coordinator thread, and is
    closed before this method returns. A commit callback must return a detached
    value rather than an ORM object whose state depends on that Session.
    """

    def __init__(
        self,
        provider: AcquisitionProvider,
        processor: Callable[[RawResponse], ProcessedT],
        session_factory: sessionmaker[Session],
        committer: Callable[[Session, AcquisitionRequest, ProcessedT], CommittedT],
        *,
        local_processing_workers: int = 4,
        max_pending_local_tasks: int | None = None,
    ) -> None:
        self._pipeline = BoundedAcquisitionPipeline(
            provider,
            processor,
            local_processing_workers=local_processing_workers,
            max_pending_local_tasks=max_pending_local_tasks,
        )
        self._session_factory = session_factory
        self._committer = committer

    def run(
        self, entity_type: EntityType | None = None
    ) -> OrderedDatabaseRun[ProcessedT, CommittedT]:
        """Finish local work first, then atomically commit in source order."""
        coordinator_thread_id = get_ident()
        pipeline_run = self._pipeline.run(entity_type)
        committed: list[CommittedT] = []

        with self._session_factory.begin() as session:
            for request, processed in zip(
                pipeline_run.requests, pipeline_run.results, strict=True
            ):
                if get_ident() != coordinator_thread_id:
                    raise RuntimeError("Database commit escaped the coordinator thread.")
                committed.append(self._committer(session, request, processed))

        return OrderedDatabaseRun(
            pipeline=pipeline_run,
            committed_results=tuple(committed),
            coordinator_thread_id=coordinator_thread_id,
        )
