# Phase 2 API operations boundary

Every response now includes a bounded application duration in `Server-Timing` and an
`X-Query-Budget` result of `met` or `exceeded`. The default advisory budgets are 250 ms
for health routes and 750 ms for other routes. Route-template overrides are injectable.
An overrun is observed but is never retried automatically, preventing duplicate database
work. Observations contain only request ID, method, route template, status, duration,
budget and authorization outcome; path values and query parameters are excluded.

The consumer boundary supports a provider-neutral rate limiter. Its in-memory implementation
remains suitable for tests, while the private Compose deployment uses a PostgreSQL fixed-window
backend with row/advisory transaction locks. An eight-worker contention smoke proves exactly
three allowed and five denied decisions with a persisted count of three.

Rate-limit responses use fixed `429 consumer_rate_limit_exceeded` bodies and a bounded
`Retry-After` header. Unexpected backend failures use fixed
`503 rate_limit_service_unavailable` bodies. No backend exception is returned.

Access decisions are reduced to UTC timestamp, request ID, SHA-256 consumer key, method,
route template, status and authorization outcome. Raw consumer subjects, bearer material,
cookies, path parameters and query strings are never passed to the audit sink. The default
private fallback writes through the redacting structured logger. The Compose deployment uses
an append-only PostgreSQL sink with explicit per-event retention deadlines; the integration
smoke also proves that only elapsed rows are purged. Raw identities never enter its schema.

The API contract is exported deterministically to `contracts/openapi-v1.json`. The
companion report records the SHA-256, path and operation counts, read-only status and
prohibited-field result. Any path-count, mutation-method or minimized-schema drift fails
the exporter and therefore the Phase 2 exit review.
