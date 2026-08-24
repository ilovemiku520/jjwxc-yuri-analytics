[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location -LiteralPath $projectRoot
$checks = [System.Collections.Generic.List[object]]::new()

function Add-Check {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][bool]$Passed,
        [Parameter(Mandatory = $true)][string]$Detail
    )
    $checks.Add([ordered]@{ name = $Name; passed = $Passed; detail = $Detail })
}

function Read-RailwayConfig {
    param([Parameter(Mandatory = $true)][string]$RelativePath)
    $absolute = Join-Path $projectRoot $RelativePath
    Add-Check "$RelativePath.exists" (Test-Path -LiteralPath $absolute -PathType Leaf) `
        "Railway service config exists"
    if (-not (Test-Path -LiteralPath $absolute -PathType Leaf)) { return $null }
    try { return Get-Content -Raw -LiteralPath $absolute | ConvertFrom-Json }
    catch { Add-Check "$RelativePath.json" $false "Invalid JSON"; return $null }
}

$api = Read-RailwayConfig "deploy\railway\api.railway.json"
$web = Read-RailwayConfig "deploy\railway\web.railway.json"
$daily = Read-RailwayConfig "deploy\railway\daily.railway.json"
$schema = "https://railway.com/railway.schema.json"
foreach ($item in @(
    @{ name = "api"; config = $api; dockerfile = "apps/api/Dockerfile" },
    @{ name = "web"; config = $web; dockerfile = "apps/web/Dockerfile" },
    @{ name = "daily"; config = $daily; dockerfile = "apps/api/Dockerfile" }
)) {
    if ($null -eq $item.config) { continue }
    Add-Check "$($item.name).schema" ($item.config.'$schema' -eq $schema) "Official Railway schema URL"
    Add-Check "$($item.name).builder" ($item.config.build.builder -eq "DOCKERFILE") "Dockerfile builder"
    Add-Check "$($item.name).dockerfile_path" `
        ($item.config.build.dockerfilePath -eq $item.dockerfile -and
         (Test-Path -LiteralPath (Join-Path $projectRoot $item.dockerfile) -PathType Leaf)) `
        "Repository-relative Dockerfile exists"
}

if ($null -ne $api) {
    Add-Check "api.start" ($api.deploy.startCommand -eq "pyuri-api") "Bounded FastAPI entry point"
    Add-Check "api.migration" `
        ($api.deploy.preDeployCommand.Count -eq 1 -and
         $api.deploy.preDeployCommand[0] -eq "pyuri-db migrate --alembic-config /app/alembic.ini") `
        "Alembic migration runs before API deployment"
    Add-Check "api.health" `
        ($api.deploy.healthcheckPath -eq "/health/ready" -and
         $api.deploy.healthcheckTimeout -ge 30 -and $api.deploy.healthcheckTimeout -le 300) `
        "Readiness endpoint and bounded timeout"
    Add-Check "api.restart" `
        ($api.deploy.restartPolicyType -eq "ON_FAILURE" -and
         $api.deploy.restartPolicyMaxRetries -ge 1 -and $api.deploy.restartPolicyMaxRetries -le 5) `
        "Bounded failure restart policy"
}

if ($null -ne $web) {
    Add-Check "web.health" `
        ($web.deploy.healthcheckPath -eq "/" -and
         $web.deploy.healthcheckTimeout -ge 30 -and $web.deploy.healthcheckTimeout -le 300) `
        "Public Web health check"
    Add-Check "web.restart" `
        ($web.deploy.restartPolicyType -eq "ON_FAILURE" -and
         $web.deploy.restartPolicyMaxRetries -ge 1 -and $web.deploy.restartPolicyMaxRetries -le 5) `
        "Bounded failure restart policy"
}

if ($null -ne $daily) {
    $command = [string]$daily.deploy.startCommand
    function Get-CommandInteger {
        param([string]$Argument)
        $match = [regex]::Match($command, "(?:^|\s)$([regex]::Escape($Argument))\s+([0-9]+)(?:\s|$)")
        if ($match.Success) { return [int]$match.Groups[1].Value }
        return -1
    }
    $indexPages = Get-CommandInteger "--index-pages"
    $hydrateLimit = Get-CommandInteger "--hydrate-limit"
    $authorLimit = Get-CommandInteger "--author-limit"
    $interval = Get-CommandInteger "--request-interval-seconds"
    Add-Check "daily.command" ($command.StartsWith("jjyuri-jjwxc-catalog ")) "Finite catalog collector command"
    Add-Check "daily.bounds" `
        ($indexPages -ge 1 -and $indexPages -le 10 -and
         $hydrateLimit -ge 1 -and $hydrateLimit -le 49 -and
         $authorLimit -ge 0 -and $authorLimit -le 10 -and $interval -ge 2) `
        "index_pages=$indexPages hydrate_limit=$hydrateLimit author_limit=$authorLimit interval=$interval"
    Add-Check "daily.cron" ($daily.deploy.cronSchedule -eq "30 19 * * *") `
        "UTC 19:30 equals Asia/Shanghai 03:30 next day"
    Add-Check "daily.restart" ($daily.deploy.restartPolicyType -eq "NEVER") `
        "Cron run is not restarted into an overlapping collection"
}

$environmentTemplate = Join-Path $projectRoot "deploy\cloud-migration\cloud.env.example"
$environmentText = if (Test-Path -LiteralPath $environmentTemplate) {
    Get-Content -Raw -LiteralPath $environmentTemplate
} else { "" }
$requiredVariables = @(
    "PYURI_DATABASE_URL",
    "PYURI_COHORT_IMPORT_TOKEN",
    "PYURI_API_HOST",
    "PYURI_API_DEPLOYMENT_SCOPE",
    "PYURI_SHARED_CONSUMER_CONTROLS_ENABLED",
    "PYURI_INTERNAL_API_URL",
    "JJYURI_ENABLE_NETWORK"
)
foreach ($variable in $requiredVariables) {
    Add-Check "variables.$variable" ($environmentText -match "(?m)^$variable=") "Documented cloud variable"
}
Add-Check "variables.no_private_key" ($environmentText -notmatch "BEGIN .*PRIVATE KEY") `
    "No private key material in template"

$failed = @($checks | Where-Object { -not $_.passed })
$report = [ordered]@{
    status = $(if ($failed.Count) { "failed" } else { "passed_with_legacy_config_warning" })
    generated_at = [DateTimeOffset]::UtcNow.ToString("o")
    check_count = $checks.Count
    failed_check_count = $failed.Count
    checks = $checks
    required_service_variables = [ordered]@{
        api = @("PYURI_DATABASE_URL", "PYURI_API_HOST", "PYURI_API_DEPLOYMENT_SCOPE", "PYURI_SHARED_CONSUMER_CONTROLS_ENABLED", "PYURI_COHORT_IMPORT_TOKEN")
        web = @("PYURI_INTERNAL_API_URL", "PYURI_COHORT_IMPORT_TOKEN")
        daily = @("PYURI_DATABASE_URL", "JJYURI_ENABLE_NETWORK")
    }
    config_as_code_notice = "Railway Config as Code remains usable for legacy services until 2026-12-01; migrate to Railway Infrastructure as Code after initial recovery deployment."
    official_references = @(
        "https://docs.railway.com/config-as-code/reference",
        "https://docs.railway.com/cron-jobs",
        "https://docs.railway.com/deployments/pre-deploy-command",
        "https://docs.railway.com/builds/dockerfiles"
    )
    external_cloud_resources_created = $false
    secrets_validated = $false
}
$reportPath = Join-Path $projectRoot "var\reports\railway_preflight.json"
$report | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $reportPath -Encoding utf8
if ($failed.Count) {
    $failed | ForEach-Object { Write-Error "$($_.name): $($_.detail)" }
    throw "Railway deployment preflight failed."
}
Write-Host "Railway deployment preflight passed with a legacy Config-as-Code warning."
Write-Host "Report: $reportPath"
$global:LASTEXITCODE = 0
