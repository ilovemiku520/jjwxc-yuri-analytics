"""Provider boundary that keeps source access separate from parsing."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable

from pixiv_yuri.acquisition.live_request_binding import CanonicalLiveRequestBinding
from pixiv_yuri.acquisition.models import AcquisitionRequest, EntityType, RawResponse
from pixiv_yuri.acquisition.runtime_session_lease import RuntimeSessionLease


class AcquisitionProvider(ABC):
    """Return immutable raw observations from an approved acquisition source."""

    @property
    def external_network_enabled(self) -> bool:
        """Default to an offline Provider unless a transport proves otherwise."""
        return False

    @property
    def approval_fingerprint(self) -> str | None:
        """Return a G0 binding when this Provider is approval-scoped."""
        return None

    @property
    def runtime_session_lease(self) -> RuntimeSessionLease | None:
        """Return the exact non-secret lease owned by a live transport, if any."""
        return None

    def plan_live_request_binding(
        self, request: AcquisitionRequest
    ) -> CanonicalLiveRequestBinding | None:
        """Return an exact network-free request identity for a live-capable Provider."""
        del request
        return None

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the stable provider identifier."""
        raise NotImplementedError

    @abstractmethod
    def list_requests(
        self, entity_type: EntityType | None = None
    ) -> tuple[AcquisitionRequest, ...]:
        """List deterministic requests available from this provider."""
        raise NotImplementedError

    @abstractmethod
    def fetch(self, request: AcquisitionRequest) -> RawResponse:
        """Fetch one response for a provider-owned request."""
        raise NotImplementedError

    def iter_responses(self, entity_type: EntityType | None = None) -> Iterable[RawResponse]:
        """Yield responses in provider-defined deterministic order."""
        for request in self.list_requests(entity_type):
            yield self.fetch(request)
