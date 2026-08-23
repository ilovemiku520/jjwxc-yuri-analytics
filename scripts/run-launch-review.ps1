[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$reportPath = Join-Path $projectRoot "var\reports\launch_review.json"
$stagedName = "launch_review.$([Guid]::NewGuid().ToString('N')).json"
$stagedPath = Join-Path $projectRoot "var\reports\$stagedName"
Set-Location -LiteralPath $projectRoot

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

docker compose --profile database up -d --wait postgres
if ($LASTEXITCODE -ne 0) { throw "PostgreSQL is not ready." }

docker compose --profile database run --rm db-migrate
if ($LASTEXITCODE -ne 0) { throw "Database migration check failed." }

docker compose --profile database build launch-review
if ($LASTEXITCODE -ne 0) { throw "Launch-review image build failed." }

docker compose --profile database run --rm --no-deps launch-review `
    --approval /run/pyuri/g0_approval.json `
    --planned-request-cap 1 `
    --output "/app/var/reports/$stagedName"
if ($LASTEXITCODE -ne 0) { throw "First-sample launch review was blocked." }

if (-not (Test-Path -LiteralPath $stagedPath)) {
    throw "Staged launch-review report was not created."
}
Move-Item -Force -LiteralPath $stagedPath -Destination $reportPath
Write-Host "First-sample launch review passed."
Write-Host "Report: $reportPath"
