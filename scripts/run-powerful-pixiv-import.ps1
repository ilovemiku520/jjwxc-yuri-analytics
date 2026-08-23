[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$ExportPath
)

$ErrorActionPreference = "Stop"
& (Join-Path $PSScriptRoot "run-browser-export-import.ps1") `
    -ExportPath $ExportPath `
    -ExpectedSourceFormat "powerful_pixiv_downloader_json"
