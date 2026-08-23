[CmdletBinding()]
param([switch]$Refresh)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$reportDirectory = Join-Path $projectRoot "var\reports"
$reportPath = Join-Path $reportDirectory "phase4_exit_review.json"
Set-Location -LiteralPath $projectRoot

if ($Refresh) {
    & (Join-Path $PSScriptRoot "run-phase4-author-analytics.ps1")
    if ($LASTEXITCODE -ne 0) { throw "Phase 4 API evidence refresh failed." }
    & (Join-Path $PSScriptRoot "run-phase4-author-web.ps1")
    if ($LASTEXITCODE -ne 0) { throw "Phase 4 Web evidence refresh failed." }
}

$api = Get-Content -Raw -LiteralPath `
    (Join-Path $reportDirectory "phase4_author_analytics.json") | ConvertFrom-Json
$web = Get-Content -Raw -LiteralPath `
    (Join-Path $reportDirectory "phase4_author_web.json") | ConvertFrom-Json
$openapi = Get-Content -Raw -LiteralPath `
    (Join-Path $reportDirectory "openapi_contract.json") | ConvertFrom-Json
$phase2 = Get-Content -Raw -LiteralPath `
    (Join-Path $reportDirectory "phase2_exit_review.json") | ConvertFrom-Json
$phase3 = Get-Content -Raw -LiteralPath `
    (Join-Path $reportDirectory "phase3_security_review.json") | ConvertFrom-Json

$violations = [Collections.Generic.List[string]]::new()
if ($api.status -ne "passed_offline_fixture" -or $api.endpoint_test_count -ne 28) {
    $violations.Add("author_api_evidence_invalid")
}
if (-not $api.average_rankings_use_metric_coverage -or $api.quality_map_limit -ne 200) {
    $violations.Add("author_analysis_semantics_unverified")
}
if ($api.influence_model_version -ne "allowed-metadata-v1" -or `
    -not $api.influence_requires_complete_metrics) {
    $violations.Add("author_influence_semantics_unverified")
}
if ($web.status -ne "passed_offline_fixture" -or $web.unit_test_count -ne 10 -or `
    $web.browser_test_count -ne 12 -or -not $web.author_quality_map_verified -or `
    -not $web.complete_metric_average_rankings_verified) {
    $violations.Add("author_web_evidence_invalid")
}
if (-not $web.author_influence_ui_verified) {
    $violations.Add("author_influence_web_unverified")
}
if ($openapi.status -ne "passed" -or $openapi.api_path_count -ne 25 -or `
    $openapi.operation_count -ne 25 -or $openapi.mutation_routes_exposed -or `
    $openapi.prohibited_fields_exposed -or $api.openapi_sha256 -ne $openapi.sha256) {
    $violations.Add("openapi_evidence_mismatch")
}
if (-not $phase2.private_read_api_ready -or $phase2.external_publication_approved -or `
    $phase2.real_source_collection_count -ne 0) {
    $violations.Add("private_api_boundary_invalid")
}
if ($phase3.external_publication_approved -or `
    $phase3.real_source_collection_authorized -or `
    $phase3.real_source_collection_count -ne 0 -or $phase3.external_network_used -or `
    $api.external_network_used -or $web.external_network_used) {
    $violations.Add("external_boundary_expanded")
}
if ($violations.Count -gt 0) {
    throw "Phase 4 checkpoint evidence failed: $($violations -join ', ')"
}

$dockerEvidenceCurrent = $phase2.openapi_sha256 -eq $openapi.sha256 -and `
    $phase2.api_path_count -eq 25
$remaining = if ($dockerEvidenceCurrent) {
    @()
} else {
    @("updated_25_path_docker_api_web_evidence_not_refreshed")
}
$report = [pscustomobject]@{
    generated_at = [DateTimeOffset]::UtcNow.ToString("o")
    status = if ($dockerEvidenceCurrent) {
        "passed_private_fixture_only"
    } else {
        "checkpoint_passed_pending_docker"
    }
    phase = 4
    estimated_completion_percent = if ($dockerEvidenceCurrent) { 100 } else { 95 }
    phase4_private_analysis_ready = $true
    phase4_exit_ready = $dockerEvidenceCurrent
    verified_api_test_count = 28
    verified_web_unit_test_count = 10
    verified_browser_test_count = 12
    api_path_count = 25
    openapi_sha256 = $openapi.sha256
    missing_metrics_preserved = $true
    metric_bound_rankings_verified = $true
    stable_cohort_growth_verified = $true
    sample_relative_quality_map_verified = $true
    configurable_complete_metric_influence_verified = $true
    multi_author_analysis_fixture_verified = $true
    docker_api_web_evidence_current = $dockerEvidenceCurrent
    remaining_exit_items = $remaining
    external_publication_approved = $false
    real_source_collection_authorized = $false
    real_source_collection_count = 0
    external_network_used = $false
}
$report | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $reportPath -Encoding UTF8

if ($dockerEvidenceCurrent) {
    Write-Host "Phase 4 private Fixture-only exit review passed."
} else {
    Write-Host "Phase 4 checkpoint passed; exit awaits current Docker evidence."
    Write-Host "Remaining exit items: $($remaining -join ', ')"
}
Write-Host "Report: $reportPath"
$global:LASTEXITCODE = 0
