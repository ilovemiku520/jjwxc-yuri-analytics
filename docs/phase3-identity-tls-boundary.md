# Phase 3 identity and TLS boundary

Updated: 2026-08-23

## Implemented offline controls

`TrustedHmacProxyAuthorizer` is disabled unless
`PYURI_CONSUMER_AUTH_MODE=trusted_hmac_proxy`. It requires one pinned proxy ID, a secret of at
least 32 bytes, and assertions no older than the configured maximum. The versioned MAC binds:

- proxy ID;
- uppercase HTTP method and route path without query material;
- a constrained subject;
- unique, sorted scopes;
- integer issued-at time.

The preferred secret input is an absolute read-only file named by
`PYURI_TRUSTED_PROXY_HMAC_SECRET_FILE`. Inline configuration exists for controlled tests only;
using inline and file configuration together fails at startup. The application never logs or
stores the secret or raw subject. Durable audits retain only a domain-separated subject digest.

The API CLI also accepts a complete pair of absolute, distinct certificate/key files. Missing,
relative, identical or unavailable paths fail before Uvicorn starts. The TLS smoke creates a
one-day self-signed certificate, runs the API only on numeric loopback, verifies HTTPS and
plaintext rejection, stops the container, and deletes both temporary files.

## Evidence

Run:

```powershell
scripts\run-identity-integration.cmd
scripts\run-tls-integration.cmd
```

The identity report proves `401/200/403/401/401` for unsigned, valid, wrong-scope, expired and
tampered requests. It also proves that the security endpoint recognizes the adapter and the
database stores only digested identity events. The TLS report records negotiated protocol,
cipher, certificate fingerprint, HTTPS status and plaintext rejection. Neither report authorizes
external publication or source collection.

## Remaining deployment review

The smoke identity assertion generator is test code, not a deployed login service. External
publication remains blocked until an accountable owner selects and deploys a real identity-aware
proxy, isolates direct API reachability, establishes secret rotation, and maps authenticated users
to `analytics:read`.

The self-signed smoke certificate is intentionally untrusted. Publication also requires a trusted
production certificate chain, hostname ownership, renewal/rotation monitoring, private-key access
controls and reviewed proxy forwarding headers. Until both reviews pass, host bindings remain
loopback-only and `external_publication_approved=false`.

The remaining facts are enforced by the deployment manifest and aggregate review documented in
[`phase3-publication-gate.md`](phase3-publication-gate.md). The committed manifest stays a draft;
its current machine result is blocked by design.
