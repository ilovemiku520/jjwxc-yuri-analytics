# Phase 6 private deployment runbook

Status: offline draft; external publication and real-source collection remain disabled.

## Startup

Validate the Phase 2 and Phase 5 exit reports, resolve runtime secrets locally, run migrations,
then start PostgreSQL, API and Web with loopback-only published ports. Stop if any healthcheck,
private-network or evidence check fails.

## Shutdown

Stop Web and API before PostgreSQL. Preserve the named database volume and current minimized audit
evidence. Do not remove volumes during an ordinary shutdown.

## Backup

Create a custom-format logical PostgreSQL backup in a disposable project, copy it through a newly
created host-local temporary directory, and verify SHA-256 before copying it back for restore.
Record its size, migration version and per-table minimized counts. Never include runtime identity,
Pixiv session material, database passwords or publication secrets in the backup report. Delete the
temporary host copy after verification.

## Restore

Restore only into a newly created isolated drill database and disposable project volume. Verify the
checksum, migration version and every bounded evidence-table count before declaring success. Treat
an empty, partial or command-failed count as failure. Never overwrite the active database during a
drill.

## Incident rollback

Keep external publication disabled, stop Web/API, preserve audit evidence, and restore only after an
accountable operator selects a verified backup. A rollback does not authorize source collection.

## Publication boundary

Loopback/private-container readiness is not approval for Internet exposure. A real identity proxy,
trusted production certificate, secret lifecycle, monitoring and accountable publication manifest
must pass the independent publication gate before any external route is enabled.
