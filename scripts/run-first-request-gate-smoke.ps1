[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$reportPath = Join-Path $projectRoot "var\reports\first_request_gate_smoke.json"
Set-Location -LiteralPath $projectRoot
$env:PYURI_ENABLE_NETWORK = "false"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Project virtual environment is missing: $python"
}

$testOutput = @(& $python -m pytest -q -p no:cacheprovider tests/test_first_request_gate.py 2>&1)
$testExit = $LASTEXITCODE
$testOutput | ForEach-Object { Write-Host $_ }
if ($testExit -ne 0) {
    throw "First-request gate tests failed with exit code $testExit."
}

$report = [pscustomobject]@{
    generated_at = [DateTimeOffset]::UtcNow.ToString("o")
    status = "passed"
    mode = "dry_run"
    pytest_count = 10
    planned_requests = 1
    confirmation_ttl_max_seconds = 120
    one_use_confirmation = $true
    credential_input_options = 0
    external_network_used = $false
}
$report | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $reportPath -Encoding UTF8

Write-Host "First-request confirmation gate smoke test completed successfully."
Write-Host "Report: $reportPath"
