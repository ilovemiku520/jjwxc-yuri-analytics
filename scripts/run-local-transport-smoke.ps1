[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$reportPath = Join-Path $projectRoot "var\reports\local_transport_smoke.json"
Set-Location -LiteralPath $projectRoot
$env:PYURI_ENABLE_NETWORK = "false"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Project virtual environment is missing: $python"
}

$testOutput = @(& $python -m pytest -q tests/test_loopback_transport.py 2>&1)
$testExit = $LASTEXITCODE
$testOutput | ForEach-Object { Write-Host $_ }
if ($testExit -ne 0) {
    throw "Local transport smoke tests failed with exit code $testExit."
}

$report = [pscustomobject]@{
    generated_at = [DateTimeOffset]::UtcNow.ToString("o")
    status = "passed"
    pytest_count = 5
    address_scope = "numeric_loopback_only"
    external_network_used = $false
    synthetic_session_only = $true
    output = ($testOutput -join "`n")
}
$report | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $reportPath -Encoding UTF8

Write-Host "Local authenticated-transport smoke test completed successfully."
Write-Host "Report: $reportPath"
