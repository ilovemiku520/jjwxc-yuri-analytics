[CmdletBinding()]
param(
    [switch]$Elevated
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$reportPath = Join-Path $projectRoot "var\reports\docker_virtualization_setup.json"

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-IsAdministrator)) {
    if ($Elevated) {
        throw "Elevation was requested, but the process is still not an administrator."
    }
    $powershell = Join-Path $PSHOME "powershell.exe"
    $arguments = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", ('"{0}"' -f $PSCommandPath),
        "-Elevated"
    )
    $process = Start-Process -FilePath $powershell -Verb RunAs `
        -ArgumentList $arguments -Wait -PassThru
    exit $process.ExitCode
}

$featureResults = @()
foreach ($feature in @("Microsoft-Windows-Subsystem-Linux", "VirtualMachinePlatform")) {
    Write-Host "Enabling Windows feature: $feature"
    & "$env:SystemRoot\System32\dism.exe" /Online /Enable-Feature `
        "/FeatureName:$feature" /All /NoRestart
    $exitCode = $LASTEXITCODE
    if ($exitCode -notin @(0, 3010)) {
        throw "DISM failed for $feature with exit code $exitCode."
    }
    $state = Get-WindowsOptionalFeature -Online -FeatureName $feature
    $featureResults += [pscustomobject]@{
        name = $feature
        state = [string]$state.State
        restart_needed = [string]$state.RestartNeeded
        dism_exit_code = $exitCode
    }
}

Write-Host "Configuring the Windows hypervisor to launch automatically."
& "$env:SystemRoot\System32\bcdedit.exe" /set hypervisorlaunchtype auto
$bcdEditExit = $LASTEXITCODE
if ($bcdEditExit -ne 0) {
    Write-Warning ((
        "BCDEdit could not update the boot store (exit code {0}). " +
        "The required Windows features are enabled, so restart first and " +
        "verify the hypervisor after reboot."
    ) -f $bcdEditExit)
}

$wslUpdateExit = $null
$wslDefaultExit = $null
Write-Host "Updating WSL. A post-reboot retry may still be required."
& "$env:SystemRoot\System32\wsl.exe" --update --web-download
$wslUpdateExit = $LASTEXITCODE
& "$env:SystemRoot\System32\wsl.exe" --set-default-version 2
$wslDefaultExit = $LASTEXITCODE

$report = [pscustomobject]@{
    generated_at = [DateTimeOffset]::UtcNow.ToString("o")
    firmware_virtualization = $true
    slat = $true
    features = $featureResults
    hypervisor_launch_type_requested = "auto"
    bcdedit_exit_code = $bcdEditExit
    wsl_update_exit_code = $wslUpdateExit
    wsl_default_version_exit_code = $wslDefaultExit
    restart_required = $true
}

$reportDirectory = Split-Path -Parent $reportPath
New-Item -ItemType Directory -Force -Path $reportDirectory | Out-Null
$report | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $reportPath -Encoding UTF8

Write-Host ""
Write-Host "Windows virtualization prerequisites are configured."
Write-Host "Restart Windows before launching Docker Desktop again."
Write-Host "Report: $reportPath"
