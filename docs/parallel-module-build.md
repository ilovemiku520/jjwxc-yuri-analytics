# Parallel Module Build

Three independent Phase 1 modules now run behind the existing G0 and persistent permit
controls. No real-source request is made by their smoke tests.

## External HTTPS transport contract

`ExternalSessionBroker` accepts exact ASCII DNS pins and only HTTPS on port 443. It
rejects IP hosts, user information, fragments, redirects, and non-pinned destinations.
Runtime credentials are supplied in memory for one request; credential-bearing and
redirect response headers are removed. Every attempted call is wrapped in one durable
permit and failures are recorded without refund or automatic retry.

## One-request operator gate

The dry-run gate only accepts `planned_requests=1`. Its random confirmation challenge
has a 5–120 second lifetime and is consumed on the first attempt, whether correct,
incorrect, or expired. Credential material has no CLI, environment, or file option.

## Ordered local processing and database commit

Provider acquisition stays on the coordinator thread. Immutable responses enter a
bounded local worker pool. Once processing completes, a new SQLAlchemy Session is
opened only on the coordinator thread and results are committed in request order inside
one transaction. Processing failure avoids the transaction; commit failure rolls the
whole batch back.

Run `scripts\run-parallel-modules-smoke.cmd`. Evidence is written to
`var/reports/parallel_modules_smoke.json`.
