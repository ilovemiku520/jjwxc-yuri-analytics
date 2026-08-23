from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from pixiv_yuri.governance.real_request_enablement import (
    EXPLICIT_ACKNOWLEDGEMENT,
    ExplicitRealRequestEnablement,
    RealRequestDeniedError,
    RealRequestDeniedReason,
    RealRequestEnablementConfig,
    RealRequestEnablementState,
)

NOW = datetime(2026, 8, 23, tzinfo=UTC)
FINGERPRINT = "a" * 64
REQUEST_HASH = "b" * 64


def armed_config() -> RealRequestEnablementConfig:
    return RealRequestEnablementConfig(
        mode="first_real_request",
        planned_requests=1,
        approval_fingerprint=FINGERPRINT,
        run_id=42,
        request_key_hash=REQUEST_HASH,
        enabled_at=NOW,
        expires_at=NOW + timedelta(seconds=60),
        acknowledgement=EXPLICIT_ACKNOWLEDGEMENT,
    )


def test_default_configuration_is_inert_and_denies_consumption() -> None:
    config = RealRequestEnablementConfig()
    enablement = ExplicitRealRequestEnablement(config)

    assert config.mode == "disabled"
    assert config.approval_fingerprint is None
    assert config.run_id is None
    assert config.request_key_hash is None
    assert enablement.snapshot(now=NOW).state == RealRequestEnablementState.DISABLED
    with pytest.raises(RealRequestDeniedError) as caught:
        enablement.consume(
            approval_fingerprint=FINGERPRINT,
            run_id=42,
            request_key_hash=REQUEST_HASH,
            now=NOW,
        )
    assert caught.value.reason == RealRequestDeniedReason.NOT_ARMED


def test_configuration_forbids_credential_shaped_extra_fields() -> None:
    with pytest.raises(ValidationError, match="password"):
        RealRequestEnablementConfig.model_validate({"password": "must-not-be-accepted"})

    field_names = set(RealRequestEnablementConfig.model_fields)
    for fragment in ("password", "cookie", "credential", "session", "token"):
        assert all(fragment not in field_name.lower() for field_name in field_names)


@pytest.mark.parametrize(
    "change",
    [
        {"approval_fingerprint": None},
        {"run_id": None},
        {"request_key_hash": None},
        {"acknowledgement": None},
        {"expires_at": NOW + timedelta(seconds=121)},
    ],
)
def test_armed_configuration_requires_complete_short_lived_binding(
    change: dict[str, object],
) -> None:
    payload = armed_config().model_dump()
    payload.update(change)

    with pytest.raises(ValidationError):
        RealRequestEnablementConfig.model_validate(payload)


def test_exact_binding_consumes_once_and_never_rearms() -> None:
    enablement = ExplicitRealRequestEnablement(armed_config())

    receipt = enablement.consume(
        approval_fingerprint=FINGERPRINT,
        run_id=42,
        request_key_hash=REQUEST_HASH,
        now=NOW + timedelta(seconds=1),
    )

    assert receipt.state == "consumed"
    assert receipt.planned_requests == 1
    assert enablement.snapshot(now=NOW + timedelta(seconds=2)).state == (
        RealRequestEnablementState.CONSUMED
    )
    with pytest.raises(RealRequestDeniedError) as caught:
        enablement.consume(
            approval_fingerprint=FINGERPRINT,
            run_id=42,
            request_key_hash=REQUEST_HASH,
            now=NOW + timedelta(seconds=2),
        )
    assert caught.value.reason == RealRequestDeniedReason.ALREADY_TERMINAL


def test_binding_mismatch_burns_enablement_without_disclosing_values() -> None:
    enablement = ExplicitRealRequestEnablement(armed_config())

    with pytest.raises(RealRequestDeniedError) as caught:
        enablement.consume(
            approval_fingerprint=FINGERPRINT,
            run_id=99,
            request_key_hash=REQUEST_HASH,
            now=NOW,
        )

    assert caught.value.reason == RealRequestDeniedReason.BINDING_MISMATCH
    assert "99" not in str(caught.value)
    assert enablement.snapshot(now=NOW).state == RealRequestEnablementState.REJECTED


@pytest.mark.parametrize("candidate", ["é" * 64, "B" * 64, "not-hex".ljust(64, "x")])
def test_invalid_candidate_hash_fails_closed_and_burns(candidate: str) -> None:
    enablement = ExplicitRealRequestEnablement(armed_config())

    with pytest.raises(RealRequestDeniedError) as caught:
        enablement.consume(
            approval_fingerprint=FINGERPRINT,
            run_id=42,
            request_key_hash=candidate,
            now=NOW,
        )

    assert caught.value.reason == RealRequestDeniedReason.BINDING_MISMATCH
    assert enablement.snapshot(now=NOW).state == RealRequestEnablementState.REJECTED


def test_consumption_before_enabled_at_is_rejected_and_burned() -> None:
    enablement = ExplicitRealRequestEnablement(armed_config())

    with pytest.raises(RealRequestDeniedError) as caught:
        enablement.consume(
            approval_fingerprint=FINGERPRINT,
            run_id=42,
            request_key_hash=REQUEST_HASH,
            now=NOW - timedelta(microseconds=1),
        )

    assert caught.value.reason == RealRequestDeniedReason.NOT_ACTIVE_YET
    assert enablement.snapshot(now=NOW).state == RealRequestEnablementState.REJECTED


def test_expired_and_cancelled_enablements_are_terminal() -> None:
    expired = ExplicitRealRequestEnablement(armed_config())
    assert expired.snapshot(now=NOW + timedelta(seconds=60)).state == (
        RealRequestEnablementState.EXPIRED
    )

    cancelled = ExplicitRealRequestEnablement(armed_config())
    cancelled.cancel(now=NOW)
    assert cancelled.snapshot(now=NOW).state == RealRequestEnablementState.CANCELLED
    with pytest.raises(RealRequestDeniedError) as caught:
        cancelled.consume(
            approval_fingerprint=FINGERPRINT,
            run_id=42,
            request_key_hash=REQUEST_HASH,
            now=NOW,
        )
    assert caught.value.reason == RealRequestDeniedReason.ALREADY_TERMINAL


def test_concurrent_consumers_produce_exactly_one_receipt() -> None:
    enablement = ExplicitRealRequestEnablement(armed_config())
    barrier = threading.Barrier(8, timeout=2)
    lock = threading.Lock()
    receipts = 0
    denials = 0

    def consume() -> None:
        nonlocal receipts, denials
        barrier.wait()
        try:
            enablement.consume(
                approval_fingerprint=FINGERPRINT,
                run_id=42,
                request_key_hash=REQUEST_HASH,
                now=NOW,
            )
        except RealRequestDeniedError:
            with lock:
                denials += 1
        else:
            with lock:
                receipts += 1

    threads = [threading.Thread(target=consume) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)

    assert receipts == 1
    assert denials == 7
    assert all(not thread.is_alive() for thread in threads)
