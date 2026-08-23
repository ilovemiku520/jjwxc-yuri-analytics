[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$productionTemplate = Join-Path $projectRoot "config\production_identity_tls.template.json"
$productionReview = Join-Path $projectRoot "var\reports\production_identity_tls_review.json"
$publicationTemplate = Join-Path $projectRoot "config\publication_deployment.template.json"
$publicationReview = Join-Path $projectRoot "var\reports\publication_review.json"
$artifactPath = Join-Path $projectRoot "var\reports\production_publication.generated-draft.json"
$schemaPath = Join-Path $projectRoot "var\reports\production_publication_binding.schema.json"
$reportPath = Join-Path $projectRoot "var\reports\production_publication_binding.json"
Set-Location -LiteralPath $projectRoot

& $python -m pytest -q -p no:cacheprovider tests/test_production_publication_binding.py
if ($LASTEXITCODE -ne 0) { throw "Production/publication binding tests failed." }
& $python -m ruff check src/pixiv_yuri/deployment/production_publication_binding.py `
    tests/test_production_publication_binding.py
if ($LASTEXITCODE -ne 0) { throw "Production/publication binding Ruff check failed." }
& $python -m mypy --strict src/pixiv_yuri/deployment/production_publication_binding.py `
    tests/test_production_publication_binding.py
if ($LASTEXITCODE -ne 0) { throw "Production/publication binding strict mypy failed." }

$production = Get-Content -Raw -LiteralPath $productionTemplate | ConvertFrom-Json
$productionDecision = Get-Content -Raw -LiteralPath $productionReview | ConvertFrom-Json
$publication = Get-Content -Raw -LiteralPath $publicationTemplate | ConvertFrom-Json
$publicationDecision = Get-Content -Raw -LiteralPath $publicationReview | ConvertFrom-Json
$artifact = [ordered]@{
    version = 1
    manifest = $publication
    review = $publicationDecision
    certificate_sha256 = $production.tls.certificate_sha256
    production_evidence_sha256 = $productionDecision.evidence_sha256
}
$artifact | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $artifactPath -Encoding UTF8

& $python -m pixiv_yuri.deployment.production_publication_binding schema --output $schemaPath
if ($LASTEXITCODE -ne 0) { throw "Binding Schema export failed." }
& $python -m pixiv_yuri.deployment.production_publication_binding review `
    --production-evidence $productionTemplate --publication-artifact $artifactPath `
    --output $reportPath
$reviewExitCode = $LASTEXITCODE
if ($reviewExitCode -notin @(0, 2)) { throw "Binding review could not run." }

$report = Get-Content -Raw -LiteralPath $reportPath | ConvertFrom-Json
if ($report.status -ne "blocked" -or $report.external_publication_approved -or `
    $report.real_source_collection_authorized -or $report.external_network_used -or `
    $report.violations.Count -eq 0) {
    throw "The draft publication binding did not remain fail-closed."
}
Write-Host "Production/publication binding tooling passed safely; draft remains blocked."
Write-Host "Report: $reportPath"
$global:LASTEXITCODE = 0
