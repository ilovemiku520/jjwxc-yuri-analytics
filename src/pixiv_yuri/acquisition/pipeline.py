"""Bounded two-stage acquisition pipeline with serialized source access."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass

from pixiv_yuri.acquisition.base import AcquisitionProvider
from pixiv_yuri.acquisition.models import AcquisitionRequest, EntityType, RawResponse

_MAX_LOCAL_WORKERS = 8
_MAX_PENDING_LOCAL_TASKS = 64


@dataclass(frozen=True, slots=True)
class PipelineRun[ResultT]:
    """Deterministic results and non-sensitive concurrency evidence for one run."""

    requests: tuple[AcquisitionRequest, ...]
    results: tuple[ResultT, ...]
    acquisition_workers: int
    local_processing_workers: int
    peak_pending_local_tasks: int


class BoundedAcquisitionPipeline[ResultT]:
    """Serialize permit-bearing fetches while parallelizing local-only processing.

    Source acquisition deliberately remains on the caller thread. Only responses
    already returned by the Provider enter the worker pool, so this class cannot
    increase the external concurrency recorded in G0.
    """

    def __init__(
        self,
        provider: AcquisitionProvider,
        processor: Callable[[RawResponse], ResultT],
        *,
        local_processing_workers: int = 4,
        max_pending_local_tasks: int | None = None,
    ) -> None:
        if not 1 <= local_processing_workers <= _MAX_LOCAL_WORKERS:
            raise ValueError("Local processing workers must be between 1 and 8.")
        pending_limit = (
            max_pending_local_tasks
            if max_pending_local_tasks is not None
            else local_processing_workers * 2
        )
        if not local_processing_workers <= pending_limit <= _MAX_PENDING_LOCAL_TASKS:
            raise ValueError(
                "Pending local task limit must be between the worker count and 64."
            )
        self._provider = provider
        self._processor = processor
        self._local_workers = local_processing_workers
        self._pending_limit = pending_limit

    def run(self, entity_type: EntityType | None = None) -> PipelineRun[ResultT]:
        """Fetch each unique request once and return results in request order."""
        requests = self._provider.list_requests(entity_type)
        if len({request.key for request in requests}) != len(requests):
            raise ValueError("Pipeline requests must have unique logical keys.")

        futures: list[Future[ResultT]] = []
        resolved: dict[int, ResultT] = {}
        peak_pending = 0

        with ThreadPoolExecutor(
            max_workers=self._local_workers,
            thread_name_prefix="pyuri-local",
        ) as executor:
            try:
                for request in requests:
                    self._harvest_completed(futures, resolved)
                    response = self._provider.fetch(request)
                    futures.append(executor.submit(self._processor, response))
                    peak_pending = max(peak_pending, len(futures) - len(resolved))
                    if len(futures) - len(resolved) >= self._pending_limit:
                        self._resolve_oldest(futures, resolved)

                for index, future in enumerate(futures):
                    if index not in resolved:
                        resolved[index] = future.result()
            except BaseException:
                for future in futures:
                    future.cancel()
                raise

        return PipelineRun(
            requests=requests,
            results=tuple(resolved[index] for index in range(len(requests))),
            acquisition_workers=1,
            local_processing_workers=self._local_workers,
            peak_pending_local_tasks=peak_pending,
        )

    @staticmethod
    def _harvest_completed(
        futures: list[Future[ResultT]], resolved: dict[int, ResultT]
    ) -> None:
        """Surface local failures before scheduling the next source request."""
        for index, future in enumerate(futures):
            if index not in resolved and future.done():
                resolved[index] = future.result()

    @staticmethod
    def _resolve_oldest(
        futures: list[Future[ResultT]], resolved: dict[int, ResultT]
    ) -> None:
        """Apply deterministic backpressure without completion-order output."""
        for index, future in enumerate(futures):
            if index not in resolved:
                resolved[index] = future.result()
                return
