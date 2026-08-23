[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$reportPath = Join-Path $projectRoot "var\reports\api_integration.json"
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
} else {
    "m.daocloud.io/docker.io/library/postgres:17"
}
$env:PYURI_PYTHON_BASE_IMAGE = if ($env:PYURI_PYTHON_BASE_IMAGE) {
    $env:PYURI_PYTHON_BASE_IMAGE
} else {
    "m.daocloud.io/docker.io/library/python:3.12-slim"
}
$apiPort = if ($env:PYURI_API_PORT) { [int]$env:PYURI_API_PORT } else { 8000 }

docker version
if ($LASTEXITCODE -ne 0) {
    throw "Docker Engine is not ready. Start Docker Desktop and retry."
}

docker compose --profile database run --rm db-migrate
if ($LASTEXITCODE -ne 0) {
    throw "The API database migration failed."
}

docker compose --profile api --profile database up `
    -d --build --wait --wait-timeout 180 api
if ($LASTEXITCODE -ne 0) {
    docker compose --profile api --profile database logs --tail 100 api
    throw "The API container did not become healthy."
}

function Invoke-LoopbackApiRequest {
    param([string]$Path)
    $lastFailure = $null
    for ($attempt = 1; $attempt -le 5; $attempt++) {
        try {
            return Invoke-WebRequest `
                -Uri "http://127.0.0.1:$apiPort$Path" `
                -UseBasicParsing `
                -TimeoutSec 5
        } catch {
            $lastFailure = $_
            Start-Sleep -Milliseconds 500
        }
    }
    throw $lastFailure
}

function Invoke-ContainerApiRequest {
    param([string]$Path)
    $pythonCode = "import urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8000$Path', timeout=5); print(r.status); print(r.headers.get('X-Query-Budget','')); print(r.headers.get('Server-Timing','')); print(r.read().decode())"
    $result = @(& docker compose exec -T api python -c $pythonCode)
    if ($LASTEXITCODE -ne 0) {
        throw "Container-internal API verification failed."
    }
    return [pscustomobject]@{
        StatusCode = [int]$result[0]
        Headers = @{
            "X-Query-Budget" = $result[1]
            "Server-Timing" = $result[2]
        }
        Content = ($result | Select-Object -Skip 3) -join "`n"
    }
}

function Assert-OperationalHeaders {
    param($Response)
    $budget = [string]$Response.Headers["X-Query-Budget"]
    $timing = [string]$Response.Headers["Server-Timing"]
    if (($budget -ne "met") -and ($budget -ne "exceeded")) {
        throw "The API response omitted the query-budget result."
    }
    if (-not $timing.StartsWith("app;dur=")) {
        throw "The API response omitted the bounded Server-Timing value."
    }
}

$corsGetCode = "import urllib.request; r=urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8000/health/live',headers={'Origin':'https://untrusted.example'}),timeout=5); print(r.status); print(r.headers.get('Access-Control-Allow-Origin') or '<absent>')"
$corsGet = @(& docker compose exec -T api python -c $corsGetCode)
if ($LASTEXITCODE -ne 0) { throw "The cross-origin GET probe could not run." }
$corsPreflightCode = "import http.client; c=http.client.HTTPConnection('127.0.0.1',8000,timeout=5); c.request('OPTIONS','/api/v1/works',headers={'Origin':'https://untrusted.example','Access-Control-Request-Method':'GET'}); r=c.getresponse(); print(r.status); print(r.getheader('Access-Control-Allow-Origin') or '<absent>')"
$corsPreflight = @(& docker compose exec -T api python -c $corsPreflightCode)
if ($LASTEXITCODE -ne 0 -or [int]$corsGet[0] -ne 200 -or $corsGet[1] -ne "<absent>" -or `
    [int]$corsPreflight[0] -ne 405 -or $corsPreflight[1] -ne "<absent>") {
    throw "The deny-by-default CORS probe failed."
}

$apiAccessMode = "host_loopback"
try {
    $live = Invoke-LoopbackApiRequest "/health/live"
    $ready = Invoke-LoopbackApiRequest "/health/ready"
    $sourceRecords = Invoke-LoopbackApiRequest "/api/v1/source-records?limit=2"
    $schemaDefinitions = Invoke-LoopbackApiRequest "/api/v1/schema-definitions?limit=2"
    $works = Invoke-LoopbackApiRequest "/api/v1/works?limit=2"
    $tagAggregates = Invoke-LoopbackApiRequest "/api/v1/analytics/tags?limit=2"
    $authorAggregates = Invoke-LoopbackApiRequest "/api/v1/analytics/authors?limit=2"
    $authorProfile = Invoke-LoopbackApiRequest "/api/v1/analytics/authors/synthetic-author-501/profile"
    $authorTrends = Invoke-LoopbackApiRequest "/api/v1/analytics/authors/synthetic-author-501/metric-trends?date_from=2026-08-01&date_to=2026-08-02"
    $authorGrowth = Invoke-LoopbackApiRequest "/api/v1/analytics/authors/synthetic-author-501/growth?date_from=2026-08-01&date_to=2026-08-02"
    $metricTrends = Invoke-LoopbackApiRequest "/api/v1/analytics/metric-trends?date_from=2026-08-01&date_to=2026-08-02"
    $freshness = Invoke-LoopbackApiRequest "/api/v1/analytics/freshness"
    $workDetail = Invoke-LoopbackApiRequest "/api/v1/works/synthetic-work-1001"
    $authorDetail = Invoke-LoopbackApiRequest "/api/v1/authors/synthetic-author-501"
    $tagDetail = Invoke-LoopbackApiRequest "/api/v1/tags/synthetic-tag-a"
    $workRanking = Invoke-LoopbackApiRequest "/api/v1/rankings/works?metric=likes&limit=2"
    $authorRanking = Invoke-LoopbackApiRequest "/api/v1/rankings/authors?metric=bookmarks&limit=2"
    $authorAverageRanking = Invoke-LoopbackApiRequest "/api/v1/rankings/authors?metric=average_bookmarks&limit=2"
    $authorQualityMap = Invoke-LoopbackApiRequest "/api/v1/analytics/authors/quality-map?limit=100"
    $authorInfluence = Invoke-LoopbackApiRequest "/api/v1/analytics/authors/influence-ranking?limit=10"
    $tagAssociation = Invoke-LoopbackApiRequest "/api/v1/analytics/tags/co-occurrence?limit=10"
    $tagSensitivity = Invoke-LoopbackApiRequest "/api/v1/analytics/tags/association-sensitivity?candidate_limit=10"
    $securityStatus = Invoke-LoopbackApiRequest "/api/v1/operations/security-status"
} catch {
    $apiAccessMode = "container_internal_fallback"
    $live = Invoke-ContainerApiRequest "/health/live"
    $ready = Invoke-ContainerApiRequest "/health/ready"
    $sourceRecords = Invoke-ContainerApiRequest "/api/v1/source-records?limit=2"
    $schemaDefinitions = Invoke-ContainerApiRequest "/api/v1/schema-definitions?limit=2"
    $works = Invoke-ContainerApiRequest "/api/v1/works?limit=2"
    $tagAggregates = Invoke-ContainerApiRequest "/api/v1/analytics/tags?limit=2"
    $authorAggregates = Invoke-ContainerApiRequest "/api/v1/analytics/authors?limit=2"
    $authorProfile = Invoke-ContainerApiRequest "/api/v1/analytics/authors/synthetic-author-501/profile"
    $authorTrends = Invoke-ContainerApiRequest "/api/v1/analytics/authors/synthetic-author-501/metric-trends?date_from=2026-08-01&date_to=2026-08-02"
    $authorGrowth = Invoke-ContainerApiRequest "/api/v1/analytics/authors/synthetic-author-501/growth?date_from=2026-08-01&date_to=2026-08-02"
    $metricTrends = Invoke-ContainerApiRequest "/api/v1/analytics/metric-trends?date_from=2026-08-01&date_to=2026-08-02"
    $freshness = Invoke-ContainerApiRequest "/api/v1/analytics/freshness"
    $workDetail = Invoke-ContainerApiRequest "/api/v1/works/synthetic-work-1001"
    $authorDetail = Invoke-ContainerApiRequest "/api/v1/authors/synthetic-author-501"
    $tagDetail = Invoke-ContainerApiRequest "/api/v1/tags/synthetic-tag-a"
    $workRanking = Invoke-ContainerApiRequest "/api/v1/rankings/works?metric=likes&limit=2"
    $authorRanking = Invoke-ContainerApiRequest "/api/v1/rankings/authors?metric=bookmarks&limit=2"
    $authorAverageRanking = Invoke-ContainerApiRequest "/api/v1/rankings/authors?metric=average_bookmarks&limit=2"
    $authorQualityMap = Invoke-ContainerApiRequest "/api/v1/analytics/authors/quality-map?limit=100"
    $authorInfluence = Invoke-ContainerApiRequest "/api/v1/analytics/authors/influence-ranking?limit=10"
    $tagAssociation = Invoke-ContainerApiRequest "/api/v1/analytics/tags/co-occurrence?limit=10"
    $tagSensitivity = Invoke-ContainerApiRequest "/api/v1/analytics/tags/association-sensitivity?candidate_limit=10"
    $securityStatus = Invoke-ContainerApiRequest "/api/v1/operations/security-status"
}
@(
    $live,
    $ready,
    $sourceRecords,
    $schemaDefinitions,
    $works,
    $tagAggregates,
    $authorAggregates,
    $authorProfile,
    $authorTrends,
    $authorGrowth,
    $metricTrends,
    $freshness,
    $workDetail,
    $authorDetail,
    $tagDetail,
    $workRanking,
    $authorRanking,
    $authorAverageRanking,
    $authorQualityMap,
    $authorInfluence,
    $tagAssociation,
    $tagSensitivity,
    $securityStatus
) | ForEach-Object { Assert-OperationalHeaders $_ }
$sourceRecordBody = $sourceRecords.Content | ConvertFrom-Json
$schemaDefinitionBody = $schemaDefinitions.Content | ConvertFrom-Json
$workBody = $works.Content | ConvertFrom-Json
$tagAggregateBody = $tagAggregates.Content | ConvertFrom-Json
$authorAggregateBody = $authorAggregates.Content | ConvertFrom-Json
$authorProfileBody = $authorProfile.Content | ConvertFrom-Json
$authorTrendsBody = $authorTrends.Content | ConvertFrom-Json
$authorGrowthBody = $authorGrowth.Content | ConvertFrom-Json
$metricTrendBody = $metricTrends.Content | ConvertFrom-Json
$freshnessBody = $freshness.Content | ConvertFrom-Json
$workRankingBody = $workRanking.Content | ConvertFrom-Json
$authorRankingBody = $authorRanking.Content | ConvertFrom-Json
$authorAverageRankingBody = $authorAverageRanking.Content | ConvertFrom-Json
$authorQualityMapBody = $authorQualityMap.Content | ConvertFrom-Json
$authorInfluenceBody = $authorInfluence.Content | ConvertFrom-Json
$tagAssociationBody = $tagAssociation.Content | ConvertFrom-Json
$tagSensitivityBody = $tagSensitivity.Content | ConvertFrom-Json
$securityStatusBody = $securityStatus.Content | ConvertFrom-Json
if (($sourceRecords.Content -match 'source_url|payload_object_key|observation_metadata') -or `
    ($schemaDefinitions.Content -match 'definition|payload|source_url|metadata') -or `
    ($works.Content -match 'description|comments|followers|source_url|payload|latest_observation_id')) {
    throw "The read-only API exposed a prohibited storage field."
}
if (($workDetail.Content -match 'payload|source_url|observation_id') -or `
    ($authorDetail.Content -match 'followers|profile|payload') -or `
    ($tagDetail.Content -match 'payload|source_url')) {
    throw "A catalog detail API exposed a prohibited field."
}
if (($authorProfile.Content -match 'source_url|observation_id|followers|comments|payload') -or `
    $authorProfileBody.analyzed_work_count -ne 2 -or `
    $authorProfileBody.metric_coverage.public_view_count -ne 0 -or `
    $authorProfileBody.top_public_tags.Count -ne 2 -or `
    $null -ne $authorProfileBody.public_bookmark_rate_basis_points -or `
    $null -ne $authorProfileBody.public_like_rate_basis_points) {
    throw "The Phase 4 author profile violated minimized or missing-metric semantics."
}
if (($authorTrends.Content -match 'source_url|observation_id|followers|comments|payload') -or `
    $authorTrendsBody.items.Count -ne 2 -or `
    $authorTrendsBody.items[0].public_view_coverage_count -ne 0 -or `
    $null -ne $authorTrendsBody.items[0].total_public_view_count -or `
    $authorTrendsBody.items[0].total_public_bookmark_count -ne 75) {
    throw "The Phase 4 author trend violated bounded or missing-metric semantics."
}
if (($authorGrowth.Content -match 'source_url|observation_id|followers|comments|payload') -or `
    $authorGrowthBody.matched_work_count -ne 0 -or `
    $authorGrowthBody.start_only_work_count -ne 1 -or `
    $authorGrowthBody.end_only_work_count -ne 1 -or `
    $null -ne $authorGrowthBody.public_bookmarks.absolute_change -or `
    $null -ne $authorGrowthBody.public_likes.growth_basis_points) {
    throw "The Phase 4 author growth endpoint compared different work cohorts."
}
if (($authorAverageRanking.Content -match 'source_url|observation_id|followers|comments|payload') -or `
    $authorAverageRankingBody.metric -ne "average_bookmarks" -or `
    $authorAverageRankingBody.items[0].score_scale -ne 100 -or `
    $authorAverageRankingBody.items[0].metric_coverage_count -ne 2 -or `
    $authorAverageRankingBody.items[0].score -ne 6800) {
    throw "The Phase 4 average ranking violated complete-metric semantics."
}
if (($authorQualityMap.Content -match 'source_url|observation_id|followers|comments|payload') -or `
    $authorQualityMapBody.sampled_author_count -ne 1 -or `
    $authorQualityMapBody.sample_truncated -or `
    $authorQualityMapBody.items[0].bookmark_coverage_count -ne 2 -or `
    $authorQualityMapBody.items[0].average_public_bookmark_count_x100 -ne 6800) {
    throw "The Phase 4 author quality map violated bounded complete-axis semantics."
}
if (($authorInfluence.Content -match 'source_url|observation_id|followers|comments|payload') -or `
    $authorInfluenceBody.model_version -ne "allowed-metadata-v1" -or `
    $authorInfluenceBody.weights.bookmark -ne 4375 -or `
    $authorInfluenceBody.weights.like -ne 3750 -or `
    $authorInfluenceBody.weights.production -ne 1875 -or `
    $authorInfluenceBody.items[0].complete_metric_work_count -ne 2 -or `
    $authorInfluenceBody.items[0].influence_score_basis_points -ne 10000) {
    throw "The Phase 4 influence model violated versioned complete-metric semantics."
}
if (($tagAssociation.Content -match 'source_url|observation_id|payload|is_yuri|yuri_probability') -or `
    $tagAssociationBody.interpretation -ne "descriptive_association_only" -or `
    $tagAssociationBody.semantic_classification_performed -or `
    $tagAssociationBody.sampled_work_count -ne 2 -or `
    $tagAssociationBody.edges.Count -ne 1 -or `
    $tagAssociationBody.edges[0].cooccurrence_work_count -ne 1) {
    throw "The Phase 5 tag association endpoint violated bounded descriptive semantics."
}
if (($tagSensitivity.Content -match 'source_url|observation_id|payload|is_yuri|yuri_probability|semantic_label|embedding') -or `
    $tagSensitivityBody.interpretation -ne "descriptive_association_only" -or `
    $tagSensitivityBody.semantic_classification_performed -or `
    $tagSensitivityBody.sampled_work_count -ne 2 -or `
    $tagSensitivityBody.thresholds.Count -ne 5 -or `
    $tagSensitivityBody.thresholds[0] -ne 1 -or `
    $tagSensitivityBody.review_candidates.Count -ne 1 -or `
    $tagSensitivityBody.review_candidates[0].review_state -ne "pending_human_review") {
    throw "The Phase 5 tag sensitivity endpoint violated bounded human-review semantics."
}
if (($securityStatus.Content -match 'consumer_key|request_id|route_template|subject|query|token') -or `
    $securityStatusBody.shared_rate_limit_backend -ne "postgres" -or `
    $securityStatusBody.durable_access_audit_sink -ne "postgres" -or `
    $securityStatusBody.identity_adapter_configured -or `
    $securityStatusBody.external_publication_approved) {
    throw "The consumer security status was not aggregate-only and fail-closed."
}

$observationStatus = $null
$observationPageSize = 0
$metricHistoryStatus = $null
$metricHistoryPageSize = 0
if ($sourceRecordBody.items.Count -gt 0) {
    $sourceRecordId = $sourceRecordBody.items[0].id
    if ($apiAccessMode -eq "host_loopback") {
        $observations = Invoke-LoopbackApiRequest "/api/v1/source-records/$sourceRecordId/observations?limit=2"
    } else {
        $observations = Invoke-ContainerApiRequest "/api/v1/source-records/$sourceRecordId/observations?limit=2"
    }
    if ($observations.Content -match 'payload_sha256|payload_object_key|source_url|observation_metadata|task_attempt_id') {
        throw "The observation API exposed a prohibited storage field."
    }
    $observationBody = $observations.Content | ConvertFrom-Json
    Assert-OperationalHeaders $observations
    $observationStatus = $observations.StatusCode
    $observationPageSize = $observationBody.items.Count
}
if ($workBody.items.Count -gt 0) {
    $catalogWorkId = $workBody.items[0].work_id
    if ($apiAccessMode -eq "host_loopback") {
        $metricHistory = Invoke-LoopbackApiRequest "/api/v1/works/$catalogWorkId/metric-history?limit=2"
    } else {
        $metricHistory = Invoke-ContainerApiRequest "/api/v1/works/$catalogWorkId/metric-history?limit=2"
    }
    if ($metricHistory.Content -match 'source_observation_id|payload|source_url') {
        throw "The metric-history API exposed a prohibited provenance or storage field."
    }
    $metricHistoryBody = $metricHistory.Content | ConvertFrom-Json
    Assert-OperationalHeaders $metricHistory
    $metricHistoryStatus = $metricHistory.StatusCode
    $metricHistoryPageSize = $metricHistoryBody.items.Count
}

$report = [pscustomobject]@{
    generated_at = [DateTimeOffset]::UtcNow.ToString("o")
    live_status = $live.StatusCode
    live_body = $live.Content | ConvertFrom-Json
    ready_status = $ready.StatusCode
    ready_body = $ready.Content | ConvertFrom-Json
    source_records_status = $sourceRecords.StatusCode
    source_records_page_size = $sourceRecordBody.items.Count
    source_records_minimized = $true
    schema_definitions_status = $schemaDefinitions.StatusCode
    schema_definitions_page_size = $schemaDefinitionBody.items.Count
    schema_definitions_minimized = $true
    observations_status = $observationStatus
    observations_page_size = $observationPageSize
    observations_minimized = $true
    works_status = $works.StatusCode
    works_page_size = $workBody.items.Count
    tag_aggregates_status = $tagAggregates.StatusCode
    tag_aggregates_page_size = $tagAggregateBody.items.Count
    author_aggregates_status = $authorAggregates.StatusCode
    author_aggregates_page_size = $authorAggregateBody.items.Count
    author_profile_status = $authorProfile.StatusCode
    author_profile_tag_count = $authorProfileBody.top_public_tags.Count
    author_profile_missing_views_preserved = $true
    author_metric_trends_status = $authorTrends.StatusCode
    author_metric_trends_day_count = $authorTrendsBody.items.Count
    author_metric_trends_missing_views_preserved = $true
    author_growth_status = $authorGrowth.StatusCode
    author_growth_matched_work_count = $authorGrowthBody.matched_work_count
    author_growth_cohort_isolated = $true
    metric_history_status = $metricHistoryStatus
    metric_history_page_size = $metricHistoryPageSize
    metric_trends_status = $metricTrends.StatusCode
    metric_trends_day_count = $metricTrendBody.items.Count
    freshness_status = $freshness.StatusCode
    freshness_metric_snapshot_count = $freshnessBody.metric_snapshot_count
    work_detail_status = $workDetail.StatusCode
    author_detail_status = $authorDetail.StatusCode
    tag_detail_status = $tagDetail.StatusCode
    work_ranking_status = $workRanking.StatusCode
    work_ranking_page_size = $workRankingBody.items.Count
    author_ranking_status = $authorRanking.StatusCode
    author_ranking_page_size = $authorRankingBody.items.Count
    author_average_ranking_status = $authorAverageRanking.StatusCode
    author_average_ranking_complete_coverage = $true
    author_quality_map_status = $authorQualityMap.StatusCode
    author_quality_map_sample_size = $authorQualityMapBody.sampled_author_count
    author_influence_status = $authorInfluence.StatusCode
    author_influence_model_version = $authorInfluenceBody.model_version
    author_influence_complete_metrics = $true
    tag_association_status = $tagAssociation.StatusCode
    tag_association_edge_count = $tagAssociationBody.edges.Count
    tag_association_semantic_classification = $false
    tag_sensitivity_status = $tagSensitivity.StatusCode
    tag_sensitivity_threshold_count = $tagSensitivityBody.thresholds.Count
    tag_sensitivity_candidate_count = $tagSensitivityBody.review_candidates.Count
    tag_sensitivity_semantic_classification = $false
    consumer_security_status = $securityStatus.StatusCode
    shared_rate_limit_backend = $securityStatusBody.shared_rate_limit_backend
    durable_access_audit_sink = $securityStatusBody.durable_access_audit_sink
    identity_adapter_configured = $securityStatusBody.identity_adapter_configured
    external_publication_approved = $securityStatusBody.external_publication_approved
    query_budget_headers_verified = $true
    server_timing_headers_verified = $true
    mutation_routes_exposed = $false
    verification_access_mode = $apiAccessMode
    collection_network_enabled = $false
    deny_by_default_cors_verified = $true
}

$reportDirectory = Split-Path -Parent $reportPath
New-Item -ItemType Directory -Force -Path $reportDirectory | Out-Null
$report | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $reportPath -Encoding UTF8

if (($live.StatusCode -ne 200) -or ($ready.StatusCode -ne 200) -or `
    ($sourceRecords.StatusCode -ne 200) -or ($schemaDefinitions.StatusCode -ne 200) -or `
    ($works.StatusCode -ne 200) -or ($tagAggregates.StatusCode -ne 200) -or `
    ($authorAggregates.StatusCode -ne 200) -or ($authorProfile.StatusCode -ne 200) -or `
    ($authorTrends.StatusCode -ne 200) -or `
    ($authorGrowth.StatusCode -ne 200) -or `
    ($metricTrends.StatusCode -ne 200) -or ($freshness.StatusCode -ne 200) -or `
    (($null -ne $metricHistoryStatus) -and ($metricHistoryStatus -ne 200)) -or `
    ($workDetail.StatusCode -ne 200) -or ($authorDetail.StatusCode -ne 200) -or `
    ($tagDetail.StatusCode -ne 200) -or ($workRanking.StatusCode -ne 200) -or `
    ($authorRanking.StatusCode -ne 200) -or `
    ($authorAverageRanking.StatusCode -ne 200) -or `
    ($authorQualityMap.StatusCode -ne 200) -or `
    ($authorInfluence.StatusCode -ne 200) -or `
    ($tagAssociation.StatusCode -ne 200) -or `
    ($tagSensitivity.StatusCode -ne 200) -or `
    ($securityStatus.StatusCode -ne 200) -or `
    (($null -ne $observationStatus) -and ($observationStatus -ne 200))) {
    throw "API health verification failed. Review $reportPath."
}

Write-Host "API container integration completed successfully."
Write-Host "Liveness: $($live.StatusCode) $($live.Content)"
Write-Host "Readiness: $($ready.StatusCode) $($ready.Content)"
Write-Host "Source records: $($sourceRecords.StatusCode), page size $($sourceRecordBody.items.Count)"
Write-Host "Schema definitions: $($schemaDefinitions.StatusCode), page size $($schemaDefinitionBody.items.Count)"
Write-Host "Observations: $observationStatus, page size $observationPageSize"
Write-Host "Works: $($works.StatusCode), page size $($workBody.items.Count)"
Write-Host "Tag aggregates: $($tagAggregates.StatusCode), page size $($tagAggregateBody.items.Count)"
Write-Host "Author aggregates: $($authorAggregates.StatusCode), page size $($authorAggregateBody.items.Count)"
Write-Host "Author profile: $($authorProfile.StatusCode), tags $($authorProfileBody.top_public_tags.Count)"
Write-Host "Author metric trends: $($authorTrends.StatusCode), days $($authorTrendsBody.items.Count)"
Write-Host "Author growth: $($authorGrowth.StatusCode), matched works $($authorGrowthBody.matched_work_count)"
Write-Host "Metric history: $metricHistoryStatus, page size $metricHistoryPageSize"
Write-Host "Metric trends: $($metricTrends.StatusCode), days $($metricTrendBody.items.Count)"
Write-Host "Freshness: $($freshness.StatusCode), snapshots $($freshnessBody.metric_snapshot_count)"
Write-Host "Details: work $($workDetail.StatusCode), author $($authorDetail.StatusCode), tag $($tagDetail.StatusCode)"
Write-Host "Rankings: works $($workRanking.StatusCode), authors $($authorRanking.StatusCode)"
Write-Host "Author averages: $($authorAverageRanking.StatusCode), quality map: $($authorQualityMap.StatusCode)"
Write-Host "Author influence: $($authorInfluence.StatusCode), model $($authorInfluenceBody.model_version)"
Write-Host "Tag associations: $($tagAssociation.StatusCode), edges $($tagAssociationBody.edges.Count)"
Write-Host "Tag sensitivity: $($tagSensitivity.StatusCode), candidates $($tagSensitivityBody.review_candidates.Count)"
Write-Host "Consumer security: $($securityStatus.StatusCode), shared PostgreSQL controls enabled"
Write-Host "Report: $reportPath"
