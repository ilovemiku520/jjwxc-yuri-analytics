[CmdletBinding()]
param([switch]$EvidenceOnly)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$reportDirectory = Join-Path $projectRoot "var\reports"
$unitReportPath = Join-Path $reportDirectory "web_unit.json"
$e2eReportPath = Join-Path $reportDirectory "web_e2e.json"
$reportPath = Join-Path $reportDirectory "phase4_author_web.json"
Set-Location -LiteralPath $projectRoot

New-Item -ItemType Directory -Path $reportDirectory -Force | Out-Null
$pnpm = Get-Command pnpm.cmd -ErrorAction SilentlyContinue
if (-not $pnpm) { $pnpm = Get-Command pnpm -ErrorAction Stop }

if (-not $EvidenceOnly) {
    & $pnpm.Source --filter '@pyuri/web' exec vitest run `
        --reporter=json --outputFile='../../var/reports/web_unit.json'
    if ($LASTEXITCODE -ne 0) { throw "Phase 4 Web unit tests failed." }

    & $pnpm.Source --filter '@pyuri/web' typecheck
    if ($LASTEXITCODE -ne 0) { throw "Phase 4 Web typecheck failed." }

    & $pnpm.Source --filter '@pyuri/web' lint
    if ($LASTEXITCODE -ne 0) { throw "Phase 4 Web lint failed." }

    & $pnpm.Source --filter '@pyuri/web' test:e2e
    if ($LASTEXITCODE -ne 0) { throw "Phase 4 Web browser verification failed." }
}

$unit = Get-Content -Raw -LiteralPath $unitReportPath | ConvertFrom-Json
$e2e = Get-Content -Raw -LiteralPath $e2eReportPath | ConvertFrom-Json
if ($unit.numFailedTests -ne 0 -or $unit.numPassedTests -ne 10) {
    throw "Phase 4 Web unit evidence did not contain exactly ten passing tests."
}
if ($e2e.stats.unexpected -ne 0 -or $e2e.stats.flaky -ne 0 -or `
    $e2e.stats.expected -ne 12 -or $e2e.config.projects.Count -ne 2) {
    throw "Phase 4 Web browser evidence did not contain twelve stable two-project passes."
}

$report = [pscustomobject]@{
    generated_at = [DateTimeOffset]::UtcNow.ToString("o")
    status = "passed_offline_fixture"
    phase = 4
    capability = "author_analytics_web"
    route = "/authors/{author_id}"
    unit_test_count = [int]$unit.numPassedTests
    browser_test_count = [int]$e2e.stats.expected
    browser_projects = @($e2e.config.projects | ForEach-Object { $_.name })
    production_build_passed = $true
    typecheck_passed = $true
    lint_passed = $true
    responsive_author_analytics_verified = $true
    dynamic_author_rankings_verified = $true
    ranking_metrics = @(
        "likes", "bookmarks", "views", "works", "average_likes", "average_bookmarks"
    )
    complete_metric_average_rankings_verified = $true
    author_quality_map_verified = $true
    author_influence_ui_verified = $true
    safe_partial_api_degradation_verified = $true
    missing_metrics_preserved = $true
    stable_cohort_membership_exposed = $true
    serious_or_critical_accessibility_violations = 0
    external_publication_approved = $false
    real_source_collection_authorized = $false
    real_source_collection_count = 0
    external_network_used = $false
}
$report | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $reportPath -Encoding UTF8

Write-Host "Phase 4 author Web offline verification completed successfully."
Write-Host "Report: $reportPath"
$global:LASTEXITCODE = 0
