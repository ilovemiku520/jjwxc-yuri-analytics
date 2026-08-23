[CmdletBinding()]
param([switch]$SkipDockerRefresh)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$reportDirectory = Join-Path $projectRoot "var\reports"
$outputPath = Join-Path $reportDirectory "phase3_security_review.json"
Set-Location -LiteralPath $projectRoot

if (-not $SkipDockerRefresh) {
    & (Join-Path $PSScriptRoot "run-identity-integration.ps1")
    if ($LASTEXITCODE -ne 0) { throw "Identity integration refresh failed." }
    & (Join-Path $PSScriptRoot "run-tls-integration.ps1")
    if ($LASTEXITCODE -ne 0) { throw "TLS integration refresh failed." }
}

& (Join-Path $PSScriptRoot "run-publication-evidence.ps1")
if ($LASTEXITCODE -ne 0) { throw "Publication evidence bundle refresh failed." }
& (Join-Path $PSScriptRoot "run-publication-review.ps1")

$phase2 = Get-Content -Raw -LiteralPath (Join-Path $reportDirectory "phase2_exit_review.json") |
    ConvertFrom-Json
$identity = Get-Content -Raw -LiteralPath (Join-Path $reportDirectory "identity_integration.json") |
    ConvertFrom-Json
$tls = Get-Content -Raw -LiteralPath (Join-Path $reportDirectory "tls_integration.json") |
    ConvertFrom-Json
$publication = Get-Content -Raw -LiteralPath `
    (Join-Path $reportDirectory "publication_review.json") | ConvertFrom-Json
$publicationEvidence = Get-Content -Raw -LiteralPath `
    (Join-Path $reportDirectory "publication_evidence_bundle.json") | ConvertFrom-Json

if ($phase2.status -ne "passed_private_only" -or `
    -not $phase2.shared_consumer_controls_verified -or `
    -not $phase2.trusted_proxy_adapter_verified -or -not $phase2.loopback_tls_verified -or `
    $identity.status -ne "passed" -or $identity.raw_subject_exposed -or `
    $tls.status -ne "passed" -or $tls.plaintext_http_accepted -or `
    $publicationEvidence.status -ne "passed_non_secret_fail_closed" -or `
    $publicationEvidence.forbidden_secret_properties_present -or `
    $publicationEvidence.external_publication_approved -or `
    $publicationEvidence.real_source_collection_authorized -or `
    $publicationEvidence.external_network_used -or `
    $publication.status -ne "blocked" -or $publication.external_publication_approved -or `
    $publication.real_source_collection_authorized -or $publication.violations.Count -eq 0) {
    throw "Phase 3 security evidence is inconsistent or not fail-closed."
}

$temporarySecretPresent = Test-Path -LiteralPath `
    (Join-Path $projectRoot "var\identity-smoke\proxy-secret")
$temporaryPrivateKeyPresent = Test-Path -LiteralPath `
    (Join-Path $projectRoot "var\tls-smoke\private-key.pem")
if ($temporarySecretPresent -or $temporaryPrivateKeyPresent) {
    throw "A temporary Phase 3 secret was not cleaned up."
}

$report = [pscustomobject]@{
    generated_at = [DateTimeOffset]::UtcNow.ToString("o")
    status = "passed_offline_controls_publication_blocked"
    private_read_api_ready = $true
    shared_consumer_controls_verified = $true
    trusted_proxy_adapter_verified = $true
    default_deny_cors_verified = $true
    loopback_tls_verified = $true
    publication_evidence_bundle_verified = $true
    production_certificate_trust_reviewed = $false
    real_identity_proxy_deployment_reviewed = $false
    temporary_secrets_cleaned = $true
    external_publication_approved = $false
    real_source_collection_authorized = $false
    real_source_collection_count = 0
    remaining_publication_controls = @($publication.violations)
    external_network_used = $false
}
$report | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $outputPath -Encoding UTF8

Write-Host "Phase 3 offline security review completed successfully."
Write-Host "External publication remains blocked. Report: $outputPath"
