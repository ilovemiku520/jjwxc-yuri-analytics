[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$tlsDirectory = Join-Path $projectRoot "var\tls-smoke"
$certificatePath = Join-Path $tlsDirectory "certificate.pem"
$privateKeyPath = Join-Path $tlsDirectory "private-key.pem"
$reportPath = Join-Path $projectRoot "var\reports\tls_integration.json"
Set-Location -LiteralPath $projectRoot

$env:PYURI_POSTGRES_IMAGE = if ($env:PYURI_POSTGRES_IMAGE) {
    $env:PYURI_POSTGRES_IMAGE
} else { "m.daocloud.io/docker.io/library/postgres:17" }
$env:PYURI_PYTHON_BASE_IMAGE = if ($env:PYURI_PYTHON_BASE_IMAGE) {
    $env:PYURI_PYTHON_BASE_IMAGE
} else { "m.daocloud.io/docker.io/library/python:3.12-slim" }

New-Item -ItemType Directory -Force -Path $tlsDirectory | Out-Null
foreach ($temporaryFile in @($certificatePath, $privateKeyPath)) {
    if (Test-Path -LiteralPath $temporaryFile -PathType Leaf) {
        Remove-Item -LiteralPath $temporaryFile -Force
    }
}

try {
    docker compose --profile database up -d --wait postgres
    if ($LASTEXITCODE -ne 0) { throw "PostgreSQL did not become healthy." }

    docker compose --profile database run --rm --no-deps `
        --entrypoint openssl `
        --volume "${tlsDirectory}:/tls" `
        postgres req -x509 -newkey rsa:2048 -sha256 -nodes -days 1 `
        -subj "/CN=localhost" `
        -addext "subjectAltName=DNS:localhost,IP:127.0.0.1" `
        -keyout /tls/private-key.pem -out /tls/certificate.pem
    if ($LASTEXITCODE -ne 0) { throw "Temporary TLS certificate generation failed." }

    docker compose --profile database run --rm db-migrate
    if ($LASTEXITCODE -ne 0) { throw "Database migration failed before TLS smoke." }

    docker compose --profile tls --profile database up `
        -d --build --wait --wait-timeout 180 tls-api
    if ($LASTEXITCODE -ne 0) {
        docker compose --profile tls --profile database logs --tail 100 tls-api
        throw "The TLS API container did not become healthy."
    }

    $probeOutput = (& docker compose exec -T tls-api pyuri-tls-smoke) -join "`n"
    if ($LASTEXITCODE -ne 0) { throw "The TLS protocol probe failed." }
    $report = $probeOutput | ConvertFrom-Json
    if ($report.status -ne "passed" -or $report.https_status -ne 200 -or `
        $report.tls_protocol -notin @("TLSv1.2", "TLSv1.3") -or `
        $report.plaintext_http_accepted -or $report.external_publication_approved -or `
        $report.external_network_used -or $report.certificate_sha256.Length -ne 64) {
        throw "The TLS report did not meet its fail-closed contract."
    }
    $report | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $reportPath -Encoding UTF8
    Write-Host "Loopback TLS API integration completed successfully."
    Write-Host "Report: $reportPath"
} finally {
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & docker compose --profile tls --profile database stop tls-api 2>&1 | Out-Null
    $ErrorActionPreference = $previousErrorActionPreference
    foreach ($temporaryFile in @($certificatePath, $privateKeyPath)) {
        if (Test-Path -LiteralPath $temporaryFile -PathType Leaf) {
            Remove-Item -LiteralPath $temporaryFile -Force
        }
    }
}
