param(
    [ValidatePattern('^[1-9][0-9]{0,11}$')]
    [string]$NovelId = '10806685'
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Project virtual environment is missing.'
}

$previousNetwork = [Environment]::GetEnvironmentVariable('JJYURI_ENABLE_NETWORK', 'Process')
try {
    [Environment]::SetEnvironmentVariable('JJYURI_ENABLE_NETWORK', 'true', 'Process')
    & $pythonPath -m pixiv_yuri.jjwxc.public_probe $NovelId --execute-live
    if ($LASTEXITCODE -ne 0) {
        throw 'JJWXC public metadata probe failed.'
    }
} finally {
    [Environment]::SetEnvironmentVariable('JJYURI_ENABLE_NETWORK', $previousNetwork, 'Process')
}
