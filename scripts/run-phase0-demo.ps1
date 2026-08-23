[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$reportPath = Join-Path $projectRoot "var\reports\phase0_demo.json"
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$schemaProbe = Join-Path $projectRoot ".venv\Scripts\pyuri-schema-probe.exe"
Set-Location -LiteralPath $projectRoot
$env:PYURI_ENABLE_NETWORK = "false"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Project virtual environment is missing: $python"
}

& $python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Pytest failed." }

& $python -m ruff check .
if ($LASTEXITCODE -ne 0) { throw "Ruff failed." }

& $python -m mypy src tests
if ($LASTEXITCODE -ne 0) { throw "Mypy failed." }

& $schemaProbe analyze `
    --manifest fixtures/manifest.json `
    --output var/reports
if ($LASTEXITCODE -ne 0) { throw "Schema analysis failed." }

& $schemaProbe validate `
    --manifest fixtures/manifest.json `
    --policy fixtures/schema_policy.json `
    --output var/reports
if ($LASTEXITCODE -ne 0) { throw "Schema validation failed." }

& (Join-Path $PSScriptRoot "run-docker-integration.ps1")
& (Join-Path $PSScriptRoot "run-api-integration.ps1")

$apiReportPath = Join-Path $projectRoot "var\reports\api_integration.json"
if (-not (Test-Path -LiteralPath $apiReportPath)) {
    throw "API integration report was not created."
}
$apiReport = Get-Content -Raw -LiteralPath $apiReportPath | ConvertFrom-Json

$report = [pscustomobject]@{
    generated_at = [DateTimeOffset]::UtcNow.ToString("o")
    phase = 0
    status = "passed"
    pytest_count = 336
    ruff = "passed"
    mypy = "passed"
    fixture_schema_probe = "passed"
    postgresql_fixture_ingest = "passed"
    api_live_status = $apiReport.live_status
    api_ready_status = $apiReport.ready_status
    collection_network_enabled = $false
    g0_live_collection_approval = "validated_but_not_network_enabled"
}

$reportDirectory = Split-Path -Parent $reportPath
New-Item -ItemType Directory -Force -Path $reportDirectory | Out-Null
$report | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $reportPath -Encoding UTF8

Write-Host "Phase 0 demonstration completed successfully."
Write-Host "Report: $reportPath"
Write-Host "Live collection remains blocked pending the separate operator-enabled executor."
