[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$schemaPath = Join-Path $projectRoot "var\reports\production_identity_tls.schema.json"
$reportPath = Join-Path $projectRoot "var\reports\production_identity_tls_review.json"
$templatePath = Join-Path $projectRoot "config\production_identity_tls.template.json"
Set-Location -LiteralPath $projectRoot

& $python -m pytest -q -p no:cacheprovider tests/test_production_evidence.py
if ($LASTEXITCODE -ne 0) { throw "Production evidence tests failed." }
& $python -m ruff check src/pixiv_yuri/deployment/production_evidence.py `
    tests/test_production_evidence.py
if ($LASTEXITCODE -ne 0) { throw "Production evidence Ruff check failed." }
& $python -m mypy --strict src/pixiv_yuri/deployment/production_evidence.py `
    tests/test_production_evidence.py
if ($LASTEXITCODE -ne 0) { throw "Production evidence strict mypy check failed." }

& $python -m pixiv_yuri.deployment.production_evidence schema --output $schemaPath --force
if ($LASTEXITCODE -ne 0) { throw "Production evidence Schema export failed." }
& $python -m pixiv_yuri.deployment.production_evidence review `
    --evidence $templatePath --output $reportPath
$reviewExitCode = $LASTEXITCODE
if ($reviewExitCode -notin @(0, 2)) { throw "Production evidence review could not run." }

$report = Get-Content -Raw -LiteralPath $reportPath | ConvertFrom-Json
if ($report.status -ne "blocked" -or $report.production_deployment_reviewed -or `
    $report.external_publication_approved -or $report.real_source_collection_authorized -or `
    $report.external_network_used -or $report.violations.Count -eq 0) {
    throw "The draft production evidence did not remain fail-closed."
}
Write-Host "Production identity/TLS evidence tooling passed safely; draft remains blocked."
Write-Host "Report: $reportPath"
$global:LASTEXITCODE = 0
