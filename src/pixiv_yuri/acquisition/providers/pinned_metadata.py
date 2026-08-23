"""Host-pinned metadata Provider contract with strict G0 field minimization."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from urllib.parse import quote

from pixiv_yuri.acquisition.base import AcquisitionProvider
from pixiv_yuri.acquisition.live_request_binding import CanonicalLiveRequestBinding
from pixiv_yuri.acquisition.models import AcquisitionRequest, EntityType, RawResponse
from pixiv_yuri.acquisition.runtime_session_lease import RuntimeSessionLease
from pixiv_yuri.acquisition.transport_contract import (
    MetadataTransportResponse,
    PermitGuardedMetadataTransport,
    normalize_pinned_metadata_origin,
    pinned_metadata_origin_kind,
)
from pixiv_yuri.governance.g0 import G0Approval, approval_fingerprint

_SENSITIVE_KEY_FRAGMENTS = ("authorization", "cookie", "password", "secret", "token")
_PATHS = {
    EntityType.WORK: "works",
    EntityType.AUTHOR: "authors",
    EntityType.TAG_PAGE: "tags",
}
_REQUIRED_IDENTITY = {
    EntityType.WORK: "work_id",
    EntityType.AUTHOR: "author_id",
    EntityType.TAG_PAGE: "tag_name",
}


class MetadataPolicyReason(StrEnum):
    """Non-secret reasons for rejecting one metadata payload."""

    INVALID_ROOT = "invalid_root"
    SENSITIVE_FIELD = "sensitive_field"
    SCHEMA_DRIFT = "schema_drift"
    MISSING_IDENTITY = "missing_identity"


class MetadataPolicyError(ValueError):
    """Fail closed without placing field names or values into the exception."""

    def __init__(self, reason: MetadataPolicyReason) -> None:
        self.reason = reason
        super().__init__(f"Metadata payload rejected: {reason.value}")


class ApprovedMetadataPolicy:
    """Allow exactly the top-level fields recorded in one G0 approval."""

    def __init__(self, approval: G0Approval) -> None:
        self._allowed_fields = frozenset(approval.source_scope.allowed_fields)

    def apply(self, payload: Any, entity_type: EntityType) -> dict[str, Any]:
        """Return an allowlisted copy or reject the whole payload."""
        if not isinstance(payload, Mapping):
            raise MetadataPolicyError(MetadataPolicyReason.INVALID_ROOT)
        if _contains_sensitive_key(payload):
            raise MetadataPolicyError(MetadataPolicyReason.SENSITIVE_FIELD)
        if not set(payload).issubset(self._allowed_fields):
            raise MetadataPolicyError(MetadataPolicyReason.SCHEMA_DRIFT)
        identity_field = _REQUIRED_IDENTITY.get(entity_type)
        if identity_field is None or identity_field not in payload:
            raise MetadataPolicyError(MetadataPolicyReason.MISSING_IDENTITY)
        if any(_contains_mapping(value) for value in payload.values()):
            raise MetadataPolicyError(MetadataPolicyReason.SCHEMA_DRIFT)
        return {str(key): value for key, value in payload.items()}


@dataclass(frozen=True, slots=True)
class PinnedMetadataRequestPlan:
    """Network-free, non-authorizing description of one exact live request."""

    request: AcquisitionRequest
    binding: CanonicalLiveRequestBinding
    timeout_seconds: float

    @property
    def source_url(self) -> str:
        """Return the exact URL already covered by the canonical binding."""
        return self.binding.canonical_url


class PinnedMetadataProvider(AcquisitionProvider):
    """Fetch provider-owned paths from one approved, structurally pinned origin."""

    def __init__(
        self,
        origin: str,
        requests: tuple[AcquisitionRequest, ...],
        transport: PermitGuardedMetadataTransport,
        approval: G0Approval,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._origin = normalize_pinned_metadata_origin(origin)
        transport_kind = transport.transport_kind
        if transport_kind != pinned_metadata_origin_kind(self._origin):
            raise ValueError("Pinned metadata origin and transport modes do not match.")
        try:
            transport.validate_origin(self._origin)
        except Exception:
            raise ValueError(
                "Pinned metadata origin is not permitted by its transport."
            ) from None
        if len({request.key for request in requests}) != len(requests):
            raise ValueError("Pinned Provider requests must have unique logical keys.")
        unsupported = {request.entity_type for request in requests} - set(_PATHS)
        if unsupported:
            raise ValueError("Pinned Provider contains an unsupported entity type.")
        self._requests = requests
        self._request_keys = {request.key for request in requests}
        self._transport = transport
        self._transport_kind = transport_kind
        self._policy = ApprovedMetadataPolicy(approval)
        self._approval_fingerprint = approval_fingerprint(approval)
        self._timeout_seconds = approval.traffic_limits.request_timeout_seconds
        self._clock = clock or (lambda: datetime.now(UTC))

    @property
    def name(self) -> str:
        """Identify this as a local contract Provider, never a live source client."""
        return "pinned_metadata_local_contract"

    @property
    def external_network_enabled(self) -> bool:
        """Expose the transport mode without revealing credentials or host details."""
        return self._transport.external_network_enabled

    @property
    def approval_fingerprint(self) -> str:
        """Bind orchestration to the exact G0 record used by the field policy."""
        return self._approval_fingerprint

    @property
    def runtime_session_lease(self) -> RuntimeSessionLease | None:
        """Expose only the exact lease identity owned by the external transport."""
        return getattr(self._transport, "runtime_session_lease", None)

    def list_requests(
        self, entity_type: EntityType | None = None
    ) -> tuple[AcquisitionRequest, ...]:
        """Return only the immutable seed requests owned by this Provider."""
        return tuple(
            request
            for request in self._requests
            if entity_type is None or request.entity_type == entity_type
        )

    def fetch(self, request: AcquisitionRequest) -> RawResponse:
        """Compatibility wrapper; live orchestration uses the split plan/parse API."""
        self._require_owned_request(request)
        if self._transport_kind == "exact_https_dns" and self.external_network_enabled:
            raise RuntimeError(
                "Direct live Provider fetch is disabled; use journal-bound execution."
            )
        observed_at = self._clock()
        if self._transport_kind == "exact_https_dns":
            plan = self.plan_network_free_request(request)
            response = self._transport.fetch(
                plan.source_url,
                timeout_seconds=plan.timeout_seconds,
            )
        else:
            source_url = self._source_url(request)
            response = self._transport.fetch(
                source_url,
                timeout_seconds=self._timeout_seconds,
                now=observed_at,
            )
        try:
            if self._transport_kind == "exact_https_dns":
                return self.parse_allowlisted_response(
                    request,
                    plan.binding,
                    response,
                    observed_at=observed_at,
                )
            return self._parse_minimized_response(
                request,
                response,
                source_url=source_url,
                observed_at=observed_at,
            )
        except MetadataPolicyError:
            self._transport.signal_schema_drift(now=observed_at)
            raise

    def signal_schema_drift(self, *, now: datetime | None = None) -> None:
        """Persist a drift stop when the final settled-response processor rejects."""
        self._transport.signal_schema_drift(now=now)

    def plan_network_free_request(
        self, request: AcquisitionRequest
    ) -> PinnedMetadataRequestPlan:
        """Plan an exact HTTPS request without authorizing or touching transport."""
        self._require_owned_request(request)
        if self._transport_kind != "exact_https_dns":
            raise ValueError("Live request plans require one exact HTTPS origin.")
        binding = self._binding_for_request(request)
        return PinnedMetadataRequestPlan(
            request=request,
            binding=binding,
            timeout_seconds=self._timeout_seconds,
        )

    def parse_allowlisted_response(
        self,
        request: AcquisitionRequest,
        binding: CanonicalLiveRequestBinding,
        response: MetadataTransportResponse,
        *,
        observed_at: datetime | None = None,
    ) -> RawResponse:
        """Validate identity and minimize a known response without transport calls.

        Schema-policy errors are returned to the orchestrator as exceptions. The
        orchestrator, not this pure parsing boundary, owns durable drift signaling.
        """
        self._require_owned_request(request)
        if not isinstance(binding, CanonicalLiveRequestBinding):
            raise ValueError("Canonical live request binding is invalid.")
        expected = self._binding_for_request(request)
        if binding != expected or binding.binding_hash != expected.binding_hash:
            raise ValueError("Canonical live request binding does not match Provider.")
        return self._parse_minimized_response(
            request,
            response,
            source_url=binding.canonical_url,
            observed_at=observed_at or self._clock(),
        )

    def _parse_minimized_response(
        self,
        request: AcquisitionRequest,
        response: MetadataTransportResponse,
        *,
        source_url: str,
        observed_at: datetime,
    ) -> RawResponse:
        """Apply the common response minimization logic without any I/O."""
        if (
            isinstance(response.status_code, bool)
            or not isinstance(response.status_code, int)
            or not 100 <= response.status_code <= 599
        ):
            raise ValueError("Metadata response status is invalid.")
        if response.status_code < 200 or response.status_code >= 300:
            return RawResponse(
                provider=self.name,
                entity_type=request.entity_type,
                source_id=request.source_id,
                observed_at=observed_at,
                status_code=response.status_code,
                content_type="application/json",
                body=b"{}",
                source_url=source_url,
                headers=dict(response.headers),
                metadata={"response_body_discarded": True},
            )
        try:
            payload = json.loads(response.body.decode("utf-8"))
            approved = self._policy.apply(payload, request.entity_type)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise MetadataPolicyError(MetadataPolicyReason.INVALID_ROOT) from None
        minimized_body = json.dumps(
            approved,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return RawResponse(
            provider=self.name,
            entity_type=request.entity_type,
            source_id=request.source_id,
            observed_at=observed_at,
            status_code=response.status_code,
            content_type="application/json",
            body=minimized_body,
            source_url=source_url,
            headers=dict(response.headers),
            metadata={"field_count": len(approved), "policy": "g0_exact_allowlist"},
        )

    def plan_live_request_binding(
        self, request: AcquisitionRequest
    ) -> CanonicalLiveRequestBinding:
        """Build the exact, network-free identity used by every durable live guard."""
        return self.plan_network_free_request(request).binding

    def _binding_for_request(
        self, request: AcquisitionRequest
    ) -> CanonicalLiveRequestBinding:
        return CanonicalLiveRequestBinding.from_request(
            approval_fingerprint=self._approval_fingerprint,
            provider_id=self.name,
            request=request,
            exact_url=self._source_url(request),
        )

    def _require_owned_request(self, request: AcquisitionRequest) -> None:
        if request.key not in self._request_keys:
            raise ValueError("Request is not owned by the pinned metadata Provider.")

    def _source_url(self, request: AcquisitionRequest) -> str:
        path_group = _PATHS[request.entity_type]
        return f"{self._origin}/{path_group}/{quote(request.source_id, safe='')}"


def _contains_sensitive_key(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if any(fragment in str(key).lower() for fragment in _SENSITIVE_KEY_FRAGMENTS):
                return True
            if _contains_sensitive_key(child):
                return True
    elif isinstance(value, list):
        return any(_contains_sensitive_key(child) for child in value)
    return False


def _contains_mapping(value: Any) -> bool:
    if isinstance(value, Mapping):
        return True
    if isinstance(value, list):
        return any(_contains_mapping(child) for child in value)
    return False
