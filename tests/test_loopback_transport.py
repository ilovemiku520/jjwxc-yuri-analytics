from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from pixiv_yuri.acquisition.auth import SessionCapability
from pixiv_yuri.acquisition.loopback_transport import (
    LoopbackSessionBroker,
    LoopbackTransportError,
    PermitGuardedLoopbackTransport,
)
from pixiv_yuri.acquisition.persistence_models import (
    AcquisitionRequestPermit,
    AcquisitionRunBudget,
)
from pixiv_yuri.acquisition.persistent_safety import PersistentAcquisitionSafety
from pixiv_yuri.acquisition.safety import AcquisitionStoppedError
from pixiv_yuri.governance.g0 import G0Approval
from pixiv_yuri.ingest.models import CrawlRun
from pixiv_yuri.shared.database import Base
from tests.test_g0_governance import valid_approval_payload

NOW = datetime(2026, 8, 23, tzinfo=UTC)
SYNTHETIC_COOKIE = "session=synthetic-runtime-secret"


class LocalHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/slow":
            time.sleep(0.1)
        status = 403 if self.path.startswith("/forbidden") else 200
        body = json.dumps(
            {
                "authenticated": self.headers.get("Cookie") == SYNTHETIC_COOKIE,
                "path": self.path,
            }
        ).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Set-Cookie", "should-not-escape=1")
        self.send_header("X-Safe", "visible")
        self.end_headers()
        with suppress(BrokenPipeError):
            self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


@contextmanager
def local_server() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), LocalHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


def build_transport() -> tuple[
    PermitGuardedLoopbackTransport, sessionmaker[Session], PersistentAcquisitionSafety
]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        execution_options={"schema_translate_map": {"ingest": None}},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory.begin() as session:
        run = CrawlRun(
            run_type="loopback_transport_test",
            provider="loopback",
            status="running",
            config_snapshot={"network_scope": "numeric_loopback_only"},
            requested_by="test",
        )
        session.add(run)
        session.flush()
        run_id = run.id
    approval = G0Approval.model_validate(valid_approval_payload())
    safety = PersistentAcquisitionSafety(factory, approval, run_id)
    safety.initialize(now=NOW)
    capability = SessionCapability(
        established_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=5),
        allowed_age_ratings=frozenset({"all_ages", "r18", "r18g"}),
    )
    broker = LoopbackSessionBroker(capability, lambda: SYNTHETIC_COOKIE)
    return PermitGuardedLoopbackTransport(safety, broker), factory, safety


def test_cookie_is_applied_but_never_returned() -> None:
    transport, _, _ = build_transport()
    with local_server() as base_url:
        response = transport.fetch(f"{base_url}/ok", timeout_seconds=1, now=NOW)

    assert json.loads(response.body)["authenticated"] is True
    assert response.headers["X-Safe"] == "visible"
    assert all("cookie" not in key.lower() for key in response.headers)
    assert "synthetic-runtime-secret" not in repr(response)


def test_external_host_is_rejected_without_calling_secret_supplier() -> None:
    _, factory, safety = build_transport()
    supplied = False

    def supplier() -> str:
        nonlocal supplied
        supplied = True
        return SYNTHETIC_COOKIE

    capability = SessionCapability(
        established_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=5),
        allowed_age_ratings=frozenset({"all_ages"}),
    )
    transport = PermitGuardedLoopbackTransport(
        safety, LoopbackSessionBroker(capability, supplier)
    )
    with pytest.raises(LoopbackTransportError, match="loopback"):
        transport.fetch("https://example.com/", timeout_seconds=1, now=NOW)

    assert supplied is False
    with factory() as session:
        permit = session.scalar(select(AcquisitionRequestPermit))
        assert permit is not None and permit.status == "transport_failed"


def test_timeout_consumes_permit_without_refund() -> None:
    transport, factory, _ = build_transport()
    with (
        local_server() as base_url,
        pytest.raises(LoopbackTransportError, match="Local transport failed"),
    ):
        transport.fetch(f"{base_url}/slow", timeout_seconds=0.01, now=NOW)

    with factory() as session:
        permit = session.scalar(select(AcquisitionRequestPermit))
        run_budget = session.scalar(select(AcquisitionRunBudget))
        assert permit is not None and permit.status == "transport_failed"
        assert run_budget is not None and run_budget.request_count == 1
        assert run_budget.in_flight_count == 0


def test_two_forbidden_responses_trip_persistent_breaker() -> None:
    transport, _, _ = build_transport()
    with local_server() as base_url:
        first = transport.fetch(f"{base_url}/forbidden?request=1", timeout_seconds=1, now=NOW)
        second = transport.fetch(
            f"{base_url}/forbidden?request=2",
            timeout_seconds=1,
            now=NOW + timedelta(seconds=1),
        )
        assert first.status_code == second.status_code == 403
        with pytest.raises(AcquisitionStoppedError, match="repeated_403"):
            transport.fetch(
                f"{base_url}/ok", timeout_seconds=1, now=NOW + timedelta(seconds=2)
            )


def test_redirect_is_not_followed() -> None:
    class RedirectHandler(LocalHandler):
        def do_GET(self) -> None:
            self.send_response(302)
            self.send_header("Location", "https://example.com/")
            self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        transport, _, _ = build_transport()
        response = transport.fetch(
            f"http://127.0.0.1:{server.server_port}/redirect",
            timeout_seconds=1,
            now=NOW,
        )
        assert response.status_code == 302
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)
