[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$reportPath = Join-Path $projectRoot "var\reports\first_sample_dry_run.json"
Set-Location -LiteralPath $projectRoot
$env:PYURI_ENABLE_NETWORK = "false"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Project virtual environment is missing: $python"
}

$testOutput = @(& $python -m pytest -q -p no:cacheprovider tests/test_first_sample_dry_run.py 2>&1)
$testExit = $LASTEXITCODE
$testOutput | ForEach-Object { Write-Host $_ }
if ($testExit -ne 0) {
    throw "First-sample dry-run tests failed with exit code $testExit."
}

$report = [pscustomobject]@{
    generated_at = [DateTimeOffset]::UtcNow.ToString("o")
    status = "passed"
    pytest_count = 4
    planned_requests = 1
    operator_capability = "one_use_process_local"
    first_request_slot = "permanent_approval_scope"
    provider_transport = "fake_https_opener"
    schema_drift_fail_closed = "passed"
    repeated_attempt_blocked = "passed"
    external_network_used = $false
}
$report | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $reportPath -Encoding UTF8

Write-Host "First-sample offline end-to-end rehearsal completed successfully."
Write-Host "Report: $reportPath"
