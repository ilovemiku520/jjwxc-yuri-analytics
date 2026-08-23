[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$ExportDirectory
)

$ErrorActionPreference = "Stop"
$directory = Get-Item -LiteralPath (Resolve-Path -LiteralPath $ExportDirectory).Path
if (-not $directory.PSIsContainer) {
    throw "The batch input must be a directory."
}
$exports = @(Get-ChildItem -LiteralPath $directory.FullName -File |
    Where-Object { $_.Name -like "pyuri-pixiv-metadata-*.json" } |
    Sort-Object -Property Name)
if ($exports.Count -eq 0) {
    throw "No Yuri Cultural Index browser-companion JSON files were found."
}
if ($exports.Count -gt 25) {
    throw "A batch may contain at most 25 browser-companion exports."
}
& (Join-Path $PSScriptRoot "run-pyuri-browser-companion-import.ps1") `
    -ExportPath @($exports.FullName)

