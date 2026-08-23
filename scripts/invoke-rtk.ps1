[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("version", "pytest", "ruff", "mypy", "gain")]
    [string]$Profile
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$workspaceRoot = (Resolve-Path (Join-Path $projectRoot "..\..")).Path
$rtkExecutable = Join-Path $workspaceRoot "tools\rtk-bin\app\rtk.exe"
$rtkStateRoot = Join-Path $projectRoot "var\rtk"
$venvScripts = Join-Path $projectRoot ".venv\Scripts"
$expectedExecutableHash = "888ECFCC7CA6CEAF9170CF95027D196D6010C7D1A1892B3662B4BB61F18A3618"

if (-not (Test-Path -LiteralPath $rtkExecutable -PathType Leaf)) {
    throw "Project-local RTK executable is missing: $rtkExecutable"
}
$sha256 = [System.Security.Cryptography.SHA256]::Create()
$rtkStream = [System.IO.File]::OpenRead($rtkExecutable)
try {
    $actualExecutableHash = ([BitConverter]::ToString($sha256.ComputeHash($rtkStream))).Replace("-", "")
} finally {
    $rtkStream.Dispose()
    $sha256.Dispose()
}
if ($actualExecutableHash -ne $expectedExecutableHash) {
    throw "Project-local RTK executable failed its SHA-256 integrity check."
}

New-Item -ItemType Directory -Force -Path $rtkStateRoot | Out-Null
$sessionId = $env:PYURI_RTK_SESSION_ID
$sharedSession = -not [string]::IsNullOrWhiteSpace($sessionId)
if ($sharedSession) {
    $parsedSessionId = [Guid]::Empty
    if (-not [Guid]::TryParse($sessionId, [ref]$parsedSessionId)) {
        throw "RTK session identifier must be a GUID."
    }
    $rtkDatabasePath = Join-Path $rtkStateRoot ("session-{0}.db" -f $parsedSessionId.ToString("N"))
} else {
    $rtkDatabasePath = Join-Path $rtkStateRoot ("single-{0}.db" -f ([Guid]::NewGuid().ToString("N")))
}

$environmentNames = @(
    "CLAUDE_CONFIG_DIR",
    "RTK_DB_PATH",
    "RTK_TELEMETRY_DISABLED",
    "RTK_TEE",
    "Path"
)
$previousEnvironment = @{}
foreach ($name in $environmentNames) {
    $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
}
$previousLocation = Get-Location
$rtkExitCode = 1

try {
    # Keep all transient RTK state local. No hook path is created.
    $env:CLAUDE_CONFIG_DIR = Join-Path $rtkStateRoot "no-claude-install"
    $env:RTK_DB_PATH = $rtkDatabasePath
    $env:RTK_TELEMETRY_DISABLED = "1"
    $env:RTK_TEE = "0"
    if (Test-Path -LiteralPath $venvScripts -PathType Container) {
        $env:Path = "$venvScripts;$($previousEnvironment['Path'])"
    }
    Set-Location -LiteralPath $projectRoot
    switch ($Profile) {
        "version" { & $rtkExecutable --version }
        "pytest" { & $rtkExecutable pytest -p no:cacheprovider -o addopts= }
        "ruff" { & $rtkExecutable ruff check . }
        "mypy" { & $rtkExecutable mypy }
        "gain" { & $rtkExecutable gain }
    }
    $rtkExitCode = $LASTEXITCODE
} finally {
    Set-Location -LiteralPath $previousLocation
    foreach ($name in $environmentNames) {
        $previousValue = $previousEnvironment[$name]
        if ($null -eq $previousValue) {
            [Environment]::SetEnvironmentVariable($name, $null, "Process")
        } else {
            [Environment]::SetEnvironmentVariable($name, [string]$previousValue, "Process")
        }
    }
    if (-not $sharedSession -and (Test-Path -LiteralPath $rtkDatabasePath -PathType Leaf)) {
        Remove-Item -LiteralPath $rtkDatabasePath -Force
    }
}

exit $rtkExitCode
