"""Loopback-only TLS evidence probe for the private API container."""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import socket
import ssl
from datetime import UTC, datetime


def run_tls_smoke(*, host: str, port: int) -> dict[str, object]:
    if host not in {"127.0.0.1", "::1"}:
        raise ValueError("TLS smoke target must be numeric loopback")
    if port < 1 or port > 65_535:
        raise ValueError("TLS smoke port is invalid")

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    connection = http.client.HTTPSConnection(host, port, context=context, timeout=5)
    connection.connect()
    tls_socket = connection.sock
    if tls_socket is None:
        raise RuntimeError("TLS connection did not expose a socket")
    protocol = tls_socket.version()
    cipher_details = tls_socket.cipher()
    certificate = tls_socket.getpeercert(binary_form=True)
    if protocol is None or cipher_details is None or not certificate:
        raise RuntimeError("TLS session evidence was incomplete")
    connection.request("GET", "/health/ready")
    response = connection.getresponse()
    response.read()
    connection.close()

    plaintext_http_accepted = False
    try:
        with socket.create_connection((host, port), timeout=3) as plaintext:
            plaintext.sendall(b"GET /health/live HTTP/1.0\r\nHost: localhost\r\n\r\n")
            plaintext_http_accepted = plaintext.recv(32).startswith(b"HTTP/")
    except (OSError, TimeoutError):
        plaintext_http_accepted = False

    passed = (
        response.status == 200
        and protocol in {"TLSv1.2", "TLSv1.3"}
        and not plaintext_http_accepted
    )
    report: dict[str, object] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "passed" if passed else "failed",
        "target": "numeric_loopback",
        "https_status": response.status,
        "tls_protocol": protocol,
        "cipher": cipher_details[0],
        "certificate_sha256": hashlib.sha256(certificate).hexdigest(),
        "plaintext_http_accepted": plaintext_http_accepted,
        "certificate_trust_reviewed": False,
        "external_publication_approved": False,
        "external_network_used": False,
    }
    if not passed:
        raise RuntimeError(f"TLS smoke failed: {report}")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8443)
    args = parser.parse_args()
    print(json.dumps(run_tls_smoke(host=args.host, port=args.port), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
