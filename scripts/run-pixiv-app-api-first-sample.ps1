[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$collector = Join-Path $projectRoot ".venv\Scripts\pyuri-pixiv-app-api.exe"
if (-not (Test-Path -LiteralPath $collector -PathType Leaf)) {
    throw "The project Pixiv App API environment is not installed."
}

Write-Host "One-page Pixiv App API sample: search '百合', metadata only."
Write-Host "Complete Pixiv login/CAPTCHA yourself in the project Chrome window."
Write-Host "The project extension will return the short-lived callback automatically."

Set-Location -LiteralPath $projectRoot
& $collector --auth-mode "oauth-pkce" --callback-mode "automatic" --max-pages 1 `
    --proxy "http://127.0.0.1:41080" `
    --confirm "UNOFFICIAL-APP-API" --force search "百合"
if ($LASTEXITCODE -ne 0) {
    throw "The one-page Pixiv App API sample was safely blocked."
}

Write-Host "One-page candidate collection completed."
Write-Host "Candidate: $projectRoot\var\candidates\pixiv-app-api.candidate.jsonl"
Write-Host "Report: $projectRoot\var\reports\pixiv-app-api-collection.json"
