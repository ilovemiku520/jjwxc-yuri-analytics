from __future__ import annotations

import pickle
import threading
from datetime import UTC, datetime, timedelta

import pytest

from pixiv_yuri.acquisition.base import AcquisitionProvider
from pixiv_yuri.acquisition.models import AcquisitionRequest, EntityType, RawResponse
from pixiv_yuri.governance.one_request_executor import (
    CapabilityUnavailableError,
    ConfirmedOneRequestCapability,
    confirm_and_execute_exactly_one,
    confirm_one_request_capability,
    execute_exactly_one_provider_request,
)

NOW = datetime(2026, 8, 22, 12, tzinfo=UTC)
REQUEST = AcquisitionRequest(entity_type=EntityType.WORK, source_id="synthetic-one")


class InjectedProvider(AcquisitionProvider):
    def __init__(
        self,
        *,
        fail: bool = False,
        wrong_identity: bool = False,
        status_code: int = 200,
    ) -> None:
        self.fetch_count = 0
        self._fail = fail
        self._wrong_identity = wrong_identity
        self._status_code = status_code
        self._lock = threading.Lock()

    @property
    def external_network_enabled(self) -> bool:
        return False

    @property
    def name(self) -> str:
        return "injected_test_provider"

    def list_requests(
        self, entity_type: EntityType | None = None
    ) -> tuple[AcquisitionRequest, ...]:
        return (REQUEST,) if entity_type in {None, EntityType.WORK} else ()

    def fetch(self, request: AcquisitionRequest) -> RawResponse:
        with self._lock:
            self.fetch_count += 1
        if self._fail:
            raise RuntimeError("synthetic sensitive provider detail")
        source_id = "wrong" if self._wrong_identity else request.source_id
        return RawResponse(
            provider=self.name,
            entity_type=request.entity_type,
            source_id=source_id,
            observed_at=NOW,
            status_code=self._status_code,
            content_type="application/json",
            body=b'{"private_value":"must-not-escape"}',
        )


def confirmed_capability(
    provider: AcquisitionProvider,
) -> ConfirmedOneRequestCapability:
    confirmation, capability = confirm_one_request_capability(
        provider,
        (REQUEST,),
        ttl_seconds=60,
        reader=lambda prompt: PHRASE if PHRASE in prompt else "",
        phrase_factory=lambda: PHRASE,
        now=lambda: NOW,
    )
    assert confirmation.status == "passed"
    assert capability is not None
    return capability


PHRASE = "CONFIRM-ONE-001122AABBCC"


def test_exactly_one_injected_provider_fetch_returns_only_safe_fields() -> None:
    provider = InjectedProvider()
    result = confirm_and_execute_exactly_one(
        provider,
        (REQUEST,),
        ttl_seconds=60,
        reader=lambda prompt: PHRASE if PHRASE in prompt else "",
        phrase_factory=lambda: PHRASE,
        now=lambda: NOW,
    )

    assert result.status == "passed"
    assert provider.fetch_count == 1
    assert result.attempted_requests == result.completed_requests == 1
    assert result.capability_consumed is True
    assert result.external_network_used is False
    assert "must-not-escape" not in repr(result)
    assert not hasattr(result, "body")
    assert not hasattr(result, "headers")
    assert not hasattr(result, "source_url")


@pytest.mark.parametrize("requests", [(), (REQUEST, REQUEST)])
def test_request_count_other_than_one_consumes_capability_without_fetch(
    requests: tuple[AcquisitionRequest, ...],
) -> None:
    provider = InjectedProvider()
    capability = confirmed_capability(provider)

    result = execute_exactly_one_provider_request(
        capability,
        provider,
        requests,
        now=NOW,
    )

    assert result.status == "blocked"
    assert result.violations == ("planned_requests_must_equal_one",)
    assert result.capability_consumed is True
    assert provider.fetch_count == 0


def test_provider_failure_consumes_capability_and_safe_result_hides_exception() -> None:
    provider = InjectedProvider(fail=True)
    capability = confirmed_capability(provider)

    result = execute_exactly_one_provider_request(
        capability,
        provider,
        (REQUEST,),
        now=NOW,
    )
    retry = execute_exactly_one_provider_request(
        capability,
        provider,
        (REQUEST,),
        now=NOW,
    )

    assert result.violations == ("provider_request_failed",)
    assert "sensitive" not in repr(result)
    assert retry.violations == ("capability_unavailable",)
    assert provider.fetch_count == 1


def test_successful_capability_cannot_be_reused() -> None:
    provider = InjectedProvider()
    capability = confirmed_capability(provider)

    first = execute_exactly_one_provider_request(capability, provider, (REQUEST,), now=NOW)
    second = execute_exactly_one_provider_request(capability, provider, (REQUEST,), now=NOW)

    assert first.status == "passed"
    assert second.status == "blocked"
    assert second.violations == ("capability_unavailable",)
    assert provider.fetch_count == 1


def test_two_threads_competing_for_one_capability_fetch_only_once() -> None:
    provider = InjectedProvider()
    capability = confirmed_capability(provider)
    barrier = threading.Barrier(2)
    results = []

    def execute() -> None:
        barrier.wait()
        results.append(
            execute_exactly_one_provider_request(capability, provider, (REQUEST,), now=NOW)
        )

    threads = [threading.Thread(target=execute) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)

    assert provider.fetch_count == 1
    assert sorted(result.status for result in results) == ["blocked", "passed"]


def test_expired_capability_is_consumed_without_fetch() -> None:
    provider = InjectedProvider()
    capability = confirmed_capability(provider)

    result = execute_exactly_one_provider_request(
        capability,
        provider,
        (REQUEST,),
        now=NOW + timedelta(seconds=60),
    )

    assert result.violations == ("capability_unavailable",)
    assert result.capability_consumed is True
    assert provider.fetch_count == 0


def test_unconfirmed_gate_cannot_issue_capability() -> None:
    provider = InjectedProvider()
    confirmation, capability = confirm_one_request_capability(
        provider,
        (REQUEST,),
        ttl_seconds=60,
        reader=lambda _: "wrong",
        phrase_factory=lambda: PHRASE,
        now=lambda: NOW,
    )

    assert confirmation.status == "blocked"
    assert capability is None


def test_capability_cannot_be_forged_or_serialized() -> None:
    provider = InjectedProvider()
    with pytest.raises(CapabilityUnavailableError, match="confirmed gate"):
        ConfirmedOneRequestCapability(
            NOW + timedelta(seconds=60),
            provider,
            REQUEST,
            _issuer=object(),
        )

    capability = confirmed_capability(provider)
    with pytest.raises(TypeError, match="cannot be serialized"):
        pickle.dumps(capability)


def test_network_execution_flag_is_rejected_before_injected_provider_fetch() -> None:
    provider = InjectedProvider()
    capability = confirmed_capability(provider)

    result = execute_exactly_one_provider_request(
        capability,
        provider,
        (REQUEST,),
        now=NOW,
        external_network_used=True,
    )

    assert result.status == "blocked"
    assert result.violations == ("network_execution_not_enabled",)
    assert result.external_network_used is False
    assert result.capability_consumed is True
    assert provider.fetch_count == 0


def test_provider_with_real_network_mode_is_rejected_before_fetch() -> None:
    class NetworkProvider(InjectedProvider):
        @property
        def external_network_enabled(self) -> bool:
            return True

    network_provider = NetworkProvider()
    capability = confirmed_capability(network_provider)
    result = execute_exactly_one_provider_request(
        capability,
        network_provider,
        (REQUEST,),
        now=NOW,
    )

    assert result.violations == ("network_execution_not_enabled",)
    assert result.capability_consumed is True
    assert network_provider.fetch_count == 0


def test_mismatched_response_identity_fails_closed_after_one_fetch() -> None:
    provider = InjectedProvider(wrong_identity=True)
    capability = confirmed_capability(provider)

    result = execute_exactly_one_provider_request(
        capability,
        provider,
        (REQUEST,),
        now=NOW,
    )

    assert result.status == "blocked"
    assert result.violations == ("provider_response_identity_mismatch",)
    assert result.completed_requests == 0
    assert provider.fetch_count == 1


@pytest.mark.parametrize("status_code", [100, 199, 300, 403, 429, 599])
def test_non_success_response_is_attempted_but_not_completed(status_code: int) -> None:
    provider = InjectedProvider(status_code=status_code)
    capability = confirmed_capability(provider)

    result = execute_exactly_one_provider_request(
        capability,
        provider,
        (REQUEST,),
        now=NOW,
    )

    assert result.status == "blocked"
    assert result.violations == ("provider_non_success_response",)
    assert result.attempted_requests == 1
    assert result.completed_requests == 0
    assert provider.fetch_count == 1


def test_capability_is_bound_to_exact_provider_and_request_key() -> None:
    provider = InjectedProvider()
    other_provider = InjectedProvider()
    capability = confirmed_capability(provider)

    result = execute_exactly_one_provider_request(
        capability,
        other_provider,
        (REQUEST,),
        now=NOW,
    )

    assert result.violations == ("capability_binding_mismatch",)
    assert result.capability_consumed is True
    assert provider.fetch_count == other_provider.fetch_count == 0


def test_capability_rejects_a_different_request_key_on_bound_provider() -> None:
    provider = InjectedProvider()
    capability = confirmed_capability(provider)
    other_request = AcquisitionRequest(
        entity_type=EntityType.WORK,
        source_id="synthetic-two",
    )

    result = execute_exactly_one_provider_request(
        capability,
        provider,
        (other_request,),
        now=NOW,
    )

    assert result.violations == ("capability_binding_mismatch",)
    assert result.capability_consumed is True
    assert provider.fetch_count == 0
