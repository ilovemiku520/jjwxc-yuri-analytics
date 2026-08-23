[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$temporaryDirectory = Join-Path $projectRoot ".tmp"
$composePath = Join-Path $temporaryDirectory "phase6-compose-config-$PID.json"
$reportPath = Join-Path $projectRoot "var\reports\phase6_readiness.json"
$backupRestorePath = Join-Path $projectRoot "var\reports\phase6_backup_restore.json"
Set-Location -LiteralPath $projectRoot

. (Join-Path $PSScriptRoot "runtime-database-secret.ps1")
$previousPassword = $env:PYURI_POSTGRES_PASSWORD
$env:PYURI_POSTGRES_PASSWORD = New-PyuriRuntimeDatabasePassword
New-Item -ItemType Directory -Force -Path $temporaryDirectory | Out-Null
try {
    $composeJson = docker compose --profile '*' config --format json
    if ($LASTEXITCODE -ne 0) { throw "Compose configuration could not be normalized." }
    Set-Content -LiteralPath $composePath -Value $composeJson -Encoding UTF8

    & $python -m pytest -q -p no:cacheprovider `
        --basetemp (Join-Path $projectRoot "var\test-tmp\phase6-readiness") `
        tests/test_deployment_readiness.py
    if ($LASTEXITCODE -ne 0) { throw "Phase 6 readiness tests failed." }
    & $python -m ruff check src/pixiv_yuri/deployment/readiness.py `
        tests/test_deployment_readiness.py
    if ($LASTEXITCODE -ne 0) { throw "Phase 6 readiness Ruff check failed." }
    & $python -m mypy src/pixiv_yuri/deployment/readiness.py `
        tests/test_deployment_readiness.py --strict
    if ($LASTEXITCODE -ne 0) { throw "Phase 6 readiness strict mypy check failed." }

    $reviewArguments = @(
        "-m", "pixiv_yuri.deployment.readiness",
        "--compose-json", $composePath,
        "--output", $reportPath
    )
    if (Test-Path -LiteralPath $backupRestorePath -PathType Leaf) {
        $reviewArguments += @("--backup-restore", $backupRestorePath)
    }
    & $python @reviewArguments
    if ($LASTEXITCODE -ne 0) { throw "Phase 6 readiness review could not run." }
} finally {
    if (Test-Path -LiteralPath $composePath) {
        Remove-Item -LiteralPath $composePath -Force
    }
    $env:PYURI_POSTGRES_PASSWORD = $previousPassword
}

$report = Get-Content -Raw -LiteralPath $reportPath | ConvertFrom-Json
if ($report.status -ne "offline_preparation_blocked" -or `
    $report.private_runtime_ready -or $report.external_publication_approved -or `
    $report.real_source_collection_authorized -or $report.external_network_used -or `
    $report.blockers.Count -eq 0) {
    throw "Phase 6 readiness matrix did not remain fail-closed."
}
Write-Host "Phase 6 offline readiness matrix generated safely."
Write-Host "Blockers: $($report.blockers -join ', ')"
Write-Host "Report: $reportPath"
$global:LASTEXITCODE = 0
