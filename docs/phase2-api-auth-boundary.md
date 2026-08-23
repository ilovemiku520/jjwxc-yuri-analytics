# Phase 2 consumer authorization boundary

## Current deployment rule

The read API has a provider-neutral authorization seam and a trusted-HMAC-proxy adapter,
but the adapter is disabled by default and no real identity-aware proxy is deployed. Its CLI permits only
an explicit loopback IP, or a wildcard bind with the exact `private_container` deployment
scope used by the internal Compose network. LAN, public and hostname bindings fail before
Uvicorn starts. It must not be published on a LAN, public host,
ingress, tunnel or externally reachable reverse proxy until the proxy/certificate deployment
is reviewed. This restriction is independent of the Pixiv acquisition G0 gates.

All responses carry `nosniff`, `no-referrer` and deny-all/frame-deny CSP headers. Health
and error responses default to `Cache-Control: no-store`; explicitly minimized read models
retain their private endpoint-specific ETag caching.

## Required boundary before non-loopback use

Use an identity-aware reverse proxy as the primary authentication layer. The implemented
adapter pins a proxy ID and verifies a SHA-256 HMAC over method, path, subject, sorted scopes
and issued-at time using a 32-byte-or-longer runtime secret. Read endpoints require
`analytics:read`; future administrative and mutation operations must use separate scopes
and routes. Default-deny unknown scopes and entities.

The adapter reduces identity to an immutable subject and scope set. It emits fixed payload-free
401/403/503 failures, rejects missing/duplicate/malformed/expired/future/tampered assertions,
and never accepts credentials through query parameters. The HMAC secret may be supplied by an
absolute read-only file and is never persisted or reported. Deploying and reviewing the actual
proxy remains required before widening the bind boundary.

The private Compose application uses PostgreSQL per-consumer rate limiting and minimized durable
auditing. Eight-worker contention, explicit audit retention and expired-row deletion pass in a
real PostgreSQL container. Audit events use a domain-separated SHA-256 consumer key and route
template, never the raw subject, path values, query string or credential.

Bearer credentials must never appear in query strings, application logs, reports, ETags,
cursor content or database rows. Redact authorization and cookie headers at proxy and
application logging boundaries. Do not add password-based login or persist a Pixiv user
password in this service.

Default-deny CORS is verified. Configure TLS on every non-loopback hop, bounded request and
response sizes, per-subject rate limits, and auditable access decisions containing only
request ID, verified subject identifier, route, decision and timestamp. Browser cookie
deployments additionally require secure/httpOnly/sameSite cookies and CSRF protection;
bearer-token deployments must not silently accept ambient cookies.

## Exit evidence

The local/container matrix covers valid, unsigned, expired, missing-scope and tampered assertions;
rate limiting; minimized audit; default-deny CORS; TLS protocol; plaintext rejection; and the
absence of mutation/acquisition routes. Before publication, record the deployed proxy, its
network trust boundary, production certificate chain/key lifecycle and approver without committing
secrets.
