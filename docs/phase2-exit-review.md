# Phase 2 private-boundary exit review

Updated: 2026-08-23

## Decision

Phase 2 **passed for loopback and private-container use**. The PostgreSQL-backed v1 API
exposes twenty-five bounded GET paths, stable opaque pagination, details, aggregates,
rankings, metric history/trends and freshness. No mutation or acquisition route exists.

This decision does not approve external publication and does not authorize Pixiv access.
The machine report records `external_publication_approved=false` and
`real_source_collection_count=0`.

## Evidence

| Gate | Result |
|-|-|
| Full quality suite | 426/426 tests; Ruff; strict mypy over 142 source/test modules |
| PostgreSQL migration | `20260823_0009`; five catalog read indexes |
| Docker API/Web reads | Catalog, histories and operational summaries return 200 |
| Operational headers | Query budget and bounded Server-Timing verified |
| OpenAPI v1 | 21 GET operations; no mutation/prohibited fields |
| OpenAPI checksum | `bd0b7720002ed176a14903cabf4a5207e66f236b737307fbbc32957ecca816de` |
| Consumer controls | 8-worker PostgreSQL contention passed; durable minimized audit and expiry purge passed |
| Identity adapter | Trusted-HMAC-proxy valid/unsigned/scope/expiry/tamper container matrix passed |
| Loopback TLS | TLS 1.3 HTTPS 200; plaintext rejected; temporary key deleted |
| Source isolation | zero permits, zero first slots, no external network |

The executable report is `var/reports/phase2_exit_review.json`. Reproduce all local
quality and contract checks with:

```powershell
scripts\run-phase2-exit-review.cmd -SkipDockerRefresh
```

Omit `-SkipDockerRefresh` to refresh PostgreSQL and API Docker evidence first.

## External-publication blockers

- deploy and review a real identity-aware proxy that issues the implemented assertions;
- provision and review a production TLS certificate chain and key lifecycle;

The API has no cross-origin allowlist: untrusted-origin GET responses omit CORS grants and
preflight requests fail with `405`. Unit and container probes verify this default denial.

Until those controls pass separately, the API CLI exposure guard remains unchanged.
