"""Final internal plan/send/settle/parse composition for one metadata request."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.orm import Session, sessionmaker

from pixiv_yuri.acquisition.base import AcquisitionProvider
from pixiv_yuri.acquisition.durable_external_sender import (
    DurableMarkerExternalSender,
    DurableMarkerSendContext,
)
from pixiv_yuri.acquisition.external_transport import ExternalSessionBroker
from pixiv_yuri.acquisition.first_request_slot import FirstRequestClaim
from pixiv_yuri.acquisition.live_attempt_coordinator import (
    InjectedTransportResponse,
    JournalBoundLiveAttemptCoordinator,
    JournalBoundSendContext,
)
from pixiv_yuri.acquisition.live_execution_journal import (
    LiveExecutionJournalService,
    LiveExecutionState,
)
from pixiv_yuri.acquisition.live_request_binding import CanonicalLiveRequestBinding
from pixiv_yuri.acquisition.models import AcquisitionRequest, RawResponse
from pixiv_yuri.acquisition.persistent_safety import PersistentAcquisitionSafety
from pixiv_yuri.acquisition.providers.pinned_metadata import (
    MetadataPolicyError,
    PinnedMetadataProvider,
)
from pixiv_yuri.acquisition.runtime_session_lease import RuntimeSessionLease


class JournalBoundProviderExecutionError(RuntimeError):
    """Payload-free failure from the final internal live execution boundary."""


class _DurableSenderAdapter:
    """Translate coordinator evidence without adding authority or settling permits."""

    def __init__(self, sender: DurableMarkerExternalSender) -> None:
        self._sender = sender

    def send(self, context: JournalBoundSendContext) -> InjectedTransportResponse:
        response = self._sender.send(
            DurableMarkerSendContext(
                journal_id=context.journal_id,
                permit_id=context.permit_id,
                request_binding_hash=context.request_binding_hash,
                send_started_at=context.send_started_at,
            )
        )
        return InjectedTransportResponse(
            status_code=response.status_code,
            content_type=response.content_type,
            body=response.body,
            headers=response.headers,
        )


class _PinnedSettledResponseProcessor:
    """Parse only a known response after permit and journal settlement."""

    def __init__(
        self,
        provider: PinnedMetadataProvider,
        request: AcquisitionRequest,
        binding: CanonicalLiveRequestBinding,
        *,
        clock: Callable[[], datetime],
    ) -> None:
        self._provider = provider
        self._request = request
        self._binding = binding
        self._clock = clock
        self.raw_response: RawResponse | None = None

    def process(self, response: InjectedTransportResponse) -> None:
        observed_at = _aware_utc(self._clock())
        try:
            self.raw_response = self._provider.parse_allowlisted_response(
                self._request,
                self._binding,
                response,
                observed_at=observed_at,
            )
        except MetadataPolicyError:
            self._provider.signal_schema_drift(now=observed_at)
            raise


class JournalBoundPinnedMetadataExecutor:
    """Construct the one-shot sender only after the permanent slot is claimed."""

    def __init__(
        self,
        *,
        safety: PersistentAcquisitionSafety,
        journals: LiveExecutionJournalService,
        broker: ExternalSessionBroker,
        session_factory: sessionmaker[Session],
        runtime_session_lease: RuntimeSessionLease,
        timeout_seconds: float,
        estimated_cost: Decimal = Decimal("0"),
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._safety = safety
        self._journals = journals
        self._broker = broker
        self._session_factory = session_factory
        self._runtime_session_lease = runtime_session_lease
        self._timeout_seconds = timeout_seconds
        self._estimated_cost = estimated_cost
        self._clock = clock or (lambda: datetime.now(UTC))

    def execute(
        self,
        *,
        provider: AcquisitionProvider,
        request: AcquisitionRequest,
        claim: FirstRequestClaim,
        binding: CanonicalLiveRequestBinding,
    ) -> RawResponse:
        if not isinstance(provider, PinnedMetadataProvider):
            raise JournalBoundProviderExecutionError(
                "Journal-bound Provider type is unavailable."
            )
        try:
            plan = provider.plan_network_free_request(request)
            if plan.binding != binding or plan.binding.binding_hash != claim.request_key_hash:
                raise ValueError("request binding mismatch")
            sender = DurableMarkerExternalSender(
                binding,
                self._broker,
                self._session_factory,
                runtime_session_lease=self._runtime_session_lease,
                timeout_seconds=min(plan.timeout_seconds, self._timeout_seconds),
                clock=self._clock,
            )
            processor = _PinnedSettledResponseProcessor(
                provider,
                request,
                binding,
                clock=self._clock,
            )
            coordinator = JournalBoundLiveAttemptCoordinator(
                self._safety,
                self._journals,
                _DurableSenderAdapter(sender),
                clock=self._clock,
            )
            result = coordinator.execute_binding(
                claim,
                binding=binding,
                estimated_cost=self._estimated_cost,
                response_processor=processor,
            )
        except JournalBoundProviderExecutionError:
            raise
        except Exception:
            raise JournalBoundProviderExecutionError(
                "Journal-bound Provider execution is unavailable."
            ) from None
        if result.state != LiveExecutionState.COMPLETED or processor.raw_response is None:
            raise JournalBoundProviderExecutionError(
                "Journal-bound Provider execution did not complete."
            )
        return processor.raw_response


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Provider execution timestamps must include a timezone.")
    return value.astimezone(UTC)
