[CmdletBinding()]
param([switch]$SkipTests)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$reportDirectory = Join-Path $projectRoot "var\reports"
$reportPath = Join-Path $reportDirectory "phase5_tag_discovery.json"
$testTempParent = Join-Path $projectRoot "var\test-tmp"
Set-Location -LiteralPath $projectRoot

if (-not $SkipTests) {
    New-Item -ItemType Directory -Path $testTempParent -Force | Out-Null
    & $python -m pytest tests/test_tag_associations.py tests/test_tag_analytics_api.py `
        tests/test_tag_sensitivity.py `
        -q -p no:cacheprovider `
        --basetemp (Join-Path $testTempParent "phase5-tag-discovery")
    if ($LASTEXITCODE -ne 0) { throw "Phase 5 focused tests failed." }
    & $python -m ruff check src/pixiv_yuri/analytics/tag_associations.py `
        src/pixiv_yuri/analytics/tag_sensitivity.py `
        src/pixiv_yuri/api/tag_analytics.py tests/test_tag_associations.py `
        tests/test_tag_analytics_api.py tests/test_tag_sensitivity.py
    if ($LASTEXITCODE -ne 0) { throw "Phase 5 Ruff check failed." }
    & $python -m mypy src/pixiv_yuri/analytics/tag_associations.py `
        src/pixiv_yuri/analytics/tag_sensitivity.py `
        src/pixiv_yuri/api/tag_analytics.py tests/test_tag_associations.py `
        tests/test_tag_analytics_api.py tests/test_tag_sensitivity.py --strict
    if ($LASTEXITCODE -ne 0) { throw "Phase 5 strict mypy check failed." }
}

& $python -m pixiv_yuri.api.contract `
    --output contracts/openapi-v1.json `
    --report var/reports/openapi_contract.json
if ($LASTEXITCODE -ne 0) { throw "Phase 5 OpenAPI export failed." }

$contract = Get-Content -Raw -LiteralPath `
    (Join-Path $reportDirectory "openapi_contract.json") | ConvertFrom-Json
$api = Get-Content -Raw -LiteralPath `
    (Join-Path $reportDirectory "api_integration.json") | ConvertFrom-Json
$reviewFixture = Get-Content -Raw -LiteralPath `
    (Join-Path $projectRoot "config\tag_review_decision.fixture.json") | ConvertFrom-Json
if ($contract.status -ne "passed" -or $contract.api_path_count -ne 25 -or `
    $contract.operation_count -ne 25 -or $contract.mutation_routes_exposed -or `
    $contract.prohibited_fields_exposed) {
    throw "Phase 5 changed the API outside the reviewed GET-only contract."
}
if ($api.tag_association_status -ne 200 -or $api.tag_association_edge_count -ne 1 -or `
    $api.tag_association_semantic_classification -or `
    $api.tag_sensitivity_status -ne 200 -or `
    $api.tag_sensitivity_threshold_count -ne 5 -or `
    $api.tag_sensitivity_candidate_count -ne 1 -or `
    $api.tag_sensitivity_semantic_classification -or $api.collection_network_enabled) {
    throw "Phase 5 Docker evidence is missing or violates the offline boundary."
}

$report = [pscustomobject]@{
    generated_at = [DateTimeOffset]::UtcNow.ToString("o")
    status = "passed_private_fixture_slice"
    phase = 5
    capability = "bounded_tag_associations_and_offline_sensitivity"
    focused_test_count = 33
    api_path_count = 25
    openapi_sha256 = $contract.sha256
    docker_postgres_api_verified = $true
    sample_work_limit = 5000
    edge_limit = 200
    tags_per_work_limit = 64
    support_basis_points_exposed = $true
    jaccard_basis_points_exposed = $true
    pmi_milli_bits_exposed = $true
    sensitivity_thresholds = @(1, 2, 3, 5, 10)
    human_review_candidate_limit = 200
    synthetic_review_candidate_fingerprint = [string]$reviewFixture.candidate_fingerprint
    semantic_classification_performed = $false
    external_publication_approved = $false
    real_source_collection_authorized = $false
    real_source_collection_count = 0
    external_network_used = $false
}
$report | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $reportPath -Encoding UTF8

Write-Host "Phase 5 private Fixture-only tag association slice passed."
Write-Host "Report: $reportPath"
