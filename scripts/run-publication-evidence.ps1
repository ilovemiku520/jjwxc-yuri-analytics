[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$reportDirectory = Join-Path $projectRoot "var\reports"
$schemaPath = Join-Path $reportDirectory "publication_deployment.schema.json"
$draftPath = Join-Path $reportDirectory "publication_deployment.generated-draft.json"
$reviewPath = Join-Path $reportDirectory "publication_generated_draft_review.json"
$bundlePath = Join-Path $reportDirectory "publication_evidence_bundle.json"
Set-Location -LiteralPath $projectRoot

& $python -m pixiv_yuri.api.publication_evidence schema --output $schemaPath --force
if ($LASTEXITCODE -ne 0) { throw "Publication manifest Schema generation failed." }
& $python -m pixiv_yuri.api.publication_evidence init --output $draftPath --force
if ($LASTEXITCODE -ne 0) { throw "Publication draft initialization failed." }

& $python -m pixiv_yuri.api.publication_review `
    --phase2-report var/reports/phase2_exit_review.json `
    --manifest $draftPath `
    --output $reviewPath
$reviewExitCode = $LASTEXITCODE
if ($reviewExitCode -ne 2) {
    throw "The generated draft was not rejected by the publication gate."
}

$schema = Get-Content -Raw -LiteralPath $schemaPath | ConvertFrom-Json
$draft = Get-Content -Raw -LiteralPath $draftPath | ConvertFrom-Json
$review = Get-Content -Raw -LiteralPath $reviewPath | ConvertFrom-Json
if ($schema.'$id' -ne "urn:pixiv-yuri-analytics:publication-deployment-manifest:v1" -or `
    $schema.additionalProperties -ne $false) {
    throw "The generated publication Schema is not the pinned fail-closed version."
}
if ($draft.status -ne "draft" -or $review.status -ne "blocked" -or `
    $review.external_publication_approved -or $review.real_source_collection_authorized -or `
    $review.external_network_used -or $review.violations.Count -eq 0) {
    throw "The generated publication evidence did not remain fail-closed."
}

$forbiddenKeys = @("account_password", "browser_cookie", "hmac_secret", "private_key", "session_token")
function Assert-NoForbiddenProperty {
    param([object]$Value)
    if ($null -eq $Value) { return }
    if ($Value -is [System.Array]) {
        foreach ($item in $Value) { Assert-NoForbiddenProperty -Value $item }
        return
    }
    if ($Value -is [pscustomobject]) {
        foreach ($property in $Value.PSObject.Properties) {
            if ($forbiddenKeys -contains $property.Name) {
                throw "A forbidden secret-shaped property exists in publication evidence."
            }
            Assert-NoForbiddenProperty -Value $property.Value
        }
    }
}
Assert-NoForbiddenProperty -Value $draft

function Get-ArtifactSha256 {
    param([Parameter(Mandatory = $true)][string]$LiteralPath)
    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    $stream = [System.IO.File]::OpenRead($LiteralPath)
    try {
        $hash = $sha256.ComputeHash($stream)
        return ([System.BitConverter]::ToString($hash)).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $stream.Dispose()
        $sha256.Dispose()
    }
}

$bundle = [pscustomobject]@{
    generated_at = [DateTimeOffset]::UtcNow.ToString("o")
    status = "passed_non_secret_fail_closed"
    schema_id = $schema.'$id'
    schema_sha256 = Get-ArtifactSha256 -LiteralPath $schemaPath
    draft_sha256 = Get-ArtifactSha256 -LiteralPath $draftPath
    draft_review_status = $review.status
    violation_count = $review.violations.Count
    forbidden_secret_properties_present = $false
    external_publication_approved = $false
    real_source_collection_authorized = $false
    external_network_used = $false
}
$bundle | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $bundlePath -Encoding UTF8

Write-Host "Publication evidence bundle completed safely."
Write-Host "Status: blocked by design; report: $bundlePath"
$global:LASTEXITCODE = 0
