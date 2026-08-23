[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$reportPath = Join-Path $projectRoot "var\reports\publication_review.json"
Set-Location -LiteralPath $projectRoot

& $python -m pixiv_yuri.api.publication_review `
    --phase2-report var/reports/phase2_exit_review.json `
    --manifest config/publication_deployment.template.json `
    --output var/reports/publication_review.json
$reviewExitCode = $LASTEXITCODE
if ($reviewExitCode -notin @(0, 2)) {
    throw "The external-publication review could not run."
}
if (-not (Test-Path -LiteralPath $reportPath -PathType Leaf)) {
    throw "The external-publication report was not created."
}
$report = Get-Content -Raw -LiteralPath $reportPath | ConvertFrom-Json
if ($report.status -ne "blocked" -or $report.external_publication_approved -or `
    $report.real_source_collection_authorized -or $report.external_network_used -or `
    $report.violations.Count -eq 0) {
    throw "The draft publication review did not remain fail-closed."
}

Write-Host "Draft external-publication review completed safely."
Write-Host "Status: blocked; report: $reportPath"
$global:LASTEXITCODE = 0
