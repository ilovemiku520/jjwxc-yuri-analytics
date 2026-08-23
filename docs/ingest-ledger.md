# Offline Ingest Ledger

This increment adds the PostgreSQL persistence foundation required before a live
provider can be considered. It accepts only the existing `FixtureProvider`; it does
not contain Pixiv, Bright Data, browser automation, cookies, login, or HTTP code.

## Tables

All tables live in the `ingest` schema:

|Table|Purpose|
|-|-|
|`source_records`|Stable provider-local entity identities and availability state|
|`crawl_runs`|Run status, immutable configuration snapshot, and zero/live budget fields|
|`crawl_tasks`|Durable logical work and idempotency keys|
|`task_attempts`|Append-only execution attempts and operational outcomes|
|`raw_observations`|Content hash, external object key, size, schema fingerprint, and timestamps|
|`schema_definitions`|Versioned structure descriptors discovered by the offline probe|
|`quarantine_records`|Review queue for acquisition, parse, or validation failures|
|`discovery_checkpoints`|Opaque cursors for a future approved resumable provider|
|`acquisition_daily_budgets`|G0-fingerprint-bound daily request and estimated-cost totals|
|`acquisition_run_budgets`|Per-run counters, concurrency, and circuit-breaker state|
|`acquisition_request_permits`|Durable one-use reservations created before transport|
|`acquisition_stop_events`|Append-only non-secret stop-transition evidence|

Raw JSON bodies are deliberately not stored in PostgreSQL. For fixtures,
`payload_object_key` is the safe relative fixture path. A production object-storage
policy remains a later decision.

## Safety and repeatability

- `PYURI_ENABLE_NETWORK=true` is rejected by configuration.
- The Docker database profile uses an internal-only network.
- Replaying the same fixture observation does not duplicate `raw_observations`.
- Every run and attempt remains auditable even when an observation is a duplicate.
- Non-success fixture responses create a failed task and an open quarantine record.
- With `--schema-policy`, exact approvals record `valid` plus parser provenance;
  unknown/rejected/parser failures record `quarantined` plus an open review item.
- Replaying an already quarantined observation does not duplicate its open quarantine.
- SQLite is accepted only with an explicit test flag; Alembic targets PostgreSQL.

## Local PostgreSQL workflow

Install the database extras, set `PYURI_DATABASE_URL`, then run:

```powershell
pyuri-db migrate
pyuri-db ingest-fixtures `
  --manifest fixtures/manifest.json `
  --schema-policy fixtures/schema_policy.json
```

The ingest command prints deterministic result counts as JSON. Running it a second
time reports the observations as duplicates while preserving the original rows.

## Docker workflow

```powershell
docker compose --profile database up -d postgres
docker compose --profile database run --rm db-migrate
docker compose --profile database run --rm fixture-ingest
```

Revision `20260823_0009`, all safety/catalog/API-control tables and read indexes, cross-day permit contention, and
fixture replay passed against PostgreSQL 17 in Docker on 2026-08-22. The contention
test committed exactly one permit and deferred the competing worker without network
access.

## Deferred gates

- G0: authorize and constrain any live provider or real collection.
- G1: approve production entity fields after representative, authorized samples.
- Object storage, retention/deletion enforcement, parser promotion, and normalized
  work/author/tag models remain outside this increment.
