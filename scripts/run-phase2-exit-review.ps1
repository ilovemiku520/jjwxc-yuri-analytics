[CmdletBinding()]
param([switch]$SkipDockerRefresh)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location -LiteralPath $projectRoot

$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "The project virtual environment is missing."
}

if (-not $SkipDockerRefresh) {
    & (Join-Path $PSScriptRoot "run-docker-integration.ps1")
    if ($LASTEXITCODE -ne 0) {
        throw "The PostgreSQL integration refresh failed."
    }
    & (Join-Path $PSScriptRoot "run-api-integration.ps1")
    if ($LASTEXITCODE -ne 0) {
        throw "The API integration refresh failed."
    }
    & (Join-Path $PSScriptRoot "run-identity-integration.ps1")
    if ($LASTEXITCODE -ne 0) {
        throw "The trusted-proxy identity integration refresh failed."
    }
    & (Join-Path $PSScriptRoot "run-tls-integration.ps1")
    if ($LASTEXITCODE -ne 0) {
        throw "The loopback TLS integration refresh failed."
    }
}

& $python -m pytest
if ($LASTEXITCODE -ne 0) {
    throw "Phase 2 tests failed."
}
& $python -m ruff check .
if ($LASTEXITCODE -ne 0) {
    throw "Phase 2 Ruff validation failed."
}
& $python -m mypy
if ($LASTEXITCODE -ne 0) {
    throw "Phase 2 strict mypy validation failed."
}
& $python -m pixiv_yuri.api.contract `
    --output contracts/openapi-v1.json `
    --report var/reports/openapi_contract.json
if ($LASTEXITCODE -ne 0) {
    throw "The OpenAPI v1 contract export failed."
}
& $python -m pixiv_yuri.api.phase2_review `
    --output var/reports/phase2_exit_review.json
if ($LASTEXITCODE -ne 0) {
    throw "The Phase 2 private-boundary exit review failed."
}

Write-Host "Phase 2 private-boundary exit review completed successfully."
Write-Host "External publication remains blocked pending the listed deployment controls."
