[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateCount(1, 25)]
    [string[]]$ExportPath,

    [Parameter(Mandatory = $false)]
    [ValidateSet("powerful_pixiv_downloader_json", "pyuri_pixiv_browser_companion_json")]
    [string]$ExpectedSourceFormat
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location -LiteralPath $projectRoot

try {
    $exportFiles = @($ExportPath | ForEach-Object {
        Get-Item -LiteralPath (Resolve-Path -LiteralPath $_ -ErrorAction Stop).Path
    })
} catch {
    throw "One or more browser-export JSON files do not exist."
}
if ($exportFiles.Where({ $_.PSIsContainer -or $_.Extension -ne ".json" }).Count -ne 0) {
    throw "Every input must be a JSON file created by the user."
}
if (($exportFiles | Measure-Object -Property Length -Sum).Sum -gt 10000000) {
    throw "The JSON export batch exceeds the 10 MB offline-import limit."
}
$exportDirectories = @($exportFiles.DirectoryName | Sort-Object -Unique)
if ($exportDirectories.Count -ne 1) {
    throw "All files in one offline batch must be in the same directory."
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker CLI is unavailable. Start Docker Desktop and retry."
}

$candidateDirectory = Join-Path $projectRoot "var\candidates"
$reportDirectory = Join-Path $projectRoot "var\reports"
New-Item -ItemType Directory -Force -Path $candidateDirectory, $reportDirectory | Out-Null

$previousExportDirectory = $env:PYURI_BROWSER_EXPORT_DIR
$previousExportFile = $env:PYURI_BROWSER_EXPORT_FILE
$previousPythonImage = $env:PYURI_PYTHON_BASE_IMAGE
try {
    $env:PYURI_BROWSER_EXPORT_DIR = $exportDirectories[0]
    $env:PYURI_BROWSER_EXPORT_FILE = $exportFiles[0].Name
    if (-not $env:PYURI_PYTHON_BASE_IMAGE) {
        $env:PYURI_PYTHON_BASE_IMAGE = "m.daocloud.io/docker.io/library/python:3.12-slim"
    }

    $dockerArguments = @(
        "compose", "--profile", "offline-import", "run", "--rm", "--build",
        "browser-export-import"
    )
    $dockerArguments += @($exportFiles | ForEach-Object { "/imports/$($_.Name)" })
    $dockerArguments += @(
        "--output", "/candidates/browser-export.candidate.jsonl",
        "--report", "/reports/browser-export-import.json", "--force"
    )
    & docker @dockerArguments
    $importExitCode = $LASTEXITCODE
} finally {
    $env:PYURI_BROWSER_EXPORT_DIR = $previousExportDirectory
    $env:PYURI_BROWSER_EXPORT_FILE = $previousExportFile
    $env:PYURI_PYTHON_BASE_IMAGE = $previousPythonImage
}

$reportPath = Join-Path $reportDirectory "browser-export-import.json"
if (-not (Test-Path -LiteralPath $reportPath -PathType Leaf)) {
    throw "The offline importer did not create its audit report."
}
$report = Get-Content -Raw -LiteralPath $reportPath | ConvertFrom-Json
if ($report.credentials_requested -or $report.external_network_used -or `
    $report.media_persisted -or $report.raw_payload_persisted -or `
    $report.visibility_verified -or $report.canonical_ingest_authorized) {
    throw "The offline import report violated the fixed safety boundary."
}
if ($ExpectedSourceFormat -and $report.source_format -ne $ExpectedSourceFormat) {
    throw "The JSON source format does not match this launcher."
}

Write-Host "Browser export review: $($report.status)"
Write-Host "Source format: $($report.source_format)"
Write-Host "Files: $($report.input_files)"
Write-Host "Accepted: $($report.accepted_records); rejected: $($report.rejected_records)"
Write-Host "Candidate: $candidateDirectory\browser-export.candidate.jsonl"
Write-Host "Report: $reportPath"

if ($importExitCode -ne 0 -or $report.status -ne "candidate_ready") {
    throw "The export was safely blocked. Review the value-free report."
}

$global:LASTEXITCODE = 0
