"""Authenticated-scope simulation that remains entirely fixture-backed."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pixiv_yuri.acquisition.auth import SessionBroker, SessionCapabilityError
from pixiv_yuri.acquisition.base import AcquisitionProvider
from pixiv_yuri.acquisition.models import AcquisitionRequest, EntityType, RawResponse
from pixiv_yuri.acquisition.providers.fixture import FixtureProvider
from pixiv_yuri.governance.g0 import G0Approval

_SECRET_KEY_FRAGMENTS = ("authorization", "cookie", "password", "secret", "token")


class AuthenticatedFixtureProviderError(RuntimeError):
    """Raised when the offline session cannot satisfy the approved G0 scope."""


class AuthenticatedFixtureProvider(AcquisitionProvider):
    """Exercise authenticated control flow without credentials or network access."""

    def __init__(
        self,
        manifest_path: Path | str,
        approval: G0Approval,
        session_broker: SessionBroker,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        scope = approval.source_scope
        if scope.authentication_mode != "user_managed_session":
            raise AuthenticatedFixtureProviderError(
                "Authenticated fixture simulation requires user-managed-session approval."
            )
        if scope.content_visibility != "authenticated_public":
            raise AuthenticatedFixtureProviderError(
                "Authenticated fixture simulation is limited to authenticated-public content."
            )
        self._fixture = FixtureProvider(manifest_path)
        self._approval = approval
        self._session_broker = session_broker
        self._clock = clock or (lambda: datetime.now(UTC))

    @property
    def name(self) -> str:
        """Identify the provider as an offline authenticated-scope simulation."""
        return f"authenticated_fixture:{self._fixture.name}"

    def list_requests(
        self, entity_type: EntityType | None = None
    ) -> tuple[AcquisitionRequest, ...]:
        """Delegate deterministic request listing to the fixture provider."""
        return self._fixture.list_requests(entity_type)

    def fetch(self, request: AcquisitionRequest) -> RawResponse:
        """Validate approval/session scope, then read one local fixture."""
        checked_at = self._clock()
        if checked_at.tzinfo is None or checked_at.utcoffset() is None:
            raise ValueError("Provider clock must include a timezone.")
        if not (self._approval.approved_at <= checked_at < self._approval.expires_at):
            raise AuthenticatedFixtureProviderError("G0 approval is inactive.")

        with self._session_broker.open_session() as session:
            try:
                session.ensure_active(checked_at)
            except SessionCapabilityError as exc:
                raise AuthenticatedFixtureProviderError(str(exc)) from exc
            missing_ratings = (
                self._approval.source_scope.allowed_age_ratings
                - session.allowed_age_ratings
            )
            if missing_ratings:
                raise AuthenticatedFixtureProviderError(
                    f"Session lacks approved age-rating scope: {sorted(missing_ratings)}"
                )

            response = self._fixture.fetch(request)
            if _response_has_secret_shaped_fields(response):
                raise AuthenticatedFixtureProviderError(
                    "Fixture response contains prohibited secret-shaped fields."
                )
            return response.model_copy(
                update={
                    "provider": self.name,
                    "metadata": {
                        **response.metadata,
                        "authentication_mode": "user_managed_session",
                        "content_visibility": "authenticated_public",
                        "allowed_age_ratings": sorted(session.allowed_age_ratings),
                    },
                }
            )


def _response_has_secret_shaped_fields(response: RawResponse) -> bool:
    if _has_secret_shaped_key(response.headers) or _has_secret_shaped_key(response.metadata):
        return True
    try:
        return _has_secret_shaped_key(response.json_value())
    except (UnicodeDecodeError, ValueError):
        return True


def _has_secret_shaped_key(value: Any) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            if any(fragment in str(key).lower() for fragment in _SECRET_KEY_FRAGMENTS):
                return True
            if _has_secret_shaped_key(child):
                return True
    elif isinstance(value, list):
        return any(_has_secret_shaped_key(child) for child in value)
    return False
