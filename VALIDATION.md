# Offline Foundation Validation

Validated on 2026-08-23 with Python 3.12.13.

Current aggregate verification: **377/377 tests passed**, Ruff passed, and strict mypy
passed across 80 source files. All external transport tests use FakeOpener; no Pixiv or
other real source was contacted.

## Passed

|Check|Result|
|-|-|
|Pytest|377/377 passed|
|Ruff|All checks passed|
|Strict mypy|No issues in 80 source files|
|Offline CLI schema probe|Passed; 2 entity reports, 0 errors|
|Schema diff CLI|Passed; identical reports produce 0 changes|
|Fixture ledger replay|Passed; second ingest creates 0 duplicate observation rows|
|Failure quarantine|Passed; a synthetic 404 creates failed run/task state and quarantine|
|Exact schema policy|Passed; 3/3 approved fixtures validate through an exact parser route|
|Fail-closed schema drift|Passed; unknown/rejected/missing-parser inputs are quarantined|
|Validation replay|Passed; quarantined observation replay does not duplicate open review rows|
|Raw-body minimization|Passed; `raw_observations` has no payload-body column|
|Alembic PostgreSQL SQL generation|Passed; all 17 ingest/safety/catalog tables emitted, no connection opened|
|Persistent safety model replay|Passed; budgets, permit and stop event survive commit/reload|
|Executable G0 v2|Passed; local ignored record validates with 14 fields and bounded authenticated scope|
|Transactional permit service|Passed; restart, one-use, concurrency, rate, cost and 403 stop behavior|
|PostgreSQL safety contention|Passed; 2 workers produced exactly 1 permit and 1 deferral, no network|
|Loopback authenticated transport|Passed; 5/5 via cmd.exe, synthetic session only, no external network|
|Pinned Provider contract|Passed; 5/5 via cmd.exe, 14-field allowlist and Schema Drift stop|
|Operator session preflight|Passed; 8/8 via cmd.exe, no-echo/TTL/clearing/safe CLI output|
|First-sample launch review|Passed via cmd.exe/PostgreSQL; 25 cap, 0 permits, 0 stopped runs|
|Docker/PostgreSQL integration|Passed; migration plus 3/3 fixture tasks succeeded|
|PostgreSQL persisted counts|1 crawl run, 3 observations, 3 schemas, 0 quarantine rows|
|FastAPI health contract|Passed; live=200 and missing-database readiness=503|
|FastAPI container integration|Passed; PostgreSQL healthy, API healthy, readiness=200|
|Phase 2 read models|Passed; source, Schema summary and observation history are minimized|
|Opaque cursor and cache contract|Passed; tampering fails closed, private ETag returns 304|
|Phase 2 Docker reads|Passed; source=200, Schema=200, observation=200, collection network off|
|API exposure guard|Passed; loopback/private-container allowed, LAN/public/hostname blocked|
|API security headers|Passed; no-store fallback, nosniff, no-referrer and deny-all CSP|
|Normalized Fixture catalog|Passed; 1 author, 2 works, 2 tags, 3 links; replay is idempotent|
|Catalog minimization|Passed; description/comments/followers/profile/URL/payload excluded|
|Catalog read API|Passed; work filters and tag/author aggregates use opaque cursors|
|Catalog Docker integration|Passed; migration `20260823_0008`, all catalog routes=200|
|Immutable metric history|Passed; 2 validated work observations produce exactly 2 snapshots|
|Daily trend semantics|Passed; latest work/day sample, timezone bounds, maximum 366-day range|
|Catalog freshness|Passed; latest observation plus author/work/tag/snapshot counts only|
|Catalog details|Passed; work/author/tag details minimized and private-cache only|
|Stable rankings|Passed; works/authors, three metrics, namespace-bound composite cursor|
|Catalog read indexes|Passed; five PostgreSQL identity/composite ranking indexes present|
|Consumer authorization seam|Passed; analytics:read plus fixed 401/403/503 outcomes|
|OpenAPI read-only contract|Passed; GET-only API, no storage/provenance/credential fields|
|Query performance budget|Passed; route-template observations and response timing headers|
|Consumer rate limiting|Passed; per-subject isolation, fixed 429/503, bounded memory|
|Minimized access audit|Passed; subject digest and route template only; no raw target/query|
|Operational read API|Passed; minimized run/task/quarantine filters and opaque pagination|
|Canonical OpenAPI export|Passed; 17 GET operations, checksum `637e803d…b97a6b`|
|Phase 2 exit review|Passed for private boundary; external publication remains blocked|
|Phase 3 web tests|11/11 Vitest tests passed across component, boundary, URL and trend behavior|
|Phase 3 web static gates|TypeScript and ESLint passed|
|Phase 3 production build|Next.js 16 optimized build passed; twelve private application routes|
|Phase 3 Docker integration|Passed; web/API/PostgreSQL healthy, twelve routes=200, Fixture rendering verified|
|Phase 3 web boundary|Passed; internal API origin hidden, prohibited fields absent, collection network disabled|
|Phase 3 responsive QA|Passed in browser at desktop and 390x844 mobile viewports; no console errors|
|Phase 3 browser E2E|8/8 Playwright checks passed across desktop and mobile projects|
|Phase 3 accessibility|axe found no serious or critical WCAG violations on seven key routes|
|Request correlation|Passed; request IDs are generated, validated, echoed, and logged|
|Windows PowerShell 5.1 runner|Passed; no PowerShell 7-only HTTP parameters remain|
|G0 governance contract|Passed; complete active record validates and fingerprints|
|G0 authenticated scope|Passed; authenticated-public plus all-ages/R-18/R-18G represented explicitly|
|G0 fail-closed cases|Passed; draft, expiry, secret handling, private/deleted/bypass, unsafe limits and missing stops rejected|
|Authenticated fixture simulation|Passed; local-only session expiry and rating scope fail closed|
|Authenticated payload secret guard|Passed; secret-shaped headers/metadata/JSON fields fail closed|
|Acquisition request guard|Passed; concurrency, run, daily and estimated-cost budgets|
|Acquisition circuit breakers|Passed; repeated 403/429, Schema Drift, manual and expiry|
|Wheel build/import (foundation baseline)|Passed; version `0.1.0`, fingerprint length 64|
|Browser companion collector|3/3 Node tests passed; exact artwork URL/ID, G0 ratings and field minimization|
|Browser companion permission boundary|Manifest V3; no Cookie, storage, tabs or webRequest permissions|
|Browser-export Docker compatibility|Both PPD and first-party companion synthetic JSON accepted offline|
|Browser companion R-18G minimization|Synthetic rating accepted, then removed from the exact twelve-field candidate|
|Browser-import website surface|Passed; source/counts visible while work ID and input hash remain hidden|

## Covered behavior

- live-network configuration is rejected;
- secret-shaped structured-log keys are redacted;
- fixture paths cannot be absolute or traverse with `..`;
- duplicate fixture logical keys and unknown requests fail explicitly;
- schema fingerprints ignore object/array order and scalar-value changes but detect
  type changes;
- aggregate reports track optional and nullable fields;
- removal of a required field is a high-severity diff;
- twelve versioned ingest-ledger and acquisition-safety tables are registered;
- fixture observation persistence is transactional and idempotent;
- run, task, attempt, schema, source-availability, and quarantine states are tested.
- policy/provider binding, duplicate decisions, parser version routing, and parser
  root-shape errors are tested;
- validation and parser provenance are persisted without storing raw payload bodies.
- liveness is database-independent and readiness fails closed without exposing errors;
- request IDs are bounded to a safe character set and propagated to response/log context.
- G0 records are bounded, expiring, fingerprinted, and independently validated before
  any future network configuration can be considered.
- authenticated Providers receive only a non-secret capability; no password, cookie,
  Authorization header, or token input exists in the offline implementation.
- every future transport request must consume a fingerprint-bound permit; concurrency
  and budgets are reserved before transport, with no refund on transport failure.
- persistent permit reservation owns its transaction and commits stop evidence before
  returning a stopped decision to the caller.
- authenticated transport tests reject external hosts/redirects, strip secret-shaped
  headers, consume timeout failures, and persist 403 breaker state.
- the Provider rejects unknown/sensitive/nested metadata before propagation and
  discards all non-success response bodies.
- operator sessions expire explicitly, redact representation, clear mutable buffers,
  and have no secret-bearing command-line option.
- launch review is read-only, requires migration `0002`, and emits no database URL or
  accountable-owner identifier.

## Deliberately not executed

- No Pixiv, Bright Data, or other external collection access occurred.
