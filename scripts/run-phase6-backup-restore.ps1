[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$reportPath = Join-Path $projectRoot "var\reports\phase6_backup_restore.json"
$projectName = "pyuri-phase6-drill-$([guid]::NewGuid().ToString('N').Substring(0, 12))"
if ($projectName -notmatch '^pyuri-phase6-drill-[0-9a-f]{12}$') {
    throw "Unsafe isolated Compose project name."
}

. (Join-Path $PSScriptRoot "runtime-database-secret.ps1")
$previousPassword = $env:PYURI_POSTGRES_PASSWORD
$env:PYURI_POSTGRES_PASSWORD = New-PyuriRuntimeDatabasePassword
$postgresUser = if ($env:PYURI_POSTGRES_USER) { $env:PYURI_POSTGRES_USER } else { "pyuri" }
$postgresDatabase = if ($env:PYURI_POSTGRES_DB) { $env:PYURI_POSTGRES_DB } else { "pyuri" }
$restoreDatabase = "pyuri_restore_drill"
$backupPath = "/tmp/phase6-backup.dump"
$hostBackupDirectory = Join-Path $projectRoot ".tmp\$projectName"
$hostBackupPath = Join-Path $hostBackupDirectory "phase6-backup.dump"
$sourceMigrationImage = "pixiv-yuri-analytics-db-migrate:latest"
$sourceFixtureImage = "pixiv-yuri-analytics-fixture-ingest:latest"
$temporaryMigrationImage = "$projectName-db-migrate:latest"
$temporaryFixtureImage = "$projectName-fixture-ingest:latest"
$temporaryImagesCreated = $false
$evidenceTables = @(
    "crawl_runs",
    "raw_observations",
    "schema_definitions",
    "quarantine_records",
    "catalog_authors",
    "catalog_works",
    "catalog_tags",
    "catalog_work_tags",
    "catalog_work_metric_snapshots"
)
$containerId = $null

function Get-PyuriTableCounts {
    param(
        [Parameter(Mandatory = $true)][string]$Container,
        [Parameter(Mandatory = $true)][string]$Database,
        [Parameter(Mandatory = $true)][string]$User,
        [Parameter(Mandatory = $true)][string[]]$Tables
    )
    $counts = [ordered]@{}
    foreach ($table in $Tables) {
        if ($table -notmatch '^[a-z_]+$') { throw "Unsafe evidence table name." }
        $raw = ((& docker exec $Container psql -v ON_ERROR_STOP=1 -U $User `
            -d $Database -tA -c "SELECT count(*) FROM ingest.$table;") -join "").Trim()
        if ($LASTEXITCODE -ne 0 -or $raw -notmatch '^[0-9]+$') {
            throw "The row count query failed for an evidence table."
        }
        $counts[$table] = [int]$raw
    }
    return $counts
}

Set-Location -LiteralPath $projectRoot
New-Item -ItemType Directory -Force -Path $hostBackupDirectory | Out-Null
try {
    docker image inspect $sourceMigrationImage $sourceFixtureImage 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Validated local migration and Fixture images are required; run Docker integration first."
    }
    docker tag $sourceMigrationImage $temporaryMigrationImage
    if ($LASTEXITCODE -ne 0) { throw "The temporary migration image tag could not be created." }
    docker tag $sourceFixtureImage $temporaryFixtureImage
    if ($LASTEXITCODE -ne 0) { throw "The temporary Fixture image tag could not be created." }
    $temporaryImagesCreated = $true

    docker compose -p $projectName --profile database up -d --wait --pull never postgres
    if ($LASTEXITCODE -ne 0) { throw "The isolated PostgreSQL container did not become healthy." }

    docker compose -p $projectName --profile database run --pull never --rm db-migrate
    if ($LASTEXITCODE -ne 0) { throw "The isolated migration failed." }
    docker compose -p $projectName --profile database run --pull never --rm --no-deps fixture-ingest
    if ($LASTEXITCODE -ne 0) { throw "The isolated Fixture ingest failed." }

    $containerId = (& docker compose -p $projectName --profile database ps -q postgres) -join ""
    if (-not $containerId) { throw "The isolated PostgreSQL container ID was not found." }

    docker exec $containerId pg_dump -U $postgresUser -d $postgresDatabase -Fc -f $backupPath
    if ($LASTEXITCODE -ne 0) { throw "The logical backup failed." }
    docker cp "${containerId}:$backupPath" $hostBackupPath
    if ($LASTEXITCODE -ne 0) { throw "The backup could not be copied to isolated host storage." }
    $backupSha256 = (Get-FileHash -LiteralPath $hostBackupPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $backupSizeBytes = (Get-Item -LiteralPath $hostBackupPath).Length
    if ($backupSha256 -notmatch '^[0-9a-f]{64}$' -or $backupSizeBytes -le 0) {
        throw "The backup checksum could not be verified."
    }

    $sourceCounts = Get-PyuriTableCounts -Container $containerId -Database $postgresDatabase `
        -User $postgresUser -Tables $evidenceTables
    $sourceSchemaVersion = ((& docker exec $containerId psql -v ON_ERROR_STOP=1 `
        -U $postgresUser -d $postgresDatabase -tA `
        -c "SELECT version_num FROM public.alembic_version;") -join "").Trim()
    if ($LASTEXITCODE -ne 0 -or $sourceSchemaVersion -notmatch '^[0-9_]+$') {
        throw "The source Schema version could not be verified."
    }

    docker exec $containerId rm -f $backupPath
    if ($LASTEXITCODE -ne 0) { throw "The original container backup could not be cleared." }
    docker cp $hostBackupPath "${containerId}:$backupPath"
    if ($LASTEXITCODE -ne 0) { throw "The host backup could not be copied back for restore." }
    $restoredBackupSha256 = ((& docker exec $containerId sha256sum $backupPath) -split '\s+')[0]
    if ($LASTEXITCODE -ne 0 -or $restoredBackupSha256 -ne $backupSha256) {
        throw "The backup checksum changed during the restore transfer."
    }

    docker exec $containerId createdb -U $postgresUser $restoreDatabase
    if ($LASTEXITCODE -ne 0) { throw "The isolated restore database could not be created." }
    docker exec $containerId pg_restore -U $postgresUser -d $restoreDatabase `
        --exit-on-error --no-owner --no-privileges $backupPath
    if ($LASTEXITCODE -ne 0) { throw "The isolated restore failed." }

    $restoredCounts = Get-PyuriTableCounts -Container $containerId -Database $restoreDatabase `
        -User $postgresUser -Tables $evidenceTables
    $restoredSchemaVersion = ((& docker exec $containerId psql -v ON_ERROR_STOP=1 `
        -U $postgresUser -d $restoreDatabase -tA `
        -c "SELECT version_num FROM public.alembic_version;") -join "").Trim()
    if ($LASTEXITCODE -ne 0) { throw "The restored Schema version could not be read." }

    $countsMatch = $true
    foreach ($table in $evidenceTables) {
        if ($sourceCounts[$table] -ne $restoredCounts[$table]) { $countsMatch = $false }
    }
    [int]$sourceRowCount = ($sourceCounts.Values | Measure-Object -Sum).Sum
    [int]$restoredRowCount = ($restoredCounts.Values | Measure-Object -Sum).Sum

    $passed = (
        $countsMatch -and $sourceRowCount -eq $restoredRowCount -and
        $sourceSchemaVersion -eq $restoredSchemaVersion -and
        $sourceSchemaVersion -match '^[0-9_]+$'
    )
    if (-not $passed) { throw "Restored evidence does not match the isolated source." }

    $report = [ordered]@{
        status = "passed_offline_restore_drill"
        isolated_restore = $true
        backup_sha256_verified = $true
        backup_sha256 = $backupSha256
        backup_size_bytes = $backupSizeBytes
        backup_format = "postgresql_custom"
        schema_version_verified = $true
        schema_version = $sourceSchemaVersion
        source_row_count = $sourceRowCount
        restored_row_count = $restoredRowCount
        source_table_counts = $sourceCounts
        restored_table_counts = $restoredCounts
        table_counts_match = $countsMatch
        compose_project = $projectName
        restore_database = $restoreDatabase
        canonical_volume_untouched = $true
        fixture_manifest_sha256 = (Get-FileHash -LiteralPath `
            (Join-Path $projectRoot "fixtures\manifest.json") -Algorithm SHA256).Hash.ToLowerInvariant()
        generated_at = [DateTimeOffset]::UtcNow.ToString("o")
        runtime_secret_generated = $true
        secret_persisted = $false
        external_network_used = $false
        real_source_collection_authorized = $false
        external_publication_approved = $false
    }
    $report | ConvertTo-Json | Set-Content -LiteralPath $reportPath -Encoding UTF8
    Write-Host "Phase 6 isolated backup/restore drill passed."
    Write-Host "Report: $reportPath"
} finally {
    if ($containerId) {
        & docker exec $containerId rm -f $backupPath 2>&1 | Out-Null
    }
    & docker compose -p $projectName --profile database down -v --remove-orphans 2>&1 | Out-Null
    if ($temporaryImagesCreated) {
        & docker image rm $temporaryMigrationImage $temporaryFixtureImage 2>&1 | Out-Null
    }
    if (Test-Path -LiteralPath $hostBackupPath -PathType Leaf) {
        Remove-Item -LiteralPath $hostBackupPath -Force
    }
    if (Test-Path -LiteralPath $hostBackupDirectory -PathType Container) {
        Remove-Item -LiteralPath $hostBackupDirectory -Force
    }
    $env:PYURI_POSTGRES_PASSWORD = $previousPassword
}

$global:LASTEXITCODE = 0
