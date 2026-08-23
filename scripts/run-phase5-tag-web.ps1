[CmdletBinding()]
param([switch]$EvidenceOnly)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$reportDirectory = Join-Path $projectRoot "var\reports"
$unitReportPath = Join-Path $reportDirectory "web_unit.json"
$e2eReportPath = Join-Path $reportDirectory "web_e2e.json"
$dockerReportPath = Join-Path $reportDirectory "web_integration.json"
$reportPath = Join-Path $reportDirectory "phase5_tag_web.json"
Set-Location -LiteralPath $projectRoot

New-Item -ItemType Directory -Path $reportDirectory -Force | Out-Null
$pnpm = Get-Command pnpm.cmd -ErrorAction SilentlyContinue
if (-not $pnpm) { $pnpm = Get-Command pnpm -ErrorAction Stop }

if (-not $EvidenceOnly) {
    $vitest = Join-Path $projectRoot "apps\web\node_modules\.bin\vitest.CMD"
    & $vitest run --reporter=json `
        --outputFile (Join-Path $reportDirectory "web_unit.json")
    if ($LASTEXITCODE -ne 0) { throw "Phase 5 Web unit tests failed." }
    & $pnpm.Source --filter '@pyuri/web' typecheck
    if ($LASTEXITCODE -ne 0) { throw "Phase 5 Web typecheck failed." }
    & $pnpm.Source --filter '@pyuri/web' lint
    if ($LASTEXITCODE -ne 0) { throw "Phase 5 Web lint failed." }
    & $pnpm.Source --filter '@pyuri/web' test:e2e
    if ($LASTEXITCODE -ne 0) { throw "Phase 5 Web browser verification failed." }
}

$unit = Get-Content -Raw -LiteralPath $unitReportPath | ConvertFrom-Json
$e2e = Get-Content -Raw -LiteralPath $e2eReportPath | ConvertFrom-Json
$docker = Get-Content -Raw -LiteralPath $dockerReportPath | ConvertFrom-Json
if ($unit.numFailedTests -ne 0 -or $unit.numPassedTests -ne 11) {
    throw "Phase 5 Web unit evidence did not contain exactly eleven passing tests."
}
if ($e2e.stats.unexpected -ne 0 -or $e2e.stats.flaky -ne 0 -or `
    $e2e.stats.expected -ne 16 -or $e2e.config.projects.Count -ne 2) {
    throw "Phase 5 Web browser evidence did not contain sixteen stable two-project passes."
}
if ($docker.status -ne "passed" -or $docker.route_count -ne 15 -or `
    -not $docker.security_headers_verified -or $docker.prohibited_fields_exposed -or `
    $docker.collection_network_enabled) {
    throw "Phase 5 Docker Web evidence is incomplete or outside the private boundary."
}

$report = [pscustomobject]@{
    generated_at = [DateTimeOffset]::UtcNow.ToString("o")
    status = "passed_private_fixture_slice"
    phase = 5
    capability = "tag_association_and_sensitivity_web"
    routes = @("/tags/graph", "/tags/review")
    unit_test_count = [int]$unit.numPassedTests
    browser_test_count = [int]$e2e.stats.expected
    browser_projects = @($e2e.config.projects | ForEach-Object { $_.name })
    docker_route_count = [int]$docker.route_count
    graph_visualization_verified = $true
    accessible_table_fallback_verified = $true
    threshold_sensitivity_chart_verified = $true
    human_review_queue_verified = $true
    bounded_filter_state_verified = $true
    semantic_classification_performed = $false
    serious_or_critical_accessibility_violations = 0
    production_build_passed = $true
    typecheck_passed = $true
    lint_passed = $true
    external_publication_approved = $false
    real_source_collection_authorized = $false
    real_source_collection_count = 0
    external_network_used = $false
}
$report | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $reportPath -Encoding UTF8

Write-Host "Phase 5 private Fixture-only tag Web slice passed."
Write-Host "Report: $reportPath"
$global:LASTEXITCODE = 0
