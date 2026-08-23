from __future__ import annotations

import copy
import pickle
import threading
from datetime import UTC, datetime, timedelta

import pytest

from pixiv_yuri.acquisition.runtime_session_lease import (
    AgeRating,
    RuntimeSessionLease,
    RuntimeSessionLeaseError,
    RuntimeSessionLeaseState,
    require_same_runtime_session_lease,
)

NOW = datetime(2026, 8, 23, tzinfo=UTC)
RATINGS: frozenset[AgeRating] = frozenset({"all_ages", "r18", "r18g"})


def new_lease() -> RuntimeSessionLease:
    return RuntimeSessionLease(
        established_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
        allowed_age_ratings=RATINGS,
    )


def test_scope_is_deeply_immutable_and_contains_no_material() -> None:
    lease = new_lease()

    assert lease.allowed_age_ratings == frozenset(RATINGS)
    assert isinstance(lease.allowed_age_ratings, frozenset)
    assert "cookie" not in repr(lease).lower()
    assert "password" not in repr(lease).lower()
    assert "token" not in repr(lease).lower()
    with pytest.raises(AttributeError):
        lease.allowed_age_ratings.add("all_ages")  # type: ignore[attr-defined]


def test_same_public_values_create_distinct_non_secret_identities() -> None:
    first = new_lease()
    second = new_lease()

    assert first.lease_id != second.lease_id
    assert first.expires_at == second.expires_at
    assert first.allowed_age_ratings == second.allowed_age_ratings
    assert require_same_runtime_session_lease(first, first) is first
    with pytest.raises(RuntimeSessionLeaseError, match="identity"):
        require_same_runtime_session_lease(first, second)


def test_lease_cannot_be_copied_or_serialized() -> None:
    lease = new_lease()

    with pytest.raises(TypeError, match="copied"):
        copy.copy(lease)
    with pytest.raises(TypeError, match="copied"):
        copy.deepcopy(lease)
    with pytest.raises(TypeError, match="serialized"):
        pickle.dumps(lease)


def test_consume_is_one_use_and_returns_non_authorizing_identity_evidence() -> None:
    lease = new_lease()

    receipt = lease.consume(
        now=NOW + timedelta(seconds=1),
        required_age_ratings=RATINGS,
    )

    assert receipt.lease_id == lease.lease_id
    assert receipt.expires_at == lease.expires_at
    assert lease.state == RuntimeSessionLeaseState.CONSUMED
    with pytest.raises(RuntimeSessionLeaseError, match="unavailable"):
        lease.consume(now=NOW + timedelta(seconds=2), required_age_ratings=RATINGS)


def test_concurrent_consumers_allow_exactly_one_success() -> None:
    lease = new_lease()
    barrier = threading.Barrier(8, timeout=2)
    result_lock = threading.Lock()
    successes = 0
    denials = 0

    def consume() -> None:
        nonlocal successes, denials
        barrier.wait()
        try:
            lease.consume(now=NOW, required_age_ratings=RATINGS)
        except RuntimeSessionLeaseError:
            with result_lock:
                denials += 1
        else:
            with result_lock:
                successes += 1

    threads = [threading.Thread(target=consume) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)

    assert all(not thread.is_alive() for thread in threads)
    assert successes == 1
    assert denials == 7
    assert lease.state == RuntimeSessionLeaseState.CONSUMED


def test_expiry_burns_lease_and_clock_rollback_cannot_reactivate_it() -> None:
    lease = new_lease()

    with pytest.raises(RuntimeSessionLeaseError, match="inactive"):
        lease.consume(
            now=lease.expires_at,
            required_age_ratings=RATINGS,
        )

    assert lease.state == RuntimeSessionLeaseState.BURNED
    with pytest.raises(RuntimeSessionLeaseError, match="unavailable"):
        lease.consume(now=NOW, required_age_ratings=RATINGS)


def test_insufficient_scope_burns_send_opportunity() -> None:
    lease = RuntimeSessionLease(
        established_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
        allowed_age_ratings=frozenset({"all_ages"}),
    )

    with pytest.raises(RuntimeSessionLeaseError, match="scope"):
        lease.consume(
            now=NOW,
            required_age_ratings=frozenset({"all_ages", "r18"}),
        )

    assert lease.state == RuntimeSessionLeaseState.BURNED


def test_explicit_burn_is_idempotent_and_terminal() -> None:
    lease = new_lease()

    lease.burn()
    lease.burn()

    assert lease.state == RuntimeSessionLeaseState.BURNED
    with pytest.raises(RuntimeSessionLeaseError, match="unavailable"):
        lease.consume(now=NOW, required_age_ratings=RATINGS)


def test_naive_timestamps_are_rejected() -> None:
    naive = datetime(2026, 8, 23)
    with pytest.raises(ValueError, match="timezone"):
        RuntimeSessionLease(
            established_at=naive,
            expires_at=NOW + timedelta(minutes=5),
            allowed_age_ratings=RATINGS,
        )

    lease = new_lease()
    with pytest.raises(ValueError, match="timezone"):
        lease.ensure_active(now=naive)
    with pytest.raises(ValueError, match="timezone"):
        lease.consume(now=naive, required_age_ratings=RATINGS)
    assert lease.state.value == RuntimeSessionLeaseState.ACTIVE.value


def test_readiness_check_does_not_consume_but_burns_inactive_window() -> None:
    lease = new_lease()

    lease.ensure_active(now=NOW)
    assert lease.state.value == RuntimeSessionLeaseState.ACTIVE.value

    with pytest.raises(RuntimeSessionLeaseError, match="inactive"):
        lease.ensure_active(now=NOW - timedelta(seconds=1))
    assert lease.state.value == RuntimeSessionLeaseState.BURNED.value
