[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$reportPath = Join-Path $projectRoot "var\reports\web_integration.json"
Set-Location -LiteralPath $projectRoot

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    $dockerDesktopBin = Join-Path $env:LOCALAPPDATA "Programs\DockerDesktop\resources\bin"
    $dockerDesktopCli = Join-Path $dockerDesktopBin "docker.exe"
    if (Test-Path -LiteralPath $dockerDesktopCli) {
        $env:Path = "$dockerDesktopBin;$env:Path"
    } else {
        throw "Docker CLI is not installed or is absent from PATH."
    }
}

$env:PYURI_POSTGRES_IMAGE = if ($env:PYURI_POSTGRES_IMAGE) {
    $env:PYURI_POSTGRES_IMAGE
} else { "m.daocloud.io/docker.io/library/postgres:17" }
$env:PYURI_PYTHON_BASE_IMAGE = if ($env:PYURI_PYTHON_BASE_IMAGE) {
    $env:PYURI_PYTHON_BASE_IMAGE
} else { "m.daocloud.io/docker.io/library/python:3.12-slim" }
$env:PYURI_NODE_BASE_IMAGE = if ($env:PYURI_NODE_BASE_IMAGE) {
    $env:PYURI_NODE_BASE_IMAGE
} else { "m.daocloud.io/docker.io/library/node:22-alpine" }
$webPort = if ($env:PYURI_WEB_PORT) { [int]$env:PYURI_WEB_PORT } else { 3000 }

docker compose --profile web --profile api --profile database up `
    -d --build --wait --wait-timeout 360 web
if ($LASTEXITCODE -ne 0) {
    docker compose --profile web --profile api --profile database logs --tail 120 web api
    throw "The Web container did not become healthy."
}

function Invoke-LoopbackWebRequest {
    param([string]$Path)
    return Invoke-WebRequest `
        -Uri "http://127.0.0.1:$webPort$Path" `
        -UseBasicParsing `
        -TimeoutSec 10
}

function Invoke-ContainerWebRequest {
    param([string]$Path)
    $nodeCode = "fetch('http://127.0.0.1:3000$Path').then(async r=>console.log(JSON.stringify({status:r.status,nosniff:r.headers.get('x-content-type-options'),referrer:r.headers.get('referrer-policy'),body:Buffer.from(await r.text()).toString('base64')})))"
    $rendered = (& docker compose exec -T web node -e $nodeCode) -join "`n"
    if ($LASTEXITCODE -ne 0) { throw "Container-internal Web verification failed." }
    $payload = $rendered | ConvertFrom-Json
    return [pscustomobject]@{
        StatusCode = [int]$payload.status
        Headers = @{
            "X-Content-Type-Options" = [string]$payload.nosniff
            "Referrer-Policy" = [string]$payload.referrer
        }
        Content = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($payload.body))
    }
}

$accessMode = "container_internal_fallback"
$paths = [ordered]@{
    home = "/"
    data_policy = "/about/data-policy"
    works = "/works"
    work_detail = "/works/synthetic-work-1001"
    authors = "/authors"
    author_detail = "/authors/synthetic-author-501"
    tags = "/tags"
    tag_graph = "/tags/graph"
    tag_review = "/tags/review"
    tag_detail = "/tags/synthetic-tag-a"
    operations = "/operations"
    readiness = "/operations/readiness"
    schemas = "/operations/schemas"
    runs = "/operations/runs"
    tasks = "/operations/tasks"
    security = "/operations/security"
    quarantine = "/operations/quarantine"
}
$responses = @{}
$publishedWebPort = (& docker compose port web 3000 2>$null) -join ""
if ($LASTEXITCODE -eq 0 -and $publishedWebPort) {
    try {
        $accessMode = "host_loopback"
        foreach ($entry in $paths.GetEnumerator()) {
            $responses[$entry.Key] = Invoke-LoopbackWebRequest $entry.Value
        }
    } catch {
        $accessMode = "container_internal_fallback"
        $responses = @{}
    }
}
if ($accessMode -eq "container_internal_fallback") {
    foreach ($entry in $paths.GetEnumerator()) {
        $responses[$entry.Key] = Invoke-ContainerWebRequest $entry.Value
    }
}

foreach ($entry in $responses.GetEnumerator()) {
    if ($entry.Value.StatusCode -ne 200) {
        throw "Web route $($entry.Key) did not return HTTP 200."
    }
    if ($entry.Value.Headers["X-Content-Type-Options"] -ne "nosniff") {
        throw "Web route $($entry.Key) omitted nosniff."
    }
    if ($entry.Value.Headers["Referrer-Policy"] -ne "no-referrer") {
        throw "Web route $($entry.Key) omitted no-referrer."
    }
    if ($entry.Value.Content -match 'http://api:8000|authorization|password|source_url|payload_object_key|config_snapshot|requested_by|logical_target|idempotency_key|task_attempt_id') {
        throw "Web route $($entry.Key) exposed an internal or prohibited value."
    }
}
$evidenceChecks = [ordered]@{
    data_policy = 'NON-COMMERCIAL'
    works = 'Synthetic Work Alpha'
    authors = 'Synthetic Author'
    tags = 'synthetic-tag-a'
    tag_graph = 'Tag associations'
    tag_review = 'Human review evidence'
    schemas = 'discovered'
    runs = 'offline_fixture_ingest'
    tasks = 'fixture_fetch'
    security = 'PostgreSQL'
    # React may insert hydration-boundary comments between adjacent text nodes.
    readiness = '10(?:<!-- -->)?/(?:<!-- -->)?12'
    quarantine = 'page-end'
}
foreach ($check in $evidenceChecks.GetEnumerator()) {
    $response = $responses[$check.Key]
    for ($attempt = 1; $attempt -le 3 -and $response.Content -notmatch $check.Value; $attempt++) {
        Start-Sleep -Seconds 1
        $response = if ($accessMode -eq "host_loopback") {
            Invoke-LoopbackWebRequest $paths[$check.Key]
        } else {
            Invoke-ContainerWebRequest $paths[$check.Key]
        }
    }
    if ($response.StatusCode -ne 200 -or $response.Content -notmatch $check.Value) {
        throw "Web route $($check.Key) did not render its Fixture evidence."
    }
    if ($response.Content -match 'http://api:8000|authorization|password|source_url|payload_object_key|config_snapshot|requested_by|logical_target|idempotency_key|task_attempt_id') {
        throw "Web route $($check.Key) exposed an internal or prohibited value after retry."
    }
    $responses[$check.Key] = $response
}

$report = [pscustomobject]@{
    generated_at = [DateTimeOffset]::UtcNow.ToString("o")
    status = "passed"
    route_count = $responses.Count
    all_routes_status_200 = $true
    fixture_data_rendered = $true
    security_headers_verified = $true
    internal_api_origin_exposed = $false
    prohibited_fields_exposed = $false
    collection_network_enabled = $false
    verification_access_mode = $accessMode
}
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $reportPath) | Out-Null
$report | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $reportPath -Encoding UTF8
Write-Host "Web container integration completed successfully."
Write-Host "Routes: $($responses.Count), access: $accessMode, report: $reportPath"
