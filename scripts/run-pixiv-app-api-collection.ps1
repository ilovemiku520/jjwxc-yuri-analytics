[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$collector = Join-Path $projectRoot ".venv\Scripts\pyuri-pixiv-app-api.exe"
if (-not (Test-Path -LiteralPath $collector -PathType Leaf)) {
    throw "The project Pixiv App API environment is not installed."
}

Write-Host "Pixiv App API candidate collection (private research; no media)."
Write-Host "Login opens in the project Chrome profile; complete login/CAPTCHA yourself."
Write-Host "The project extension returns the short-lived OAuth callback automatically."
Write-Host "1 = tag/word search; 2 = author works; 3 = ranking"
$choice = Read-Host "Choose an operation"
switch ($choice) {
    "1" {
        $operation = "search"
        $value = Read-Host "Search word or tag"
    }
    "2" {
        $operation = "author"
        $value = Read-Host "Numeric Pixiv author ID"
    }
    "3" {
        $operation = "ranking"
        $value = Read-Host "Ranking mode, for example day or week_r18"
    }
    default { throw "Unknown operation." }
}
$pagesText = Read-Host "Maximum pages (1-100, default 10)"
$pages = if ([string]::IsNullOrWhiteSpace($pagesText)) { 10 } else { [int]$pagesText }
if ($pages -lt 1 -or $pages -gt 100) {
    throw "Maximum pages must be between 1 and 100."
}

Set-Location -LiteralPath $projectRoot
& $collector --auth-mode "oauth-pkce" --callback-mode "automatic" --max-pages $pages `
    --proxy "http://127.0.0.1:41080" `
    --confirm "UNOFFICIAL-APP-API" --force $operation $value
if ($LASTEXITCODE -ne 0) {
    throw "Pixiv App API candidate collection was safely blocked."
}
Write-Host "Candidate: $projectRoot\var\candidates\pixiv-app-api.candidate.jsonl"
Write-Host "Report: $projectRoot\var\reports\pixiv-app-api-collection.json"
