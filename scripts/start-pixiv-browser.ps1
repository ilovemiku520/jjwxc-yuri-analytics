[CmdletBinding()]
param(
    [string]$StartUrl = "https://www.pixiv.net/",
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"

$warpCli = "C:\Program Files\Cloudflare\Cloudflare WARP\warp-cli.exe"
$chrome = "C:\Program Files\Google\Chrome\Application\chrome.exe"
$bridgeScript = Join-Path $PSScriptRoot "pixiv_proxy_bridge.py"
$extensionPath = Join-Path (Split-Path $PSScriptRoot -Parent) "apps\browser-extension"
$appDataRoot = Join-Path $env:LOCALAPPDATA "PixivYuriAnalytics"
$profilePath = Join-Path $appDataRoot "ChromeProfile"
$logPath = Join-Path $appDataRoot "logs\pixiv-proxy-bridge.log"
$bridgePort = 41080
$warpPort = 40000

if (-not (Test-Path -LiteralPath $warpCli)) {
    throw "Cloudflare WARP is not installed."
}
if (-not (Test-Path -LiteralPath $bridgeScript)) {
    throw "Pixiv proxy bridge script is missing."
}
if (-not $NoBrowser -and -not (Test-Path -LiteralPath $chrome)) {
    throw "Google Chrome is not installed."
}

& $warpCli mode proxy | Out-Null
& $warpCli proxy port $warpPort | Out-Null
& $warpCli connect | Out-Null

$deadline = (Get-Date).AddSeconds(20)
do {
    Start-Sleep -Milliseconds 500
    $warpReady = Get-NetTCPConnection `
        -LocalAddress "127.0.0.1" `
        -LocalPort $warpPort `
        -State Listen `
        -ErrorAction SilentlyContinue
} while (-not $warpReady -and (Get-Date) -lt $deadline)
if (-not $warpReady) {
    throw "WARP local proxy did not become ready on 127.0.0.1:$warpPort."
}

$bridgeReady = Get-NetTCPConnection `
    -LocalAddress "127.0.0.1" `
    -LocalPort $bridgePort `
    -State Listen `
    -ErrorAction SilentlyContinue
if (-not $bridgeReady) {
    $projectRoot = Split-Path $PSScriptRoot -Parent
    $pythonCandidates = @(
        (Join-Path $projectRoot ".venv\Scripts\pythonw.exe"),
        (Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\pythonw.exe")
    )
    $executable = $pythonCandidates |
        Where-Object { Test-Path -LiteralPath $_ } |
        Select-Object -First 1
    if (-not $executable) {
        $python = Get-Command python -ErrorAction Stop
        if ($python.Source -like "*\WindowsApps\python.exe") {
            throw "No usable Python runtime was found. Install Python 3.12 or create .venv."
        }
        $executable = $python.Source
    }
    New-Item -ItemType Directory -Path (Split-Path $logPath -Parent) -Force | Out-Null
    $arguments = @(
        $bridgeScript,
        "--listen-port", $bridgePort,
        "--warp-port", $warpPort,
        "--log-file", $logPath
    )
    Start-Process `
        -FilePath $executable `
        -ArgumentList $arguments `
        -WindowStyle Hidden | Out-Null

    $deadline = (Get-Date).AddSeconds(20)
    do {
        Start-Sleep -Milliseconds 500
        $bridgeReady = Get-NetTCPConnection `
            -LocalAddress "127.0.0.1" `
            -LocalPort $bridgePort `
            -State Listen `
            -ErrorAction SilentlyContinue
    } while (-not $bridgeReady -and (Get-Date) -lt $deadline)
}
if (-not $bridgeReady) {
    throw "Pixiv proxy bridge did not become ready. See $logPath"
}

$probe = & curl.exe `
    --proxy "http://127.0.0.1:$bridgePort" `
    --head `
    --output NUL `
    --silent `
    --show-error `
    --max-time 25 `
    --write-out "%{http_code}" `
    "https://www.pixiv.net/" 2>&1
if ($LASTEXITCODE -ne 0 -or $probe -ne "200") {
    throw "Pixiv connectivity probe failed: $probe. See $logPath"
}

if (-not $NoBrowser) {
    New-Item -ItemType Directory -Path $profilePath -Force | Out-Null
    $browserArguments = @(
        "--user-data-dir=$profilePath",
        "--no-first-run",
        "--no-default-browser-check",
        "--proxy-server=http://127.0.0.1:$bridgePort",
        "--proxy-bypass-list=<-loopback>",
        "--disable-extensions-except=$extensionPath",
        "--load-extension=$extensionPath",
        $StartUrl
    )
    Start-Process `
        -FilePath $chrome `
        -ArgumentList $browserArguments `
        -WindowStyle Normal | Out-Null
}

[pscustomobject]@{
    status = "ready"
    warp_proxy = "127.0.0.1:$warpPort"
    pixiv_proxy = "127.0.0.1:$bridgePort"
    chrome_profile = $profilePath
    extension = $extensionPath
    probe_http_status = [int]$probe
    system_proxy_changed = $false
    default_route_changed = $false
} | ConvertTo-Json
