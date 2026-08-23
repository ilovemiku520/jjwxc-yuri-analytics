[CmdletBinding()]
param(
    [switch]$Elevated
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$reportPath = Join-Path $projectRoot "var\reports\wsl_update.json"

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-IsAdministrator)) {
    if ($Elevated) {
        throw "Elevation was requested, but the process is still not an administrator."
    }
    $arguments = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", ('"{0}"' -f $PSCommandPath),
        "-Elevated"
    )
    $process = Start-Process -FilePath "powershell.exe" -Verb RunAs `
        -ArgumentList $arguments -Wait -PassThru
    exit $process.ExitCode
}

$wsl = Join-Path $env:SystemRoot "System32\wsl.exe"
$attempts = @()

Write-Host "Updating WSL through the direct web-download channel."
& $wsl --update --web-download
$attempts += [pscustomobject]@{
    channel = "web-download"
    exit_code = $LASTEXITCODE
}

if ($LASTEXITCODE -ne 0) {
    Write-Warning "Direct download failed; retrying through the Microsoft Store channel."
    & $wsl --update
    $attempts += [pscustomobject]@{
        channel = "store"
        exit_code = $LASTEXITCODE
    }
}

if ($attempts[-1].exit_code -ne 0) {
    throw "Both WSL update channels failed. Review the error above and retry later."
}

Write-Host "Setting WSL 2 as the default version."
& $wsl --set-default-version 2
$defaultExit = $LASTEXITCODE
if ($defaultExit -ne 0) {
    throw "WSL updated, but setting default version 2 failed with exit code $defaultExit."
}

& $wsl --shutdown
$shutdownExit = $LASTEXITCODE

$report = [pscustomobject]@{
    generated_at = [DateTimeOffset]::UtcNow.ToString("o")
    attempts = $attempts
    default_version = 2
    set_default_exit_code = $defaultExit
    shutdown_exit_code = $shutdownExit
    docker_restart_required = $true
}

$reportDirectory = Split-Path -Parent $reportPath
New-Item -ItemType Directory -Force -Path $reportDirectory | Out-Null
$report | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $reportPath -Encoding UTF8

Write-Host ""
Write-Host "WSL update completed. Close and reopen Docker Desktop."
Write-Host "Report: $reportPath"
