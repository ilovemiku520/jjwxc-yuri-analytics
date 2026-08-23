[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$secretDirectory = Join-Path $projectRoot "var\identity-smoke"
$secretPath = Join-Path $secretDirectory "proxy-secret"
$reportPath = Join-Path $projectRoot "var\reports\identity_integration.json"
Set-Location -LiteralPath $projectRoot

$env:PYURI_PYTHON_BASE_IMAGE = if ($env:PYURI_PYTHON_BASE_IMAGE) {
    $env:PYURI_PYTHON_BASE_IMAGE
} else { "m.daocloud.io/docker.io/library/python:3.12-slim" }

New-Item -ItemType Directory -Force -Path $secretDirectory | Out-Null
if (Test-Path -LiteralPath $secretPath -PathType Leaf) {
    Remove-Item -LiteralPath $secretPath -Force
}
$randomBytes = New-Object byte[] 48
$generator = [Security.Cryptography.RandomNumberGenerator]::Create()
try {
    $generator.GetBytes($randomBytes)
} finally {
    $generator.Dispose()
}
[IO.File]::WriteAllText($secretPath, [Convert]::ToBase64String($randomBytes))

try {
    docker compose --profile database up -d --wait postgres
    if ($LASTEXITCODE -ne 0) { throw "PostgreSQL did not become healthy." }
    docker compose --profile database run --rm db-migrate
    if ($LASTEXITCODE -ne 0) { throw "Database migration failed before identity smoke." }
    docker compose --profile identity --profile database up `
        -d --build --wait --wait-timeout 180 identity-api
    if ($LASTEXITCODE -ne 0) {
        docker compose --profile identity --profile database logs --tail 100 identity-api
        throw "The identity API container did not become healthy."
    }

    $probeOutput = (& docker compose exec -T identity-api pyuri-identity-smoke) -join "`n"
    if ($LASTEXITCODE -ne 0) { throw "The trusted-proxy identity probe failed." }
    $report = $probeOutput | ConvertFrom-Json
    if ($report.status -ne "passed" -or $report.adapter -ne "trusted_hmac_proxy" -or `
        $report.unsigned_status -ne 401 -or $report.valid_status -ne 200 -or `
        $report.wrong_scope_status -ne 403 -or $report.expired_status -ne 401 -or `
        $report.tampered_status -ne 401 -or $report.security_status -ne 200 -or `
        $report.minimized_audit_events -ne 6 -or $report.digested_identity_events -ne 3 -or `
        -not $report.fixed_error_bodies -or $report.raw_subject_exposed -or `
        $report.secret_reported -or $report.external_publication_approved -or `
        $report.external_network_used) {
        throw "The identity report did not meet its fail-closed contract."
    }
    $report | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $reportPath -Encoding UTF8
    Write-Host "Trusted-proxy identity integration completed successfully."
    Write-Host "Report: $reportPath"
} finally {
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & docker compose --profile identity --profile database stop identity-api 2>&1 | Out-Null
    $ErrorActionPreference = $previousErrorActionPreference
    if (Test-Path -LiteralPath $secretPath -PathType Leaf) {
        Remove-Item -LiteralPath $secretPath -Force
    }
    [Array]::Clear($randomBytes, 0, $randomBytes.Length)
}
