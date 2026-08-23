# Acquisition Safety Controller

The safety controller is an offline, transport-independent prerequisite for a future
live Provider. It does not contain URLs, credentials, HTTP clients, browser automation,
or source-specific code.

## Enforced before transport

- active, unexpired G0 approval window;
- approval fingerprint binding on every request permit;
- maximum in-flight concurrency;
- per-run and daily request caps;
- daily estimated-cost cap;
- one-time request permits.

## Circuit breakers

- two consecutive HTTP 403 responses;
- two consecutive HTTP 429 responses;
- Schema Drift signal;
- explicit operator kill switch;
- expired/not-yet-active approval;
- request or cost cap exhaustion.

Successful or unrelated responses reset consecutive 403/429 counters. A transport
failure releases its concurrency permit but does not refund request or estimated-cost
budget, which is deliberately conservative.

## Persistent foundation

Alembic revisions through `20260823_0009` and SQLAlchemy models now define authoritative daily
budgets, per-run breaker state, one-use request permits, and append-only stop events in
PostgreSQL. The schema stores only approval fingerprints, counters, costs, statuses,
timestamps, and non-secret reason codes.

`PersistentAcquisitionSafety` now reserves and consumes permits in short database-owned
transactions with row locks. It enforces global concurrency, per-minute rate, per-run
and daily request ceilings, daily/monthly estimated cost, permit one-time use, persisted
403/429 breakers, manual stops, and approval expiry. Unit tests confirm restart-safe
state using SQLite's transaction semantics.

Real PostgreSQL 17 migration and concurrent row-lock behavior passed in Docker on
2026-08-22: two simultaneous workers produced exactly one committed permit and one
deferral, with no network transport. Redis may coordinate leases later but must not
become the authoritative budget or stop-state store.

## Gate

The controller does not make a draft approval valid. `pyuri-g0` must first accept a
complete bounded record, and the future Provider must be designed so every transport
call requires a permit from this controller or its persistent successor.
