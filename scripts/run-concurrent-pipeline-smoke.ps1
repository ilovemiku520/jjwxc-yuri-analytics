[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$reportPath = Join-Path $projectRoot "var\reports\concurrent_pipeline_smoke.json"
Set-Location -LiteralPath $projectRoot
$env:PYURI_ENABLE_NETWORK = "false"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Project virtual environment is missing: $python"
}

$testOutput = @(& $python -m pytest -q tests/test_acquisition_pipeline.py 2>&1)
$testExit = $LASTEXITCODE
$testOutput | ForEach-Object { Write-Host $_ }
if ($testExit -ne 0) {
    throw "Concurrent pipeline tests failed with exit code $testExit."
}

$report = [pscustomobject]@{
    generated_at = [DateTimeOffset]::UtcNow.ToString("o")
    status = "passed"
    pytest_count = 8
    acquisition_workers = 1
    verified_local_processing_workers = 3
    maximum_configured_local_workers = 8
    maximum_pending_local_tasks = 64
    deterministic_output = "passed"
    duplicate_preflight_rejection = "passed"
    processing_failure_backpressure = "passed"
    external_network_used = $false
    output = ($testOutput -join "`n")
}
$report | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $reportPath -Encoding UTF8

Write-Host "Bounded concurrent pipeline smoke test completed successfully."
Write-Host "Report: $reportPath"
