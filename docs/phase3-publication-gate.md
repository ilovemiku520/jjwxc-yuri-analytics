# Phase 3 external-publication gate

Updated: 2026-08-23

`pyuri-publication-review` turns deployment decisions into a versioned, non-secret and
fail-closed manifest. It reads the Phase 2 private-boundary report but never changes Docker,
firewall, DNS, certificates or source-collection state.

The deployment manifest requires accountable ownership and a maximum 90-day approval. Identity
evidence covers the exact proxy product/deployment reference, pinned proxy ID, blocked direct API
access, read-only secret delivery, rotation interval, assertion lifetime and health monitoring.
TLS evidence covers one production DNS hostname, certificate authority and expiry, minimum TLS
version, runtime key storage, automatic renewal, renewal monitoring and HSTS.

Unknown fields are rejected, so password, token, cookie or HMAC-secret fields cannot be smuggled
into the approval document. A valid publication decision still sets
`real_source_collection_authorized=false`; API publication and Pixiv acquisition are independent
gates.

The committed template is deliberately incomplete. Run:

```powershell
scripts\run-publication-evidence.cmd
scripts\run-publication-review.cmd
scripts\run-phase3-security-review.cmd -SkipDockerRefresh
```

The evidence command emits a versioned JSON Schema, a fresh non-secret draft, their SHA-256
digests and a proof that the generated draft remains blocked. Its initializer refuses to
overwrite an existing file unless the operator explicitly passes `--force`. The review command
returns a safe `blocked` report while the committed template is a draft. The security command
aggregates PostgreSQL consumer controls, trusted-proxy adapter, default-deny CORS, loopback TLS,
temporary-secret cleanup and all remaining publication controls. It succeeds only when the
system remains internally consistent, the versioned evidence bundle passes and external
publication remains disabled.

Do not convert the template to `approved` until the referenced proxy, network isolation,
production hostname, certificate chain, key lifecycle, monitoring and approver are real and
independently reviewable. No secret material belongs in the manifest or generated reports.
