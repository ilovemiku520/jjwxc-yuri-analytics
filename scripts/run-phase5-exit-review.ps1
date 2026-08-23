[CmdletBinding()]
param([switch]$RefreshEvidence)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$reportPath = Join-Path $projectRoot "var\reports\phase5_exit_review.json"
$testTemp = Join-Path $projectRoot "var\test-tmp\phase5-exit-review"
Set-Location -LiteralPath $projectRoot

if ($RefreshEvidence) {
    & (Join-Path $PSScriptRoot "run-phase5-tag-discovery.ps1")
    if ($LASTEXITCODE -ne 0) { throw "Phase 5 core evidence refresh failed." }
    & (Join-Path $PSScriptRoot "run-phase5-tag-web.ps1") -EvidenceOnly
    if ($LASTEXITCODE -ne 0) { throw "Phase 5 Web evidence refresh failed." }
    & (Join-Path $PSScriptRoot "run-phase5-tag-review.ps1")
    if ($LASTEXITCODE -ne 0) { throw "Phase 5 manual review evidence refresh failed." }
}

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $testTemp) | Out-Null
& $python -m pytest -q -p no:cacheprovider --basetemp $testTemp `
    tests/test_phase5_review.py tests/test_tag_review.py
if ($LASTEXITCODE -ne 0) { throw "Phase 5 exit-review tests failed." }
& $python -m ruff check src/pixiv_yuri/analytics/phase5_review.py `
    src/pixiv_yuri/analytics/tag_review.py tests/test_phase5_review.py tests/test_tag_review.py
if ($LASTEXITCODE -ne 0) { throw "Phase 5 exit-review Ruff check failed." }
& $python -m mypy src/pixiv_yuri/analytics/phase5_review.py `
    src/pixiv_yuri/analytics/tag_review.py tests/test_phase5_review.py `
    tests/test_tag_review.py --strict
if ($LASTEXITCODE -ne 0) { throw "Phase 5 exit-review strict mypy check failed." }

& $python -m pixiv_yuri.analytics.phase5_review --output $reportPath
if ($LASTEXITCODE -ne 0) { throw "Phase 5 aggregate exit review failed." }
$report = Get-Content -Raw -LiteralPath $reportPath | ConvertFrom-Json
if ($report.status -ne "passed_private_fixture_only" -or `
    -not $report.phase5_private_fixture_ready -or `
    $report.estimated_completion_percent -ne 100 -or `
    $report.semantic_classification_performed -or `
    $report.external_publication_approved -or `
    $report.real_source_collection_authorized -or `
    $report.real_source_collection_count -ne 0 -or $report.external_network_used) {
    throw "Phase 5 aggregate evidence expanded a prohibited boundary."
}

Write-Host "Phase 5 private Fixture-only exit review passed."
Write-Host "Report: $reportPath"
$global:LASTEXITCODE = 0
