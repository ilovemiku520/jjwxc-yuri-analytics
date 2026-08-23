[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$reportPath = Join-Path $projectRoot "var\reports\phase5_tag_review.json"
$testTemp = Join-Path $projectRoot "var\test-tmp\phase5-tag-review"
Set-Location -LiteralPath $projectRoot

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $testTemp) | Out-Null
& $python -m pytest -q -p no:cacheprovider --basetemp $testTemp tests/test_tag_review.py
if ($LASTEXITCODE -ne 0) { throw "Phase 5 tag review tests failed." }
& $python -m ruff check src/pixiv_yuri/analytics/tag_review.py tests/test_tag_review.py
if ($LASTEXITCODE -ne 0) { throw "Phase 5 tag review Ruff check failed." }
& $python -m mypy src/pixiv_yuri/analytics/tag_review.py tests/test_tag_review.py --strict
if ($LASTEXITCODE -ne 0) { throw "Phase 5 tag review strict mypy check failed." }
& $python -m pixiv_yuri.analytics.tag_review `
    --artifact config/tag_review_decision.fixture.json `
    --output $reportPath
if ($LASTEXITCODE -ne 0) { throw "Synthetic manual review fixture did not verify." }

$report = Get-Content -Raw -LiteralPath $reportPath | ConvertFrom-Json
if ($report.status -ne "verified_manual_decision" -or `
    -not $report.manual_review_verified -or $report.semantic_classification_performed -or `
    $report.real_source_collection_authorized -or $report.external_network_used -or `
    $report.reviewer_id -ne "fixture-reviewer") {
    throw "Phase 5 manual review evidence expanded scope or omitted accountability."
}

Write-Host "Phase 5 offline human-review artifact verification passed."
Write-Host "Report: $reportPath"
$global:LASTEXITCODE = 0
