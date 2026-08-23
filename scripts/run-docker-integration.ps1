[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location -LiteralPath $projectRoot

$postgresUser = if ($env:PYURI_POSTGRES_USER) { $env:PYURI_POSTGRES_USER } else { "pyuri" }
$postgresDatabase = if ($env:PYURI_POSTGRES_DB) { $env:PYURI_POSTGRES_DB } else { "pyuri" }
$env:PYURI_POSTGRES_IMAGE = if ($env:PYURI_POSTGRES_IMAGE) {
    $env:PYURI_POSTGRES_IMAGE
} else {
    "m.daocloud.io/docker.io/library/postgres:17"
}
$env:PYURI_PYTHON_BASE_IMAGE = if ($env:PYURI_PYTHON_BASE_IMAGE) {
    $env:PYURI_PYTHON_BASE_IMAGE
} else {
    "m.daocloud.io/docker.io/library/python:3.12-slim"
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    $dockerDesktopBin = Join-Path $env:LOCALAPPDATA "Programs\DockerDesktop\resources\bin"
    $dockerDesktopCli = Join-Path $dockerDesktopBin "docker.exe"
    if (Test-Path -LiteralPath $dockerDesktopCli) {
        $env:Path = "$dockerDesktopBin;$env:Path"
    } else {
        throw "Docker CLI is not installed or is absent from PATH."
    }
}

docker version
if ($LASTEXITCODE -ne 0) {
    throw "Docker Engine is not ready. Start Docker Desktop and retry."
}

docker compose version
if ($LASTEXITCODE -ne 0) {
    throw "Docker Compose v2 is unavailable."
}

Write-Host "Using PostgreSQL image: $env:PYURI_POSTGRES_IMAGE"
Write-Host "Using Python base image: $env:PYURI_PYTHON_BASE_IMAGE"

docker pull $env:PYURI_POSTGRES_IMAGE
if ($LASTEXITCODE -ne 0) {
    throw "The PostgreSQL image could not be pulled through the configured registry endpoint."
}

docker pull $env:PYURI_PYTHON_BASE_IMAGE
if ($LASTEXITCODE -ne 0) {
    throw "The Python base image could not be pulled through the configured registry endpoint."
}

docker compose --profile database build db-migrate safety-smoke fixture-ingest consumer-controls-smoke
if ($LASTEXITCODE -ne 0) {
    throw "The database integration images could not be built."
}

docker compose --profile database up -d --wait postgres
if ($LASTEXITCODE -ne 0) {
    throw "PostgreSQL did not become healthy."
}

docker compose --profile database run --rm db-migrate
if ($LASTEXITCODE -ne 0) {
    throw "The migration container build or Alembic migration failed."
}

docker compose --profile database run --rm --no-deps safety-smoke
if ($LASTEXITCODE -ne 0) {
    throw "The PostgreSQL safety row-lock smoke test failed."
}

docker compose --profile database run --rm --no-deps safety-smoke `
    live-attempt-report `
    --output /app/var/reports/live_attempt_operator_report.json
if ($LASTEXITCODE -ne 0) {
    throw "The read-only live-attempt operator report failed."
}

docker compose --profile database run --rm --no-deps consumer-controls-smoke
if ($LASTEXITCODE -ne 0) {
    throw "The PostgreSQL consumer-control contention smoke failed."
}

$consumerControlsReportPath = Join-Path $projectRoot "var\reports\consumer_controls_integration.json"
if (-not (Test-Path -LiteralPath $consumerControlsReportPath -PathType Leaf)) {
    throw "The consumer-control integration report was not created."
}
$consumerControlsReport = Get-Content -Raw -LiteralPath $consumerControlsReportPath | ConvertFrom-Json
if ($consumerControlsReport.status -ne "passed" -or `
    $consumerControlsReport.allowed -ne 3 -or $consumerControlsReport.denied -ne 5 -or `
    $consumerControlsReport.persisted_request_count -ne 3 -or `
    $consumerControlsReport.minimized_audit_events -ne 8 -or `
    $consumerControlsReport.expired_audit_rows_purged -ne 1 -or `
    -not $consumerControlsReport.forbidden_audit_columns_absent -or `
    $consumerControlsReport.raw_consumer_identity_reported -or `
    $consumerControlsReport.network_used) {
    throw "The consumer-control report did not meet its fail-closed contract."
}

$operatorReportPath = Join-Path $projectRoot "var\reports\live_attempt_operator_report.json"
if (-not (Test-Path -LiteralPath $operatorReportPath -PathType Leaf)) {
    throw "The live-attempt operator report was not created."
}
$operatorReport = Get-Content -Raw -LiteralPath $operatorReportPath | ConvertFrom-Json
if (-not $operatorReport.read_only -or $operatorReport.authorizes_live_request) {
    throw "The live-attempt operator report is not fail-closed."
}
if ($operatorReport.unresolved_attempts.Count -ne 0 -or `
    $operatorReport.orphan_claimed_slots.Count -ne 0) {
    throw "The PostgreSQL safety smoke left unresolved live-attempt state."
}

docker compose --profile database run --rm --no-deps fixture-ingest
if ($LASTEXITCODE -ne 0) {
    throw "Offline fixture ingestion failed."
}

$verificationSql = @"
SELECT
  (SELECT count(*) FROM ingest.crawl_runs) AS crawl_runs,
  (SELECT count(*) FROM ingest.raw_observations) AS raw_observations,
  (SELECT count(*) FROM ingest.schema_definitions) AS schema_definitions,
  (SELECT count(*) FROM ingest.quarantine_records) AS quarantine_records,
  (SELECT count(*) FROM ingest.acquisition_daily_budgets) AS safety_daily_budgets,
  (SELECT count(*) FROM ingest.acquisition_run_budgets) AS safety_run_budgets,
  (SELECT count(*) FROM ingest.acquisition_request_permits) AS safety_permits,
  (SELECT count(*) FROM ingest.acquisition_stop_events) AS safety_stop_events,
  (SELECT count(*) FROM ingest.acquisition_first_request_slots) AS first_request_slots,
  (SELECT count(*) FROM ingest.acquisition_live_execution_journals) AS live_execution_journals,
  (SELECT count(*) FROM ingest.catalog_authors) AS catalog_authors,
  (SELECT count(*) FROM ingest.catalog_works) AS catalog_works,
  (SELECT count(*) FROM ingest.catalog_tags) AS catalog_tags,
  (SELECT count(*) FROM ingest.catalog_work_tags) AS catalog_work_tags,
  (SELECT count(*) FROM ingest.catalog_work_metric_snapshots) AS metric_snapshots,
  (SELECT count(*) FROM ingest.api_consumer_rate_limit_windows) AS consumer_rate_windows,
  (SELECT count(*) FROM ingest.api_consumer_access_audits) AS consumer_access_audits,
  (SELECT version_num FROM alembic_version) AS migration_version;
"@

docker compose exec -T postgres `
    psql -v ON_ERROR_STOP=1 -U $postgresUser -d $postgresDatabase -c $verificationSql
if ($LASTEXITCODE -ne 0) {
    throw "PostgreSQL verification query failed."
}

$catalogCounts = (& docker compose exec -T postgres `
    psql -v ON_ERROR_STOP=1 -U $postgresUser -d $postgresDatabase -tA `
    -c "SELECT count(*) || '|' || (SELECT count(*) FROM ingest.catalog_works) || '|' || (SELECT count(*) FROM ingest.catalog_tags) || '|' || (SELECT count(*) FROM ingest.catalog_work_tags) || '|' || (SELECT count(*) FROM ingest.catalog_work_metric_snapshots) FROM ingest.catalog_authors") -join ""
if (($LASTEXITCODE -ne 0) -or ($catalogCounts.Trim() -ne "1|2|2|3|2")) {
    throw "Normalized fixture catalog counts were not 1 author, 2 works, 2 tags, 3 links and 2 metric snapshots."
}
$catalogReadIndexCount = (& docker compose exec -T postgres `
    psql -v ON_ERROR_STOP=1 -U $postgresUser -d $postgresDatabase -tA `
    -c "SELECT count(*) FROM pg_indexes WHERE schemaname='ingest' AND indexname IN ('ix_catalog_authors_author_id','ix_catalog_works_work_id','ix_catalog_works_like_rank','ix_catalog_works_bookmark_rank','ix_catalog_works_view_rank')") -join ""
if (($LASTEXITCODE -ne 0) -or ($catalogReadIndexCount.Trim() -ne "5")) {
    throw "The five catalog detail/ranking indexes were not present."
}

$integrationReportPath = Join-Path $projectRoot "var\reports\postgres_safety_integration.json"
$integrationReport = [pscustomobject]@{
    generated_at = [DateTimeOffset]::UtcNow.ToString("o")
    status = "passed"
    migration_version = "20260823_0009"
    concurrent_workers = 2
    authorized = 1
    deferred = 1
    cross_utc_day_lock = "passed"
    request_idempotency = "passed"
    first_request_slot_contention = "passed"
    live_execution_journal_table = "present"
    atomic_live_send_prepare = "passed"
    no_send_recovery = "indeterminate_no_resend"
    journal_to_slot_reconciliation = "failed_no_resend"
    crash_reconciliation_matrix = "claimed_send_started_settled_completed_passed"
    uncertain_permit_cleanup = "transport_failed_no_refund"
    live_attempt_operator_report = "read_only"
    network_used = $false
    fixture_tasks_succeeded = 3
    catalog_authors = 1
    catalog_works = 2
    catalog_tags = 2
    catalog_work_tags = 3
    metric_snapshots = 2
    catalog_read_indexes = 5
    shared_consumer_rate_limit = "postgresql_contention_passed"
    durable_minimized_access_audit = "postgresql_retention_bounded"
    consumer_control_workers = 8
    consumer_control_allowed = 3
    consumer_control_denied = 5
}
$integrationReport | ConvertTo-Json -Depth 5 | Set-Content `
    -LiteralPath $integrationReportPath -Encoding UTF8

Write-Host "Docker/PostgreSQL offline integration completed successfully."
Write-Host "Report: $integrationReportPath"
