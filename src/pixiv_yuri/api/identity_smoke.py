"""Container smoke for the trusted-proxy consumer identity boundary."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

from pixiv_yuri.api.auth import trusted_proxy_headers
from pixiv_yuri.api.persistence_models import ApiConsumerAccessAudit
from pixiv_yuri.shared.database import build_engine, build_session_factory


def _request(
    *,
    path: str,
    headers: dict[str, str] | None = None,
) -> tuple[int, str]:
    request = urllib.request.Request(f"http://127.0.0.1:8001{path}", headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


def run_smoke(*, secret: bytes, database_url: str) -> dict[str, Any]:
    proxy_id = "identity-smoke-edge"
    subject = "identity-smoke-researcher"
    path = "/api/v1/analytics/freshness"
    issued_at = int(time.time())
    request_prefix = f"identity-smoke-{uuid.uuid4().hex[:12]}"

    def assertion(
        *, scopes: frozenset[str], timestamp: int = issued_at, request_suffix: str
    ) -> dict[str, str]:
        values = dict(
            trusted_proxy_headers(
                secret=secret,
                proxy_id=proxy_id,
                method="GET",
                path=path,
                subject=subject,
                scopes=scopes,
                issued_at=timestamp,
            )
        )
        values["X-Request-ID"] = f"{request_prefix}-{request_suffix}"
        return values

    unsigned_status, unsigned_body = _request(
        path=path, headers={"X-Request-ID": f"{request_prefix}-unsigned"}
    )
    valid_status, valid_body = _request(
        path=path,
        headers=assertion(scopes=frozenset({"analytics:read"}), request_suffix="valid"),
    )
    scope_status, scope_body = _request(
        path=path,
        headers=assertion(scopes=frozenset({"other:read"}), request_suffix="scope"),
    )
    expired_status, expired_body = _request(
        path=path,
        headers=assertion(
            scopes=frozenset({"analytics:read"}),
            timestamp=issued_at - 60,
            request_suffix="expired",
        ),
    )
    tampered_headers = assertion(
        scopes=frozenset({"analytics:read"}), request_suffix="tampered"
    )
    tampered_headers["X-Pyuri-Signature"] = "0" * 64
    tampered_status, tampered_body = _request(path=path, headers=tampered_headers)

    security_path = "/api/v1/operations/security-status"
    security_headers = dict(
        trusted_proxy_headers(
            secret=secret,
            proxy_id=proxy_id,
            method="GET",
            path=security_path,
            subject=subject,
            scopes=frozenset({"analytics:read"}),
            issued_at=issued_at,
        )
    )
    security_headers["X-Request-ID"] = f"{request_prefix}-security"
    security_status, security_body = _request(path=security_path, headers=security_headers)
    security_payload = json.loads(security_body)

    factory = build_session_factory(build_engine(database_url))
    with factory() as session:
        audit_count = session.scalar(
            select(func.count())
            .select_from(ApiConsumerAccessAudit)
            .where(ApiConsumerAccessAudit.request_id.like(f"{request_prefix}-%"))
        )
        digested_count = session.scalar(
            select(func.count())
            .select_from(ApiConsumerAccessAudit)
            .where(
                ApiConsumerAccessAudit.request_id.like(f"{request_prefix}-%"),
                ApiConsumerAccessAudit.consumer_key.is_not(None),
                func.length(ApiConsumerAccessAudit.consumer_key) == 64,
            )
        )

    fixed_bodies = (
        json.loads(unsigned_body) == {"detail": "consumer_authentication_required"}
        and json.loads(scope_body) == {"detail": "analytics_read_scope_required"}
        and json.loads(expired_body) == {"detail": "consumer_authentication_required"}
        and json.loads(tampered_body) == {"detail": "consumer_authentication_required"}
    )
    raw_subject_exposed = subject in "".join(
        (unsigned_body, valid_body, scope_body, expired_body, tampered_body, security_body)
    )
    passed = (
        unsigned_status == 401
        and valid_status == 200
        and scope_status == 403
        and expired_status == 401
        and tampered_status == 401
        and security_status == 200
        and security_payload.get("identity_adapter_configured") is True
        and security_payload.get("external_publication_approved") is False
        and audit_count == 6
        and digested_count == 3
        and fixed_bodies
        and not raw_subject_exposed
    )
    report: dict[str, Any] = {
        "status": "passed" if passed else "failed",
        "adapter": "trusted_hmac_proxy",
        "unsigned_status": unsigned_status,
        "valid_status": valid_status,
        "wrong_scope_status": scope_status,
        "expired_status": expired_status,
        "tampered_status": tampered_status,
        "security_status": security_status,
        "minimized_audit_events": audit_count,
        "digested_identity_events": digested_count,
        "fixed_error_bodies": fixed_bodies,
        "raw_subject_exposed": raw_subject_exposed,
        "secret_reported": False,
        "external_publication_approved": False,
        "external_network_used": False,
    }
    if not passed:
        raise RuntimeError(f"identity smoke failed: {report}")
    return report


def main() -> int:
    secret_file = os.environ.get("PYURI_TRUSTED_PROXY_HMAC_SECRET_FILE")
    database_url = os.environ.get("PYURI_DATABASE_URL")
    if not secret_file or not database_url:
        raise RuntimeError("identity smoke requires secret-file and database configuration")
    path = Path(secret_file)
    if not path.is_absolute() or not path.is_file():
        raise RuntimeError("identity smoke secret file is unavailable")
    report = run_smoke(secret=path.read_bytes(), database_url=database_url)
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
