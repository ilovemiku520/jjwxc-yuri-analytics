# Phase 0 Exit Review

Updated: 2026-08-22

## Decision

Phase 0 **passed** on 2026-08-22. The offline engineering foundation, FixtureProvider,
Schema Probe, ingest ledger, real PostgreSQL integration, and FastAPI container health
contract all pass.

This review does **not** approve Phase 1 or any real Pixiv/Bright Data access. G0 is a
separate owner decision with legal, scope, field, retention, budget, and stop-condition
evidence.

## Evidence

| Gate | Evidence | Result |
|-|-|-|
| Fail-closed configuration | `PYURI_ENABLE_NETWORK=true` is rejected | Pass |
| Fixture Provider | Path safety, deterministic replay, explicit errors | Pass |
| Schema Probe | Analyze, diff, validation, exact parser route | Pass |
| PostgreSQL migration | Alembic migration completed on PostgreSQL 17 | Pass |
| Fixture ingest | 3/3 tasks; 3 observations; 3 schemas; 0 quarantine | Pass |
| Idempotence | Replays do not duplicate raw observations | Pass |
| API health contract | live=200; missing database readiness=503 | Pass |
| API container readiness | PostgreSQL healthy; API healthy; ready=200 | Pass |
| Quality baseline | pytest, Ruff, strict mypy | Pass |
| Real collection | No live Provider exists | Blocked by design |

## Demonstration

1. Generate the fixture schema and validation reports.
2. Migrate PostgreSQL and ingest three synthetic fixtures.
3. Show the ledger counts and zero quarantine rows.
4. Start the loopback-only API container.
5. Show `/health/live` and `/health/ready` returning HTTP 200.
6. Show that enabling collection network access fails closed.

## Residual risks

- Docker Hub DNS is polluted on the current host network. Project integration scripts
  use an explicit digest-preserving registry prefix; global Docker and system DNS are
  unchanged.
- The Docker Engine named pipe belongs to the signed-in desktop user, so container
  commands are executed by the checked-in desktop runners.
- Windows PowerShell 5.1 lacks `-SkipHttpErrorCheck`; the runner now uses the compatible
  `-UseBasicParsing` path. This reporting-only issue occurred after both containers had
  already become healthy.
- No live-source schema, terms, retention, content, or cost assumptions are approved.

## Exit outcome

`phase0_demo.json` records status=passed, `api_live_status=200`, and
`api_ready_status=200`. Phase 0 is closed. Phase 1 remains blocked until G0 is explicitly
approved.
