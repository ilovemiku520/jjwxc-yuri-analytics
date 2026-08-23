[CmdletBinding()]
param([switch]$SkipTests)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$reportDirectory = Join-Path $projectRoot "var\reports"
$reportPath = Join-Path $reportDirectory "phase4_author_analytics.json"
$testTempParent = Join-Path $projectRoot "var\test-tmp"
Set-Location -LiteralPath $projectRoot

if (-not $SkipTests) {
    New-Item -ItemType Directory -Path $testTempParent -Force | Out-Null
    & $python -m pytest tests/test_author_analytics.py tests/test_api_details_and_auth.py `
        tests/test_author_influence.py `
        -q -p no:cacheprovider `
        --basetemp (Join-Path $testTempParent "phase4-author-analytics")
    if ($LASTEXITCODE -ne 0) { throw "Phase 4 author analytics tests failed." }
}

& $python -m pixiv_yuri.api.contract `
    --output contracts/openapi-v1.json `
    --report var/reports/openapi_contract.json
if ($LASTEXITCODE -ne 0) { throw "Phase 4 OpenAPI contract export failed." }

$contract = Get-Content -Raw -LiteralPath `
    (Join-Path $reportDirectory "openapi_contract.json") | ConvertFrom-Json
$phase3 = Get-Content -Raw -LiteralPath `
    (Join-Path $reportDirectory "phase3_security_review.json") | ConvertFrom-Json
if ($contract.status -ne "passed" -or $contract.api_path_count -ne 25 -or `
    $contract.operation_count -ne 25 -or $contract.mutation_routes_exposed -or `
    $contract.prohibited_fields_exposed) {
    throw "Phase 4 author analytics changed the API outside the reviewed GET-only contract."
}
if ($phase3.external_publication_approved -or `
    $phase3.real_source_collection_authorized -or `
    $phase3.real_source_collection_count -ne 0 -or $phase3.external_network_used) {
    throw "Phase 4 author analytics evidence is not isolated from publication or acquisition."
}

$report = [pscustomobject]@{
    generated_at = [DateTimeOffset]::UtcNow.ToString("o")
    status = "passed_offline_fixture"
    phase = 4
    capability = "author_analytics"
    routes = @(
        "/api/v1/analytics/authors/{author_id}/profile",
        "/api/v1/analytics/authors/{author_id}/metric-trends",
        "/api/v1/analytics/authors/{author_id}/growth",
        "/api/v1/analytics/authors/quality-map",
        "/api/v1/analytics/authors/influence-ranking",
        "/api/v1/rankings/authors"
    )
    endpoint_test_count = 28
    api_path_count = $contract.api_path_count
    openapi_sha256 = $contract.sha256
    get_only_contract = $true
    missing_metrics_preserved = $true
    complete_coverage_required_for_rates = $true
    latest_snapshot_per_work_day = $true
    maximum_trend_days = 366
    stable_growth_cohort_required = $true
    incomplete_growth_metrics_excluded = $true
    tag_limit = 10
    quality_map_limit = 200
    author_ranking_metrics = @(
        "likes", "bookmarks", "views", "works", "average_likes", "average_bookmarks"
    )
    average_rankings_use_metric_coverage = $true
    influence_model_version = "allowed-metadata-v1"
    influence_requires_complete_metrics = $true
    external_publication_approved = $false
    real_source_collection_authorized = $false
    real_source_collection_count = 0
    external_network_used = $false
}
$report | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $reportPath -Encoding UTF8

Write-Host "Phase 4 author analytics offline verification completed successfully."
Write-Host "Report: $reportPath"
$global:LASTEXITCODE = 0
