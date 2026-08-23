from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from pixiv_yuri.acquisition.safety import (
    AcquisitionDeferredError,
    AcquisitionSafetyController,
    AcquisitionStoppedError,
    StopReason,
)
from pixiv_yuri.governance.g0 import G0Approval
from tests.test_g0_governance import valid_approval_payload

NOW = datetime(2026, 8, 23, tzinfo=UTC)


def build_approval() -> G0Approval:
    return G0Approval.model_validate(valid_approval_payload())


def test_per_run_cap_stops_before_an_excess_request() -> None:
    payload = valid_approval_payload()
    limits = payload["traffic_limits"]
    assert isinstance(limits, dict)
    limits["per_run_request_cap"] = 2
    approval = G0Approval.model_validate(payload)
    controller = AcquisitionSafetyController(approval, now=NOW)

    first = controller.authorize_request(now=NOW)
    assert first.sequence == 1
    first_snapshot = controller.snapshot()
    assert first_snapshot.in_flight_requests == 1
    controller.record_transport_failure(first)
    second = controller.authorize_request(now=NOW)
    assert second.sequence == 2
    controller.record_transport_failure(second)
    with pytest.raises(AcquisitionStoppedError) as error:
        controller.authorize_request(now=NOW)

    assert error.value.reason is StopReason.PER_RUN_REQUEST_CAP
    assert controller.snapshot().run_requests == 2


@pytest.mark.parametrize(
    ("status_code", "expected_reason"),
    [(403, StopReason.REPEATED_403), (429, StopReason.REPEATED_429)],
)
def test_repeated_denial_or_rate_limit_opens_breaker(
    status_code: int,
    expected_reason: StopReason,
) -> None:
    controller = AcquisitionSafetyController(build_approval(), now=NOW)

    first = controller.authorize_request(now=NOW)
    controller.record_response(first, status_code)
    second = controller.authorize_request(now=NOW)
    controller.record_response(second, status_code)

    with pytest.raises(AcquisitionStoppedError) as error:
        controller.authorize_request(now=NOW)
    assert error.value.reason is expected_reason


def test_success_between_denials_resets_consecutive_counter() -> None:
    controller = AcquisitionSafetyController(build_approval(), now=NOW)
    for status_code in (403, 200, 403):
        permit = controller.authorize_request(now=NOW)
        controller.record_response(permit, status_code)

    assert controller.snapshot().stopped is False
    assert controller.snapshot().consecutive_403 == 1


def test_estimated_cost_is_reserved_before_transport() -> None:
    controller = AcquisitionSafetyController(build_approval(), now=NOW)
    permit = controller.authorize_request(now=NOW, estimated_cost=Decimal("6"))
    controller.record_response(permit, 200)

    with pytest.raises(AcquisitionStoppedError) as error:
        controller.authorize_request(now=NOW, estimated_cost=Decimal("5"))

    assert error.value.reason is StopReason.DAILY_COST_CAP
    assert controller.snapshot().daily_estimated_cost == Decimal("6")


def test_concurrency_limit_defers_before_reserving_another_request() -> None:
    controller = AcquisitionSafetyController(build_approval(), now=NOW)
    permit = controller.authorize_request(now=NOW)

    with pytest.raises(AcquisitionDeferredError):
        controller.authorize_request(now=NOW)
    assert controller.snapshot().run_requests == 1

    controller.record_transport_failure(permit)
    assert controller.authorize_request(now=NOW).sequence == 2


def test_schema_drift_and_manual_stop_are_fail_closed() -> None:
    schema_controller = AcquisitionSafetyController(build_approval(), now=NOW)
    schema_controller.signal_schema_drift()
    with pytest.raises(AcquisitionStoppedError) as schema_error:
        schema_controller.authorize_request(now=NOW)
    assert schema_error.value.reason is StopReason.SCHEMA_DRIFT

    manual_controller = AcquisitionSafetyController(build_approval(), now=NOW)
    manual_controller.stop_manually()
    with pytest.raises(AcquisitionStoppedError) as manual_error:
        manual_controller.authorize_request(now=NOW)
    assert manual_error.value.reason is StopReason.MANUAL


def test_expired_approval_stops_before_first_request() -> None:
    controller = AcquisitionSafetyController(
        build_approval(), now=datetime(2026, 10, 1, tzinfo=UTC)
    )

    with pytest.raises(AcquisitionStoppedError) as error:
        controller.authorize_request(now=datetime(2026, 10, 1, tzinfo=UTC))
    assert error.value.reason is StopReason.APPROVAL_INACTIVE
