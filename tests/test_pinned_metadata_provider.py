from __future__ import annotations

import json
import threading
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from pixiv_yuri.acquisition.auth import SessionCapability
from pixiv_yuri.acquisition.external_transport import (
    ExternalSessionBroker,
    PermitGuardedExternalTransport,
)
from pixiv_yuri.acquisition.live_request_binding import CanonicalLiveRequestBinding
from pixiv_yuri.acquisition.loopback_transport import (
    LoopbackSessionBroker,
    PermitGuardedLoopbackTransport,
)
from pixiv_yuri.acquisition.models import AcquisitionRequest, EntityType
from pixiv_yuri.acquisition.persistence_models import (
    AcquisitionRequestPermit,
    AcquisitionRunBudget,
    AcquisitionStopEvent,
)
from pixiv_yuri.acquisition.persistent_safety import PersistentAcquisitionSafety
from pixiv_yuri.acquisition.providers.pinned_metadata import (
    MetadataPolicyError,
    MetadataPolicyReason,
    PinnedMetadataProvider,
)
from pixiv_yuri.acquisition.transport_contract import derive_transport_request_key
from pixiv_yuri.governance.g0 import G0Approval
from pixiv_yuri.ingest.models import CrawlRun
from pixiv_yuri.shared.database import Base
from tests.test_external_transport import ALLOWED_HOST, FakeOpener, FakeResponse
from tests.test_g0_governance import valid_approval_payload

NOW = datetime(2026, 8, 23, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class KnownMetadataResponse:
    status_code: int
    body: bytes
    headers: Mapping[str, str]


PAYLOADS: dict[str, tuple[int, dict[str, object]]] = {
    "/works/ok": (
        200,
        {
            "work_id": "ok",
            "work_title": "Synthetic work",
            "public_tags": ["synthetic", "yuri"],
            "width": 1000,
            "height": 800,
        },
    ),
    "/works/drift": (200, {"work_id": "drift", "unexpected_field": "not-approved"}),
    "/works/secret": (200, {"work_id": "secret", "csrf_token": "must-not-propagate"}),
    "/works/missing": (200, {"work_title": "Missing identity"}),
    "/works/forbidden": (403, {"session_token": "must-be-discarded"}),
}


class MetadataHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        status, payload = PAYLOADS.get(self.path, (404, {}))
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


@contextmanager
def metadata_server() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), MetadataHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


def build_safety() -> tuple[
    G0Approval, PersistentAcquisitionSafety, sessionmaker[Session]
]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        execution_options={"schema_translate_map": {"ingest": None}},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory.begin() as session:
        run = CrawlRun(
            run_type="pinned_metadata_contract",
            provider="pinned_metadata_local_contract",
            status="running",
            config_snapshot={"origin_kind": "numeric_loopback"},
            requested_by="test",
        )
        session.add(run)
        session.flush()
        run_id = run.id
    approval = G0Approval.model_validate(valid_approval_payload())
    safety = PersistentAcquisitionSafety(factory, approval, run_id)
    safety.initialize(now=NOW)
    return approval, safety, factory


def build_provider(
    origin: str, *source_ids: str
) -> tuple[PinnedMetadataProvider, sessionmaker[Session]]:
    approval, safety, factory = build_safety()
    transport = build_loopback_transport(safety)

    requests = tuple(
        AcquisitionRequest(entity_type=EntityType.WORK, source_id=source_id)
        for source_id in source_ids
    )
    return (
        PinnedMetadataProvider(
            origin,
            requests,
            transport,
            approval,
            clock=lambda: NOW,
        ),
        factory,
    )


def build_loopback_transport(
    safety: PersistentAcquisitionSafety,
) -> PermitGuardedLoopbackTransport:
    capability = SessionCapability(
        established_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=5),
        allowed_age_ratings=frozenset({"all_ages", "r18", "r18g"}),
    )
    return PermitGuardedLoopbackTransport(
        safety,
        LoopbackSessionBroker(capability, lambda: "session=synthetic-contract"),
    )


def test_approved_payload_is_minimized_and_canonicalized() -> None:
    with metadata_server() as origin:
        provider, factory = build_provider(origin, "ok")
        response = provider.fetch(provider.list_requests()[0])

    assert response.json_value() == PAYLOADS["/works/ok"][1]
    assert response.metadata == {"field_count": 5, "policy": "g0_exact_allowlist"}
    assert b"synthetic-contract" not in response.body
    expected_key = derive_transport_request_key(response.source_url or "")
    with factory() as session:
        permit = session.scalar(select(AcquisitionRequestPermit))
        assert permit is not None
        assert permit.request_key_hash == sha256(expected_key.encode()).hexdigest()


def test_unknown_field_trips_schema_drift_without_leaking_field_name() -> None:
    with metadata_server() as origin:
        provider, factory = build_provider(origin, "drift")
        with pytest.raises(MetadataPolicyError) as caught:
            provider.fetch(provider.list_requests()[0])

    assert caught.value.reason == MetadataPolicyReason.SCHEMA_DRIFT
    assert "unexpected_field" not in str(caught.value)
    with factory() as session:
        run_budget = session.scalar(select(AcquisitionRunBudget))
        event = session.scalar(select(AcquisitionStopEvent))
        assert run_budget is not None and run_budget.stop_reason == "schema_drift"
        assert event is not None and event.trigger_source == "schema"


def test_sensitive_field_is_rejected_without_leaking_value() -> None:
    with metadata_server() as origin:
        provider, _ = build_provider(origin, "secret")
        with pytest.raises(MetadataPolicyError) as caught:
            provider.fetch(provider.list_requests()[0])

    assert caught.value.reason == MetadataPolicyReason.SENSITIVE_FIELD
    assert "must-not-propagate" not in str(caught.value)


def test_non_success_response_body_is_discarded() -> None:
    with metadata_server() as origin:
        provider, _ = build_provider(origin, "forbidden")
        response = provider.fetch(provider.list_requests()[0])

    assert response.status_code == 403
    assert response.body == b"{}"
    assert response.metadata == {"response_body_discarded": True}
    assert b"must-be-discarded" not in response.body


def test_unowned_request_is_rejected_before_permit() -> None:
    with metadata_server() as origin:
        provider, factory = build_provider(origin, "ok")
        unowned = AcquisitionRequest(entity_type=EntityType.WORK, source_id="missing")
        with pytest.raises(ValueError, match="not owned"):
            provider.fetch(unowned)

    with factory() as session:
        permits = session.scalars(select(AcquisitionRequestPermit)).all()
        assert permits == []


def build_external_provider(
    *source_ids: str,
) -> tuple[
    PinnedMetadataProvider,
    sessionmaker[Session],
    FakeOpener,
]:
    approval, safety, factory = build_safety()
    capability = SessionCapability(
        established_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=5),
        allowed_age_ratings=frozenset({"all_ages", "r18", "r18g"}),
    )
    opener = FakeOpener(
        FakeResponse(
            body=json.dumps(PAYLOADS["/works/ok"][1]).encode(),
            headers=[("Content-Type", "application/json")],
        )
    )
    transport = PermitGuardedExternalTransport(
        safety,
        ExternalSessionBroker(
            capability,
            lambda: "session=synthetic-external-contract",
            allowed_hosts=frozenset({ALLOWED_HOST}),
            open_request=opener,
        ),
        clock=lambda: NOW,
    )
    requests = tuple(
        AcquisitionRequest(entity_type=EntityType.WORK, source_id=source_id)
        for source_id in source_ids
    )
    provider = PinnedMetadataProvider(
        f"https://{ALLOWED_HOST}:443",
        requests,
        transport,
        approval,
        clock=lambda: NOW,
    )
    return provider, factory, opener


def test_default_external_opener_cannot_use_legacy_provider_fetch() -> None:
    approval, safety, factory = build_safety()
    capability = SessionCapability(
        established_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=5),
        allowed_age_ratings=frozenset({"all_ages", "r18", "r18g"}),
    )
    transport = PermitGuardedExternalTransport(
        safety,
        ExternalSessionBroker(
            capability,
            lambda: "session=must-never-be-read",
            allowed_hosts=frozenset({ALLOWED_HOST}),
        ),
        clock=lambda: NOW,
    )
    provider = PinnedMetadataProvider(
        f"https://{ALLOWED_HOST}",
        (AcquisitionRequest(entity_type=EntityType.WORK, source_id="42"),),
        transport,
        approval,
        clock=lambda: NOW,
    )

    with pytest.raises(RuntimeError, match="journal-bound execution"):
        provider.fetch(provider.list_requests()[0])

    with factory() as session:
        assert session.scalar(select(AcquisitionRequestPermit)) is None


def test_external_transport_mode_plans_and_parses_without_transport() -> None:
    approval, safety, _ = build_safety()
    capability = SessionCapability(
        established_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=5),
        allowed_age_ratings=frozenset({"all_ages", "r18", "r18g"}),
    )
    opener = FakeOpener()
    transport = PermitGuardedExternalTransport(
        safety,
        ExternalSessionBroker(
            capability,
            lambda: "session=synthetic-external-contract",
            allowed_hosts=frozenset({ALLOWED_HOST}),
            open_request=opener,
        ),
        clock=lambda: NOW,
    )
    request = AcquisitionRequest(entity_type=EntityType.WORK, source_id="ok")
    with pytest.raises(ValueError, match="modes do not match"):
        PinnedMetadataProvider(
            "http://127.0.0.1:8080",
            (request,),
            transport,
            approval,
            clock=lambda: NOW,
        )
    with pytest.raises(ValueError, match="not permitted"):
        PinnedMetadataProvider(
            "https://another.pixiv.test",
            (request,),
            transport,
            approval,
            clock=lambda: NOW,
        )
    provider, factory, opener = build_external_provider("ok")
    plan = provider.plan_network_free_request(request)

    assert plan.request == request
    assert plan.binding.approval_fingerprint == provider.approval_fingerprint
    assert plan.binding.provider_id == provider.name
    assert plan.source_url == f"https://{ALLOWED_HOST}/works/ok"
    assert plan.timeout_seconds > 0
    assert sha256(plan.binding.request_key.encode()).hexdigest() == (
        plan.binding.binding_hash
    )

    response = provider.parse_allowlisted_response(
        request,
        plan.binding,
        KnownMetadataResponse(
            status_code=200,
            body=json.dumps(PAYLOADS["/works/ok"][1]).encode(),
            headers={"Content-Type": "application/json"},
        ),
        observed_at=NOW,
    )

    assert response.json_value() == PAYLOADS["/works/ok"][1]
    assert response.source_url == f"https://{ALLOWED_HOST}/works/ok"
    assert opener.requests == []
    with factory() as session:
        assert session.scalars(select(AcquisitionRequestPermit)).all() == []

def test_pure_parse_reports_schema_drift_without_signaling_transport() -> None:
    provider, factory, opener = build_external_provider("drift")
    request = provider.list_requests()[0]
    plan = provider.plan_network_free_request(request)

    with pytest.raises(MetadataPolicyError) as caught:
        provider.parse_allowlisted_response(
            request,
            plan.binding,
            KnownMetadataResponse(
                status_code=200,
                body=json.dumps(PAYLOADS["/works/drift"][1]).encode(),
                headers={},
            ),
            observed_at=NOW,
        )

    assert caught.value.reason == MetadataPolicyReason.SCHEMA_DRIFT
    assert opener.requests == []
    with factory() as session:
        budget = session.scalar(select(AcquisitionRunBudget))
        assert budget is not None and budget.stop_reason is None


def test_pure_parse_discards_non_success_body_without_decoding_it() -> None:
    provider, factory, opener = build_external_provider("forbidden")
    request = provider.list_requests()[0]
    plan = provider.plan_network_free_request(request)

    response = provider.parse_allowlisted_response(
        request,
        plan.binding,
        KnownMetadataResponse(
            status_code=403,
            body=b"not-json session_token=must-not-propagate",
            headers={},
        ),
        observed_at=NOW,
    )

    assert response.body == b"{}"
    assert response.metadata == {"response_body_discarded": True}
    assert opener.requests == []
    with factory() as session:
        assert session.scalars(select(AcquisitionRequestPermit)).all() == []


@pytest.mark.parametrize(
    "replacement",
    [
        {"provider_id": "replacement_provider"},
        {"approval_fingerprint": "b" * 64},
        {"entity_type": EntityType.AUTHOR},
        {"source_id": "replacement"},
        {"canonical_url": f"https://{ALLOWED_HOST}/works/replacement"},
    ],
)
def test_pure_parse_rejects_substituted_binding(
    replacement: dict[str, object],
) -> None:
    provider, factory, opener = build_external_provider("ok")
    request = provider.list_requests()[0]
    expected = provider.plan_network_free_request(request).binding
    values: dict[str, object] = {
        "approval_fingerprint": expected.approval_fingerprint,
        "provider_id": expected.provider_id,
        "entity_type": expected.entity_type,
        "source_id": expected.source_id,
        "canonical_url": expected.canonical_url,
    }
    values.update(replacement)
    substituted = CanonicalLiveRequestBinding.model_validate(values)

    with pytest.raises(ValueError, match="does not match"):
        provider.parse_allowlisted_response(
            request,
            substituted,
            KnownMetadataResponse(status_code=200, body=b"{}", headers={}),
            observed_at=NOW,
        )

    assert opener.requests == []
    with factory() as session:
        assert session.scalars(select(AcquisitionRequestPermit)).all() == []


def test_origin_and_transport_modes_cannot_be_mixed() -> None:
    approval, safety, _ = build_safety()
    loopback_transport = build_loopback_transport(safety)
    request = AcquisitionRequest(entity_type=EntityType.WORK, source_id="ok")

    with pytest.raises(ValueError, match="modes do not match"):
        PinnedMetadataProvider(
            f"https://{ALLOWED_HOST}",
            (request,),
            loopback_transport,
            approval,
            clock=lambda: NOW,
        )


@pytest.mark.parametrize(
    "origin",
    [
        "http://metadata.pixiv.test",
        "https://127.0.0.1",
        "https://metadata.pixiv.test:444",
        "https://user:password@metadata.pixiv.test",
        "https://metadata.pixiv.test/path",
        "https://metadata.pixiv.test?query=forbidden",
        "https://metadata.pixiv.test#fragment",
        "https://*.pixiv.test",
    ],
)
def test_invalid_or_ambiguous_origins_are_rejected(origin: str) -> None:
    approval, safety, _ = build_safety()
    loopback_transport = build_loopback_transport(safety)
    request = AcquisitionRequest(entity_type=EntityType.WORK, source_id="ok")

    with pytest.raises(ValueError, match="origin"):
        PinnedMetadataProvider(
            origin,
            (request,),
            loopback_transport,
            approval,
            clock=lambda: NOW,
        )
