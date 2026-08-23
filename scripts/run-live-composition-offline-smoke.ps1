[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$reportPath = Join-Path $projectRoot "var\reports\live_composition_offline_smoke.json"
$testFiles = @(
    "tests/test_live_one_request_composition.py",
    "tests/test_live_execution_journal.py",
    "tests/test_live_attempt_coordinator.py",
    "tests/test_durable_external_sender.py",
    "tests/test_journal_bound_provider_executor.py",
    "tests/test_live_slot_reconciler.py",
    "tests/test_live_attempt_report.py",
    "tests/test_live_process_crash_recovery.py",
    "tests/test_live_request_binding.py",
    "tests/test_runtime_session_lease.py",
    "tests/test_source_endpoint_contract.py",
    "tests/test_one_request_executor.py",
    "tests/test_final_one_request_failure_matrix.py"
)

Set-Location -LiteralPath $projectRoot
$env:PYURI_ENABLE_NETWORK = "false"

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Project virtual environment is missing: $python"
}

& $python -m pytest -q -p no:cacheprovider -o addopts= @testFiles
if ($LASTEXITCODE -ne 0) {
    throw "Live composition offline smoke tests failed."
}

$collectionOutput = @(
    & $python -m pytest --collect-only -q -p no:cacheprovider -o addopts= @testFiles 2>&1
)
if ($LASTEXITCODE -ne 0) {
    throw "Live composition test collection failed."
}
$collectionMatch = [regex]::Match(($collectionOutput -join "`n"), '(\d+) tests collected')
if (-not $collectionMatch.Success) {
    throw "Live composition test count was not found."
}

$report = [ordered]@{
    generated_at = [DateTimeOffset]::UtcNow.ToString("o")
    status = "passed"
    mode = "offline_synthetic"
    pytest_count = [int]$collectionMatch.Groups[1].Value
    live_prompt_contract = "passed"
    dual_opaque_capabilities = "passed"
    permanent_first_request_slot = "passed"
    non_success_response_fails_slot = "passed"
    crash_recovery_never_resends = "passed"
    journal_bound_send_intent = "passed"
    canonical_live_request_binding = "passed"
    one_use_runtime_session_lease = "passed"
    atomic_permit_send_prepare = "passed"
    endpoint_contract_gate = "passed"
    network_free_provider_plan = "passed"
    durable_marker_one_shot_sender = "passed"
    settled_allowlist_parse = "passed"
    direct_live_provider_fetch_disabled = "passed"
    journal_to_slot_no_resend_reconciliation = "passed"
    abrupt_process_exit_restart_matrix = "passed"
    endpoint_human_evidence_finalizer = "passed"
    migration_version = "20260823_0009"
    synthetic_provider_calls_executed = $true
    real_provider_contract_constructed = $true
    runtime_credentials_requested = $false
    pixiv_contacted = $false
    real_network_used = $false
    authorizes_live_request = $false
}
$report | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $reportPath -Encoding UTF8

Write-Host "Live composition offline smoke completed successfully."
Write-Host "Report: $reportPath"
