[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$launchReportPath = Join-Path $projectRoot "var\reports\launch_review.json"
$dryRunReportPath = Join-Path $projectRoot "var\reports\first_sample_dry_run.json"
$reportPath = Join-Path $projectRoot "var\reports\live_one_request_preflight.json"
$violations = [System.Collections.Generic.List[string]]::new()

Set-Location -LiteralPath $projectRoot
$env:PYURI_ENABLE_NETWORK = "false"

$launchStatus = "not_run"
$dryRunStatus = "not_run"
$migrationVersion = "not_checked"
$approvedRequestCap = 0
$reviewedRequestCap = 0

try {
    & (Join-Path $PSScriptRoot "run-launch-review.ps1")
    if (-not (Test-Path -LiteralPath $launchReportPath)) {
        throw "Launch review evidence is missing."
    }
    $launch = Get-Content -Raw -LiteralPath $launchReportPath | ConvertFrom-Json
    $launchStatus = [string]$launch.status
    $migrationVersion = [string]$launch.migration_version
    $approvedRequestCap = [int]$launch.approved_request_cap
    $reviewedRequestCap = [int]$launch.planned_request_cap

    if ($launch.status -ne "passed") { $violations.Add("launch_review_blocked") }
    if ($launch.external_network_used -ne $false) {
        $violations.Add("launch_review_external_network_detected")
    }
    if ($launch.postgres_ready -ne $true) { $violations.Add("postgres_not_ready") }
    if ([int]$launch.active_permit_count -ne 0) { $violations.Add("active_permits_exist") }
    if ([int]$launch.first_request_slot_count -ne 0) {
        $violations.Add("first_request_slot_already_spent")
    }
    if ([int]$launch.approved_request_cap -lt 1) {
        $violations.Add("approval_does_not_cover_one_request")
    }
    if ([int]$launch.planned_request_cap -ne 1) {
        $violations.Add("launch_review_must_plan_exactly_one_request")
    }
    if (@($launch.violations).Count -ne 0) { $violations.Add("launch_review_has_violations") }

    & (Join-Path $PSScriptRoot "run-first-sample-dry-run-smoke.ps1")
    if (-not (Test-Path -LiteralPath $dryRunReportPath)) {
        throw "First-sample dry-run evidence is missing."
    }
    $dryRun = Get-Content -Raw -LiteralPath $dryRunReportPath | ConvertFrom-Json
    $dryRunStatus = [string]$dryRun.status

    if ($dryRun.status -ne "passed") { $violations.Add("first_sample_dry_run_blocked") }
    if ([int]$dryRun.planned_requests -ne 1) {
        $violations.Add("planned_requests_must_equal_one")
    }
    if ($dryRun.external_network_used -ne $false) {
        $violations.Add("dry_run_external_network_detected")
    }
    if ($dryRun.provider_transport -ne "fake_https_opener") {
        $violations.Add("offline_provider_not_confirmed")
    }
} catch {
    $violations.Add("preflight_component_failed")
}

$status = if ($violations.Count -eq 0) { "passed" } else { "blocked" }
$report = [ordered]@{
    generated_at = [DateTimeOffset]::UtcNow.ToString("o")
    status = $status
    mode = "offline_smoke"
    planned_requests = 1
    launch_review_planned_requests = $reviewedRequestCap
    launch_review_status = $launchStatus
    first_sample_dry_run_status = $dryRunStatus
    approved_request_cap = $approvedRequestCap
    migration_version = $migrationVersion
    source_credentials_requested = $false
    pixiv_contacted = $false
    source_transport_used = $false
    infrastructure_network_activity = "not_measured"
    readiness_evidence_only = $true
    authorizes_live_request = $false
    atomic_execution_gate = $false
    violations = @($violations)
}
$report | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $reportPath -Encoding UTF8

if ($status -ne "passed") {
    Write-Error "Live one-request offline preflight was blocked. See the safe JSON report."
    exit 2
}

Write-Host "Live one-request offline preflight completed successfully."
Write-Host "Report: $reportPath"
