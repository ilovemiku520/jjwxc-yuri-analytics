# Phase 2 read-only API foundation

The API currently exposes seventeen deliberately narrow read paths:

```text
GET /api/v1/source-records?limit=50&cursor=...
GET /api/v1/schema-definitions?limit=50&cursor=...
GET /api/v1/source-records/{id}/observations?limit=50&cursor=...
GET /api/v1/works?limit=50&cursor=...&q=...&author_id=...&tag=...
GET /api/v1/analytics/tags?limit=50&cursor=...
GET /api/v1/analytics/authors?limit=50&cursor=...
GET /api/v1/works/{work_id}/metric-history?limit=50&cursor=...&from=...&to=...
GET /api/v1/analytics/metric-trends?date_from=...&date_to=...
GET /api/v1/analytics/freshness
GET /api/v1/works/{work_id}
GET /api/v1/authors/{author_id}
GET /api/v1/tags/{tag_name}
GET /api/v1/rankings/works?metric=likes&limit=50&cursor=...
GET /api/v1/rankings/authors?metric=likes&limit=50&cursor=...
GET /api/v1/operations/runs?limit=50&cursor=...&status=...
GET /api/v1/operations/tasks?limit=50&cursor=...&run_id=...&status=...
GET /api/v1/operations/quarantine?limit=50&cursor=...&entity_type=...&status=...
```

All lists use ascending primary-key keyset pagination with a versioned, checksum-verified
opaque cursor. `limit` is restricted to 1–100. The source index temporarily retains the
deprecated `after_id`/`next_after_id` fields for compatibility; clients should migrate to
`cursor`/`next_cursor`. Combining a cursor with a non-zero legacy `after_id` fails closed.

The source index returns only source-system identity, entity type/id, availability and
first/last-seen timestamps. Schema summaries return lifecycle and parser-compatibility
metadata but omit the structural `definition`. Observation history returns timestamps,
HTTP/content facts, byte count, schema fingerprint, parser version and validation state.
It omits source URLs, payload bodies/hashes/object keys, task-attempt identity, retention
details and observation metadata.

Responses use deterministic ETags and endpoint-specific private caching:

- source records: `Cache-Control: private, max-age=15`;
- schema definitions: `Cache-Control: private, max-age=60`;
- observation history: `Cache-Control: private, max-age=30`.

An exact `If-None-Match` returns `304` with no body. Public/shared caching is not enabled.
Missing databases return fixed `503 data_service_unavailable`; invalid opaque cursors
return fixed `422 invalid_cursor`; missing source records return fixed
`404 source_record_not_found`.

The normalized catalog routes expose reviewed fields only. Title search treats `%`, `_` and
backslash as literal input rather than SQL wildcard syntax. Aggregate routes derive only work
counts and sums of reviewed public view/bookmark/like counts.
Metric history requires timezone-aware timestamp bounds. Daily trends keep only the latest
snapshot per work/day and reject reversed or greater-than-366-day ranges.
Ranking cursors are endpoint/metric-bound and order by score descending plus an ascending
stable key. Details and rankings expose only reviewed fields and derived aggregates.

Operational summaries expose run/task counts and fixed machine statuses/error codes. They
omit configuration snapshots, requesters, stop details, logical targets, idempotency keys,
leases, source identities, free text and task-attempt linkage. No operational mutation route
is registered.

Every response carries a minimized `Server-Timing` duration and an `X-Query-Budget`
result. Performance observations use route templates only and omit path/query values.
The canonical v1 OpenAPI document is checksum-pinned by the executable contract exporter;
see `phase2-operations.md`.

No mutation or acquisition route is registered. Container integration verifies all three
PostgreSQL-backed paths and scans their responses for prohibited storage fields while
`PYURI_ENABLE_NETWORK=false`. Consumer authorization must be implemented before any
non-loopback deployment; see `phase2-api-auth-boundary.md`.
