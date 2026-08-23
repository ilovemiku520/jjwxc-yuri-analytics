from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from email.message import Message
from typing import IO, cast
from urllib.error import HTTPError
from urllib.request import Request

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from pixiv_yuri.acquisition.auth import SessionCapability
from pixiv_yuri.acquisition.external_transport import (
    ExternalSessionBroker,
    ExternalTransportError,
    PermitGuardedExternalTransport,
)
from pixiv_yuri.acquisition.operator_session import RuntimeSession
from pixiv_yuri.acquisition.persistence_models import (
    AcquisitionRequestPermit,
    AcquisitionRunBudget,
)
from pixiv_yuri.acquisition.persistent_safety import PersistentAcquisitionSafety
from pixiv_yuri.governance.g0 import G0Approval
from pixiv_yuri.ingest.models import CrawlRun
from pixiv_yuri.shared.database import Base
from tests.test_g0_governance import valid_approval_payload

NOW = datetime(2026, 8, 23, tzinfo=UTC)
ALLOWED_HOST = "metadata.pixiv.test"
SYNTHETIC_CREDENTIAL = "session=synthetic-never-persist"


class FakeResponse:
    def __init__(
        self,
        *,
        status: int = 200,
        body: bytes = b'{"work_id":"42"}',
        headers: list[tuple[str, str]] | None = None,
    ) -> None:
        self.status = status
        self._body = body
        self.headers = Message()
        for key, value in headers or [("Content-Type", "application/json")]:
            self.headers.add_header(key, value)
        self.closed = False

    def read(self, amount: int = -1) -> bytes:
        return self._body[:amount] if amount >= 0 else self._body

    def close(self) -> None:
        self.closed = True

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object,
    ) -> None:
        self.close()


class FakeOpener:
    def __init__(
        self,
        response: FakeResponse | None = None,
        *,
        failure: Exception | None = None,
    ) -> None:
        self.response = response or FakeResponse()
        self.failure = failure
        self.requests: list[Request] = []
        self.timeouts: list[float] = []

    def __call__(self, request: Request, timeout_seconds: float) -> FakeResponse:
        self.requests.append(request)
        self.timeouts.append(timeout_seconds)
        if self.failure is not None:
            raise self.failure
        return self.response


class SequenceClock:
    def __init__(self, *values: datetime) -> None:
        self._values = iter(values)
        self.calls = 0

    def __call__(self) -> datetime:
        self.calls += 1
        return next(self._values)


class LeakingStream:
    def read(self, amount: int = -1) -> bytes:
        raise OSError("body-secret session=leaked")

    def close(self) -> None:
        raise OSError("close-secret Authorization: leaked")


class LeakingHeaders:
    def items(self) -> list[tuple[str, str]]:
        raise ExternalTransportError("header-object-secret session=leaked")


class LeakingHeaderResponse(FakeResponse):
    def __init__(self) -> None:
        super().__init__()
        self.headers = LeakingHeaders()  # type: ignore[assignment]


def build_safety() -> tuple[PersistentAcquisitionSafety, sessionmaker[Session]]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        execution_options={"schema_translate_map": {"ingest": None}},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory.begin() as session:
        run = CrawlRun(
            run_type="external_transport_test",
            provider="host_pinned_external",
            status="running",
            config_snapshot={"network_scope": "fake_opener_only"},
            requested_by="test",
        )
        session.add(run)
        session.flush()
        run_id = run.id
    approval = G0Approval.model_validate(valid_approval_payload())
    safety = PersistentAcquisitionSafety(factory, approval, run_id)
    safety.initialize(now=NOW)
    return safety, factory


def build_transport(
    opener: FakeOpener,
    *,
    supplier: object | None = None,
    max_body_bytes: int = 1_000_000,
    capability: SessionCapability | None = None,
    clock: Callable[[], datetime] | None = None,
) -> tuple[PermitGuardedExternalTransport, sessionmaker[Session]]:
    safety, factory = build_safety()
    capability = capability or SessionCapability(
        established_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=5),
        allowed_age_ratings=frozenset({"all_ages", "r18", "r18g"}),
    )
    credential_supplier = supplier if callable(supplier) else lambda: SYNTHETIC_CREDENTIAL
    broker = ExternalSessionBroker(
        capability,
        credential_supplier,
        allowed_hosts=frozenset({ALLOWED_HOST}),
        max_body_bytes=max_body_bytes,
        open_request=opener,
    )
    return PermitGuardedExternalTransport(safety, broker, clock=clock), factory


def test_allowed_https_request_uses_ephemeral_credential_and_sanitizes_response() -> None:
    opener = FakeOpener(
        FakeResponse(
            headers=[
                ("content-type", "application/json"),
                ("Set-Cookie", "response-secret=1"),
                ("WWW-Authenticate", "Bearer realm=secret"),
                ("X-Api-Token", "response-token"),
                ("Location", "https://elsewhere.test/?token=hidden"),
                ("X-Safe", "visible"),
            ]
        )
    )
    transport, factory = build_transport(opener)

    response = transport.fetch(
        f"https://{ALLOWED_HOST}:443/ajax/illust/42",
        timeout_seconds=2,
        now=NOW,
    )

    assert response.status_code == 200
    assert response.content_type == "application/json"
    assert response.headers == {"content-type": "application/json", "X-Safe": "visible"}
    assert len(opener.requests) == 1
    assert opener.requests[0].get_header("Cookie") == SYNTHETIC_CREDENTIAL
    assert opener.timeouts == [2]
    assert SYNTHETIC_CREDENTIAL not in repr(transport)
    with factory() as session:
        permit = session.scalar(select(AcquisitionRequestPermit))
        assert permit is not None and permit.status == "consumed"
        assert permit.response_status == 200
        assert permit.request_key_hash is not None
        assert "work:42" not in permit.request_key_hash


def test_runtime_session_supplier_binds_one_exact_lease_and_one_fake_send() -> None:
    opener = FakeOpener()
    capability = SessionCapability(
        established_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=5),
        allowed_age_ratings=frozenset({"all_ages", "r18", "r18g"}),
    )
    runtime_session = RuntimeSession(
        bytearray(SYNTHETIC_CREDENTIAL.encode()),
        capability.expires_at,
        established_at=capability.established_at,
        allowed_age_ratings=capability.allowed_age_ratings,
    )
    broker = ExternalSessionBroker(
        capability,
        runtime_session,
        allowed_hosts=frozenset({ALLOWED_HOST}),
        open_request=opener,
    )

    response = broker.fetch(
        f"https://{ALLOWED_HOST}/works/42",
        timeout_seconds=1,
        now=NOW,
    )

    assert response.status_code == 200
    assert broker.runtime_session_lease is runtime_session.runtime_session_lease
    assert len(opener.requests) == 1
    with pytest.raises(ExternalTransportError, match="credential is unavailable"):
        broker.fetch(
            f"https://{ALLOWED_HOST}/works/43",
            timeout_seconds=1,
            now=NOW,
        )
    assert len(opener.requests) == 1


@pytest.mark.parametrize(
    "url",
    [
        "http://metadata.pixiv.test/path",
        "https://metadata.pixiv.test:444/path",
        "https://metadata.pixiv.test.evil.test/path",
        "https://user:password@metadata.pixiv.test/path",
        "https://metadata.pixiv.test/path#fragment",
        "https://127.0.0.1/path",
    ],
)
def test_disallowed_url_consumes_permit_before_supplier_or_opener(url: str) -> None:
    supplied = False

    def supplier() -> str:
        nonlocal supplied
        supplied = True
        return SYNTHETIC_CREDENTIAL

    opener = FakeOpener()
    transport, factory = build_transport(opener, supplier=supplier)

    with pytest.raises(ExternalTransportError, match="not permitted") as captured:
        transport.fetch(
            url,
            timeout_seconds=1,
            now=NOW,
        )

    assert supplied is False
    assert opener.requests == []
    assert "password" not in str(captured.value)
    with factory() as session:
        permit = session.scalar(select(AcquisitionRequestPermit))
        run_budget = session.scalar(select(AcquisitionRunBudget))
        assert permit is not None and permit.status == "transport_failed"
        assert run_budget is not None and run_budget.request_count == 1
        assert run_budget.in_flight_count == 0


def test_oversized_body_fails_closed_and_consumes_permit() -> None:
    opener = FakeOpener(FakeResponse(body=b"12345"))
    transport, factory = build_transport(opener, max_body_bytes=4)

    with pytest.raises(ExternalTransportError, match="size limit"):
        transport.fetch(
            f"https://{ALLOWED_HOST}/large",
            timeout_seconds=1,
            now=NOW,
        )

    assert opener.response.closed is True
    with factory() as session:
        permit = session.scalar(select(AcquisitionRequestPermit))
        assert permit is not None and permit.status == "transport_failed"


def test_transport_exception_and_repr_do_not_disclose_url_or_credentials() -> None:
    opener = FakeOpener(failure=OSError("socket failed: synthetic-never-persist"))
    transport, factory = build_transport(opener)
    secret_url = f"https://{ALLOWED_HOST}/path/url-secret"

    with pytest.raises(ExternalTransportError, match="HTTPS transport failed") as captured:
        transport.fetch(
            secret_url,
            timeout_seconds=1,
            now=NOW,
        )

    message = str(captured.value)
    assert "synthetic-never-persist" not in message
    assert "url-secret" not in message
    assert captured.value.__cause__ is None
    assert SYNTHETIC_CREDENTIAL not in repr(transport)
    with factory() as session:
        permit = session.scalar(select(AcquisitionRequestPermit))
        assert permit is not None and permit.status == "transport_failed"


def test_each_reached_transport_phase_reads_a_fresh_clock_value() -> None:
    clock = SequenceClock(
        NOW,
        NOW + timedelta(seconds=1),
        NOW + timedelta(seconds=2),
        NOW + timedelta(seconds=3),
    )
    transport, factory = build_transport(FakeOpener(), clock=clock)

    transport.fetch(f"https://{ALLOWED_HOST}/phase-clock", timeout_seconds=1)

    assert clock.calls == 4
    with factory() as session:
        permit = session.scalar(select(AcquisitionRequestPermit))
        assert permit is not None
        assert permit.authorized_at.replace(tzinfo=UTC) == NOW
        assert permit.consumed_at is not None
        assert permit.consumed_at.replace(tzinfo=UTC) == NOW + timedelta(seconds=3)


def test_session_expiry_is_rechecked_immediately_before_fake_send() -> None:
    capability = SessionCapability(
        established_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(seconds=2),
        allowed_age_ratings=frozenset({"all_ages", "r18", "r18g"}),
    )
    clock = SequenceClock(
        NOW,
        NOW + timedelta(seconds=1),
        NOW + timedelta(seconds=3),
        NOW + timedelta(seconds=4),
    )
    opener = FakeOpener()
    transport, factory = build_transport(
        opener,
        capability=capability,
        clock=clock,
    )

    with pytest.raises(ExternalTransportError, match="send was not permitted"):
        transport.fetch(f"https://{ALLOWED_HOST}/expires-before-send", timeout_seconds=1)

    assert opener.requests == []
    assert clock.calls == 4
    with factory() as session:
        permit = session.scalar(select(AcquisitionRequestPermit))
        assert permit is not None and permit.status == "transport_failed"
        assert permit.consumed_at is not None
        assert permit.consumed_at.replace(tzinfo=UTC) == NOW + timedelta(seconds=4)


def test_http_error_read_and_close_failures_are_fully_sanitized() -> None:
    secret_url = f"https://{ALLOWED_HOST}/private?token=query-secret"
    headers = Message()
    headers.add_header("Authorization", "header-secret")
    http_error = HTTPError(
        secret_url,
        403,
        "session-secret",
        headers,
        cast(IO[bytes], LeakingStream()),
    )
    transport, factory = build_transport(FakeOpener(failure=http_error))

    with pytest.raises(ExternalTransportError) as captured:
        transport.fetch(
            f"https://{ALLOWED_HOST}/http-error",
            timeout_seconds=1,
            now=NOW,
        )

    rendered = f"{captured.value!s} {captured.value!r}"
    for secret in (
        "query-secret",
        "header-secret",
        "body-secret",
        "close-secret",
        "session-secret",
        "Authorization",
    ):
        assert secret not in rendered
    assert captured.value.__cause__ is None
    with factory() as session:
        permit = session.scalar(select(AcquisitionRequestPermit))
        assert permit is not None and permit.status == "transport_failed"


def test_untrusted_response_exception_type_cannot_smuggle_header_text() -> None:
    transport, factory = build_transport(FakeOpener(LeakingHeaderResponse()))

    with pytest.raises(ExternalTransportError) as captured:
        transport.fetch(
            f"https://{ALLOWED_HOST}/hostile-headers",
            timeout_seconds=1,
            now=NOW,
        )

    rendered = f"{captured.value!s} {captured.value!r}"
    assert "header-object-secret" not in rendered
    assert "session=leaked" not in rendered
    with factory() as session:
        permit = session.scalar(select(AcquisitionRequestPermit))
        assert permit is not None and permit.status == "transport_failed"


def test_settlement_exception_is_replaced_by_payload_free_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport, _ = build_transport(FakeOpener())

    def fail_settlement(*args: object, **kwargs: object) -> None:
        raise RuntimeError(
            "https://secret.test/?token=query-secret Authorization=header-secret "
            "body-secret session-secret"
        )

    monkeypatch.setattr(transport._safety, "record_response", fail_settlement)

    with pytest.raises(ExternalTransportError, match="permit settlement failed") as captured:
        transport.fetch(
            f"https://{ALLOWED_HOST}/settlement",
            timeout_seconds=1,
            now=NOW,
        )

    rendered = f"{captured.value!s} {captured.value!r}"
    for secret in (
        "secret.test",
        "query-secret",
        "header-secret",
        "body-secret",
        "session-secret",
    ):
        assert secret not in rendered
    assert captured.value.__cause__ is None


def test_failure_settlement_exception_also_replaces_the_primary_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport, _ = build_transport(
        FakeOpener(failure=OSError("socket body-secret session-secret"))
    )

    def fail_settlement(*args: object, **kwargs: object) -> None:
        raise RuntimeError("settlement query-secret Authorization=header-secret")

    monkeypatch.setattr(transport._safety, "record_transport_failure", fail_settlement)

    with pytest.raises(ExternalTransportError, match="permit settlement failed") as captured:
        transport.fetch(
            f"https://{ALLOWED_HOST}/failure-settlement",
            timeout_seconds=1,
            now=NOW,
        )

    rendered = f"{captured.value!s} {captured.value!r}"
    for secret in (
        "body-secret",
        "session-secret",
        "query-secret",
        "header-secret",
    ):
        assert secret not in rendered


def test_supplier_exception_is_sanitized_before_opener_and_consumes_permit() -> None:
    def supplier() -> str:
        raise RuntimeError("credential supplier leaked synthetic-never-persist")

    opener = FakeOpener()
    transport, factory = build_transport(opener, supplier=supplier)

    with pytest.raises(ExternalTransportError, match="credential is unavailable") as captured:
        transport.fetch(
            f"https://{ALLOWED_HOST}/supplier-failure",
            timeout_seconds=1,
            now=NOW,
        )

    assert "synthetic-never-persist" not in str(captured.value)
    assert captured.value.__cause__ is None
    assert opener.requests == []
    with factory() as session:
        permit = session.scalar(select(AcquisitionRequestPermit))
        assert permit is not None and permit.status == "transport_failed"


def test_invalid_response_status_fails_before_persistent_response_recording() -> None:
    opener = FakeOpener(FakeResponse(status=700))
    transport, factory = build_transport(opener)

    with pytest.raises(ExternalTransportError, match="status is invalid"):
        transport.fetch(
            f"https://{ALLOWED_HOST}/invalid-status",
            timeout_seconds=1,
            now=NOW,
        )

    with factory() as session:
        permit = session.scalar(select(AcquisitionRequestPermit))
        assert permit is not None and permit.status == "transport_failed"


def test_redirect_response_is_not_followed_and_location_is_removed() -> None:
    opener = FakeOpener(
        FakeResponse(
            status=302,
            body=b"",
            headers=[
                ("Location", "https://unapproved.test/path?token=secret"),
                ("Content-Type", "text/plain"),
            ],
        )
    )
    transport, factory = build_transport(opener)

    response = transport.fetch(
        f"https://{ALLOWED_HOST}/redirect",
        timeout_seconds=1,
        now=NOW,
    )

    assert response.status_code == 302
    assert len(opener.requests) == 1
    assert all(key.lower() != "location" for key in response.headers)
    with factory() as session:
        permit = session.scalar(select(AcquisitionRequestPermit))
        assert permit is not None and permit.response_status == 302


@pytest.mark.parametrize(
    "host",
    ["", "*.pixiv.test", "127.0.0.1", "metadata.pixiv.test.", "bad_host.test"],
)
def test_host_pins_must_be_exact_ascii_dns_names(host: str) -> None:
    capability = SessionCapability(
        established_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=5),
        allowed_age_ratings=frozenset({"all_ages"}),
    )

    with pytest.raises(ValueError, match="host|Host"):
        ExternalSessionBroker(
            capability,
            lambda: SYNTHETIC_CREDENTIAL,
            allowed_hosts=frozenset({host}),
            open_request=FakeOpener(),
        )
