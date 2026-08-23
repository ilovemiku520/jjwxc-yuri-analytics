[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateCount(1, 25)]
    [string[]]$ExportPath
)

$ErrorActionPreference = "Stop"
& (Join-Path $PSScriptRoot "run-browser-export-import.ps1") `
    -ExportPath $ExportPath `
    -ExpectedSourceFormat "pyuri_pixiv_browser_companion_json"
