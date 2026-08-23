[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location -LiteralPath $projectRoot

$env:PYURI_PYTHON_BASE_IMAGE = if ($env:PYURI_PYTHON_BASE_IMAGE) {
    $env:PYURI_PYTHON_BASE_IMAGE
} else {
    "m.daocloud.io/docker.io/library/python:3.12-slim"
}

docker compose --profile database up -d --wait postgres
if ($LASTEXITCODE -ne 0) {
    throw "PostgreSQL did not become healthy."
}

docker compose --profile database build db-migrate consumer-controls-smoke
if ($LASTEXITCODE -ne 0) {
    throw "Consumer-control integration images could not be built."
}

docker compose --profile database run --rm db-migrate
if ($LASTEXITCODE -ne 0) {
    throw "Alembic migration failed before the consumer-control smoke."
}

docker compose --profile database run --rm --no-deps consumer-controls-smoke
if ($LASTEXITCODE -ne 0) {
    throw "The PostgreSQL consumer-control contention smoke failed."
}

$reportPath = Join-Path $projectRoot "var\reports\consumer_controls_integration.json"
if (-not (Test-Path -LiteralPath $reportPath -PathType Leaf)) {
    throw "The consumer-control integration report was not created."
}
$report = Get-Content -Raw -LiteralPath $reportPath | ConvertFrom-Json
if ($report.status -ne "passed" -or $report.backend -ne "postgresql" -or `
    $report.allowed -ne 3 -or $report.denied -ne 5 -or `
    $report.persisted_request_count -ne 3 -or $report.minimized_audit_events -ne 8 -or `
    $report.expired_audit_rows_purged -ne 1 -or `
    -not $report.forbidden_audit_columns_absent -or $report.raw_consumer_identity_reported -or `
    $report.network_used) {
    throw "The consumer-control integration report did not meet the fail-closed contract."
}

Write-Host "PostgreSQL consumer-control integration completed successfully."
Write-Host "Report: $reportPath"
