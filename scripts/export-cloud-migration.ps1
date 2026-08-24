[CmdletBinding()]
param(
    [string]$ContainerName = "",
    [string]$OutputRoot = "",
    [switch]$VerifyRestore
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location -LiteralPath $projectRoot

$postgresUser = if ($env:PYURI_POSTGRES_USER) { $env:PYURI_POSTGRES_USER } else { "pyuri" }
$postgresDatabase = if ($env:PYURI_POSTGRES_DB) { $env:PYURI_POSTGRES_DB } else { "pyuri" }
if ($postgresUser -notmatch '^[a-z_][a-z0-9_]{0,62}$' -or
    $postgresDatabase -notmatch '^[a-z_][a-z0-9_]{0,62}$') {
    throw "Unsafe PostgreSQL user or database identifier."
}

if (-not $ContainerName) {
    $ContainerName = ((& docker compose --profile database ps -q postgres) -join "").Trim()
}
if (-not $ContainerName -or $ContainerName -notmatch '^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$') {
    throw "A safe running PostgreSQL container name or ID is required."
}
$running = ((& docker inspect --format '{{.State.Running}}' $ContainerName 2>$null) -join "").Trim()
if ($LASTEXITCODE -ne 0 -or $running -ne "true") {
    throw "The selected PostgreSQL container is not running."
}

if (-not $OutputRoot) { $OutputRoot = Join-Path $projectRoot "var\releases" }
$outputRootAbsolute = [System.IO.Path]::GetFullPath($OutputRoot, $projectRoot)
New-Item -ItemType Directory -Force -Path $outputRootAbsolute | Out-Null
$token = [guid]::NewGuid().ToString("N").Substring(0, 12)
$timestamp = [DateTimeOffset]::UtcNow.ToString("yyyyMMddTHHmmssZ")
$bundleName = "jjwxc-cloud-migration-$timestamp-$token"
$bundleDirectory = Join-Path $outputRootAbsolute $bundleName
$zipPath = "$bundleDirectory.zip"
$zipChecksumPath = "$zipPath.sha256"
if ((Test-Path -LiteralPath $bundleDirectory) -or (Test-Path -LiteralPath $zipPath)) {
    throw "The migration bundle target already exists."
}
New-Item -ItemType Directory -Path $bundleDirectory | Out-Null

$containerDumpPath = "/tmp/$bundleName.dump"
$hostDumpPath = Join-Path $bundleDirectory "database.dump"
$restoreDatabase = "pyuri_migration_verify_$token"
$restoreCreated = $false
$strictTables = @(
    "crawl_runs",
    "crawl_tasks",
    "jjwxc_author_snapshots",
    "jjwxc_authors",
    "jjwxc_catalog_index",
    "jjwxc_channel_ranking_snapshots",
    "jjwxc_chapter_snapshots",
    "jjwxc_discovery_queue",
    "jjwxc_novel_snapshots",
    "jjwxc_novels",
    "jjwxc_ranking_snapshots"
)

function Get-TableCounts {
    param(
        [Parameter(Mandatory = $true)][string]$Container,
        [Parameter(Mandatory = $true)][string]$Database,
        [Parameter(Mandatory = $true)][string]$User,
        [Parameter(Mandatory = $true)][string[]]$Tables
    )
    $counts = [ordered]@{}
    foreach ($table in $Tables) {
        if ($table -notmatch '^[a-z_]+$') { throw "Unsafe table name in verification set." }
        $raw = ((& docker exec $Container psql -v ON_ERROR_STOP=1 -U $User -d $Database `
            -tA -c "SELECT count(*) FROM ingest.$table;") -join "").Trim()
        if ($LASTEXITCODE -ne 0 -or $raw -notmatch '^[0-9]+$') {
            throw "Could not count ingest.$table."
        }
        $counts[$table] = [long]$raw
    }
    return $counts
}

try {
    $sourceCounts = Get-TableCounts -Container $ContainerName -Database $postgresDatabase `
        -User $postgresUser -Tables $strictTables
    $schemaVersion = ((& docker exec $ContainerName psql -v ON_ERROR_STOP=1 `
        -U $postgresUser -d $postgresDatabase -tA `
        -c "SELECT version_num FROM public.alembic_version;") -join "").Trim()
    if ($LASTEXITCODE -ne 0 -or $schemaVersion -notmatch '^[0-9_]+$') {
        throw "The source Alembic version could not be verified."
    }

    docker exec $ContainerName pg_dump -U $postgresUser -d $postgresDatabase `
        --format=custom --no-owner --no-privileges -f $containerDumpPath
    if ($LASTEXITCODE -ne 0) { throw "PostgreSQL logical backup failed." }
    docker cp "${ContainerName}:$containerDumpPath" $hostDumpPath
    if ($LASTEXITCODE -ne 0) { throw "The database dump could not be copied to the host bundle." }

    $dumpSha256 = (Get-FileHash -LiteralPath $hostDumpPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $dumpSize = (Get-Item -LiteralPath $hostDumpPath).Length
    if ($dumpSha256 -notmatch '^[0-9a-f]{64}$' -or $dumpSize -le 0) {
        throw "The database dump checksum or size is invalid."
    }

    $restoreCounts = $null
    if ($VerifyRestore) {
        if ($restoreDatabase -notmatch '^pyuri_migration_verify_[0-9a-f]{12}$') {
            throw "Unsafe verification database name."
        }
        docker exec $ContainerName createdb -U $postgresUser $restoreDatabase
        if ($LASTEXITCODE -ne 0) { throw "The isolated verification database could not be created." }
        $restoreCreated = $true
        docker exec $ContainerName pg_restore -U $postgresUser -d $restoreDatabase `
            --exit-on-error --no-owner --no-privileges $containerDumpPath
        if ($LASTEXITCODE -ne 0) { throw "The isolated verification restore failed." }
        $restoreCounts = Get-TableCounts -Container $ContainerName -Database $restoreDatabase `
            -User $postgresUser -Tables $strictTables
        $restoredVersion = ((& docker exec $ContainerName psql -v ON_ERROR_STOP=1 `
            -U $postgresUser -d $restoreDatabase -tA `
            -c "SELECT version_num FROM public.alembic_version;") -join "").Trim()
        if ($restoredVersion -ne $schemaVersion) { throw "Restored Alembic version does not match." }
        foreach ($table in $strictTables) {
            if ($restoreCounts[$table] -ne $sourceCounts[$table]) {
                throw "Restored row count mismatch for ingest.$table."
            }
        }
    }

    $manifest = [ordered]@{
        source_format = "pyuri_jjwxc_cloud_migration_bundle"
        schema_version = 1
        generated_at = [DateTimeOffset]::UtcNow.ToString("o")
        database_dump = "database.dump"
        database_dump_format = "postgresql_custom"
        database_dump_sha256 = $dumpSha256
        database_dump_size_bytes = $dumpSize
        alembic_version = $schemaVersion
        strict_table_counts = $sourceCounts
        restore_drill_performed = [bool]$VerifyRestore
        restore_drill_passed = [bool]$VerifyRestore
        restored_table_counts = $restoreCounts
        passwords_included = $false
        environment_secrets_included = $false
        source_html_included_separately = $false
    }
    $manifestPath = Join-Path $bundleDirectory "manifest.json"
    $manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $manifestPath -Encoding utf8
    Copy-Item -LiteralPath (Join-Path $projectRoot "scripts\restore-cloud-postgres.ps1") `
        -Destination (Join-Path $bundleDirectory "restore-cloud-postgres.ps1")
    Copy-Item -LiteralPath (Join-Path $projectRoot "deploy\cloud-migration\cloud.env.example") `
        -Destination (Join-Path $bundleDirectory "cloud.env.example")
    Copy-Item -LiteralPath (Join-Path $projectRoot "deploy\cloud-migration\README.md") `
        -Destination (Join-Path $bundleDirectory "README.md")

    Compress-Archive -Path (Join-Path $bundleDirectory "*") -DestinationPath $zipPath
    $zipSha256 = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
    "$zipSha256  $([System.IO.Path]::GetFileName($zipPath))" | `
        Set-Content -LiteralPath $zipChecksumPath -Encoding ascii
    $report = [ordered]@{
        status = "passed"
        generated_at = [DateTimeOffset]::UtcNow.ToString("o")
        bundle_directory = $bundleDirectory
        bundle_zip = $zipPath
        bundle_zip_sha256 = $zipSha256
        database_dump_sha256 = $dumpSha256
        database_dump_size_bytes = $dumpSize
        alembic_version = $schemaVersion
        restore_drill_passed = [bool]$VerifyRestore
    }
    $reportPath = Join-Path $projectRoot "var\reports\cloud_migration_latest.json"
    $report | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $reportPath -Encoding utf8
    Write-Host "Cloud migration bundle created and verified."
    Write-Host "Bundle: $zipPath"
    Write-Host "SHA-256: $zipSha256"
} finally {
    if ($restoreCreated -and $restoreDatabase -match '^pyuri_migration_verify_[0-9a-f]{12}$') {
        & docker exec $ContainerName dropdb --if-exists -U $postgresUser $restoreDatabase 2>&1 | Out-Null
    }
    & docker exec $ContainerName rm -f $containerDumpPath 2>&1 | Out-Null
}

$global:LASTEXITCODE = 0
