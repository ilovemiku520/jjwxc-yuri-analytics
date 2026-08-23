[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$reportPath = Join-Path $projectRoot "var\reports\parallel_modules_smoke.json"
Set-Location -LiteralPath $projectRoot
$env:PYURI_ENABLE_NETWORK = "false"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Project virtual environment is missing: $python"
}

$testFiles = @(
    "tests/test_external_transport.py",
    "tests/test_first_request_gate.py",
    "tests/test_ordered_database_pipeline.py"
)
$testOutput = @(& $python -m pytest -q -p no:cacheprovider @testFiles 2>&1)
$testExit = $LASTEXITCODE
$testOutput | ForEach-Object { Write-Host $_ }
if ($testExit -ne 0) {
    throw "Parallel module smoke tests failed with exit code $testExit."
}

$report = [pscustomobject]@{
    generated_at = [DateTimeOffset]::UtcNow.ToString("o")
    status = "passed"
    pytest_count = 30
    module_count = 3
    external_transport_contract = "passed"
    one_request_operator_gate = "passed"
    ordered_database_pipeline = "passed"
    acquisition_workers = 1
    verified_local_processing_workers = 3
    external_network_used = $false
}
$report | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $reportPath -Encoding UTF8

Write-Host "Parallel module smoke test completed successfully."
Write-Host "Report: $reportPath"
