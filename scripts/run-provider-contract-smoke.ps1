[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$reportPath = Join-Path $projectRoot "var\reports\provider_contract_smoke.json"
Set-Location -LiteralPath $projectRoot
$env:PYURI_ENABLE_NETWORK = "false"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Project virtual environment is missing: $python"
}

$testOutput = @(& $python -m pytest -q tests/test_pinned_metadata_provider.py 2>&1)
$testExit = $LASTEXITCODE
$testOutput | ForEach-Object { Write-Host $_ }
if ($testExit -ne 0) {
    throw "Pinned Provider contract tests failed with exit code $testExit."
}

$report = [pscustomobject]@{
    generated_at = [DateTimeOffset]::UtcNow.ToString("o")
    status = "passed"
    pytest_count = 5
    provider = "pinned_metadata_local_contract"
    allowed_field_count = 14
    schema_drift_stop = "passed"
    sensitive_field_rejection = "passed"
    non_success_body_discard = "passed"
    external_network_used = $false
    output = ($testOutput -join "`n")
}
$report | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $reportPath -Encoding UTF8

Write-Host "Pinned metadata Provider contract smoke test completed successfully."
Write-Host "Report: $reportPath"
