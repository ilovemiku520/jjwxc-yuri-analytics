[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$workspaceRoot = (Resolve-Path (Join-Path $projectRoot "..\..")).Path
$rtk = Join-Path $PSScriptRoot "invoke-rtk.ps1"
$rtkExecutable = Join-Path $workspaceRoot "tools\rtk-bin\app\rtk.exe"
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$reportPath = Join-Path $projectRoot "var\reports\rtk_quality_smoke.json"
$logPath = Join-Path $projectRoot "var\reports\rtk_quality_smoke.log"
$rtkStateRoot = Join-Path $projectRoot "var\rtk"
$logLines = [System.Collections.Generic.List[string]]::new()
$qualitySessionId = [Guid]::NewGuid()
$qualityDatabasePath = Join-Path $rtkStateRoot ("session-{0}.db" -f $qualitySessionId.ToString("N"))
$previousSessionId = $env:PYURI_RTK_SESSION_ID

Set-Location -LiteralPath $projectRoot
$env:PYURI_ENABLE_NETWORK = "false"

function Invoke-RtkCheck {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [ValidateSet("version", "pytest", "ruff", "mypy", "gain")]
        [string]$Profile
    )

    $output = @(& $rtk -Profile $Profile 2>&1)
    $exitCode = $LASTEXITCODE
    foreach ($line in $output) {
        Write-Host ([string]$line)
    }
    if ($exitCode -ne 0) {
        $logLines.Add("[$Name] failed exit=$exitCode")
        $logLines | Set-Content -LiteralPath $logPath -Encoding UTF8
        throw "$Name failed with exit code $exitCode. Status log saved to $logPath"
    }
    $logLines.Add("[$Name] passed")
    return $output
}

function Get-Sha256Hex {
    param([Parameter(Mandatory = $true)][string]$LiteralPath)
    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    $stream = [System.IO.File]::OpenRead($LiteralPath)
    try {
        return ([BitConverter]::ToString($sha256.ComputeHash($stream))).Replace("-", "").ToLowerInvariant()
    } finally {
        $stream.Dispose()
        $sha256.Dispose()
    }
}

try {
    $env:PYURI_RTK_SESSION_ID = $qualitySessionId.ToString("D")
    $versionOutput = @(Invoke-RtkCheck -Name "version" -Profile "version")
    $versionMatch = [regex]::Match(($versionOutput -join "`n"), 'rtk\s+([0-9]+\.[0-9]+\.[0-9]+)')
    if (-not $versionMatch.Success) {
        throw "RTK version output was not recognized."
    }
    $rtkVersion = $versionMatch.Groups[1].Value

    Invoke-RtkCheck -Name "pytest" -Profile "pytest" | Out-Null

    $collectionOutput = @(& $python -m pytest --collect-only -q -p no:cacheprovider -o addopts= 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "Native pytest collection verification failed."
    }
    $collectionText = $collectionOutput -join "`n"
    $collectionMatch = [regex]::Match($collectionText, '(\d+) tests collected')
    if (-not $collectionMatch.Success) {
        throw "Native pytest collection count was not found."
    }
    $pytestCount = [int]$collectionMatch.Groups[1].Value

    Invoke-RtkCheck -Name "ruff" -Profile "ruff" | Out-Null
    Invoke-RtkCheck -Name "mypy" -Profile "mypy" | Out-Null
    Invoke-RtkCheck -Name "gain" -Profile "gain" | Out-Null

    $logLines | Set-Content -LiteralPath $logPath -Encoding UTF8
    $report = [ordered]@{
        generated_at = [DateTimeOffset]::UtcNow.ToString("o")
        status = "passed"
        rtk_version = $rtkVersion
        archive_sha256 = "34cea9009a8099acdaf85147b971d95f65efabfa63fb3aea7d3e2b73e6f517c3"
        executable_sha256 = Get-Sha256Hex -LiteralPath $rtkExecutable
        executable_integrity_checked_each_invocation = $true
        telemetry_disabled = $true
        raw_failure_tee_disabled = $true
        global_hook_install_attempted = $false
        tracking_scope = "ephemeral_quality_session"
        tracking_database_deleted_after_run = $true
        pytest = "passed"
        pytest_count = $pytestCount
        rtk_pytest_summary_compatibility = "Avoided double-quiet mode; native collection count also verified."
        ruff = "passed"
        mypy_strict = "passed"
        source_transport_invoked = $false
        status_log = "var/reports/rtk_quality_smoke.log"
    }
    $report | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $reportPath -Encoding UTF8

    Write-Host "RTK quality smoke completed successfully."
    Write-Host "Report: $reportPath"
} finally {
    if ($null -eq $previousSessionId) {
        [Environment]::SetEnvironmentVariable("PYURI_RTK_SESSION_ID", $null, "Process")
    } else {
        $env:PYURI_RTK_SESSION_ID = $previousSessionId
    }
    if (Test-Path -LiteralPath $qualityDatabasePath -PathType Leaf) {
        Remove-Item -LiteralPath $qualityDatabasePath -Force
    }
}
