[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$DumpPath,
    [string]$ManifestPath = "",
    [switch]$ConfirmEmptyTarget
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$dump = (Resolve-Path -LiteralPath $DumpPath).Path
if (-not $ManifestPath) { $ManifestPath = Join-Path (Split-Path -Parent $dump) "manifest.json" }
$manifestFile = (Resolve-Path -LiteralPath $ManifestPath).Path
if (-not $ConfirmEmptyTarget) {
    throw "Restore is blocked until -ConfirmEmptyTarget is supplied. The target must be a new empty database."
}
if (-not $env:PYURI_CLOUD_DATABASE_URL) {
    throw "Set PYURI_CLOUD_DATABASE_URL in the current process; do not place it in the migration bundle."
}
$pgRestore = Get-Command pg_restore -ErrorAction SilentlyContinue
$psql = Get-Command psql -ErrorAction SilentlyContinue
if (-not $pgRestore -or -not $psql) {
    throw "PostgreSQL 17 client tools pg_restore and psql are required on this machine."
}

$manifest = Get-Content -Raw -LiteralPath $manifestFile | ConvertFrom-Json
if ($manifest.source_format -ne "pyuri_jjwxc_cloud_migration_bundle" -or
    $manifest.schema_version -ne 1) {
    throw "Migration manifest format is not supported."
}
$actualSha256 = (Get-FileHash -LiteralPath $dump -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualSha256 -ne $manifest.database_dump_sha256) {
    throw "Database dump SHA-256 does not match the manifest."
}

$previousDatabase = $env:PGDATABASE
$env:PGDATABASE = $env:PYURI_CLOUD_DATABASE_URL
try {
    $tableCount = ((& $psql.Source -v ON_ERROR_STOP=1 -tA `
        -c "SELECT count(*) FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema');") `
        -join "").Trim()
    if ($LASTEXITCODE -ne 0 -or $tableCount -notmatch '^[0-9]+$') {
        throw "The cloud database could not be inspected."
    }
    if ([long]$tableCount -ne 0) {
        throw "The cloud target is not empty; restore refused without deleting or overwriting anything."
    }
    & $pgRestore.Source --exit-on-error --no-owner --no-privileges $dump
    if ($LASTEXITCODE -ne 0) { throw "Cloud PostgreSQL restore failed." }
    $restoredVersion = ((& $psql.Source -v ON_ERROR_STOP=1 -tA `
        -c "SELECT version_num FROM public.alembic_version;") -join "").Trim()
    if ($restoredVersion -ne $manifest.alembic_version) {
        throw "Cloud Alembic version does not match the migration manifest."
    }
    $verifiedCounts = [ordered]@{}
    foreach ($property in $manifest.strict_table_counts.PSObject.Properties) {
        $table = $property.Name
        if ($table -notmatch '^[a-z_]+$') { throw "Unsafe table name in migration manifest." }
        $count = ((& $psql.Source -v ON_ERROR_STOP=1 -tA `
            -c "SELECT count(*) FROM ingest.$table;") -join "").Trim()
        if ($LASTEXITCODE -ne 0 -or $count -notmatch '^[0-9]+$' -or
            [long]$count -ne [long]$property.Value) {
            throw "Cloud row-count verification failed for ingest.$table."
        }
        $verifiedCounts[$table] = [long]$count
    }
    $report = [ordered]@{
        status = "passed"
        restored_at = [DateTimeOffset]::UtcNow.ToString("o")
        database_dump_sha256 = $actualSha256
        alembic_version = $restoredVersion
        verified_table_counts = $verifiedCounts
        credentials_persisted = $false
    }
    $report | ConvertTo-Json -Depth 7 | Set-Content `
        -LiteralPath (Join-Path (Split-Path -Parent $dump) "cloud-restore-report.json") `
        -Encoding utf8
    Write-Host "Cloud database restore and row-count verification passed."
} finally {
    $env:PGDATABASE = $previousDatabase
}

$global:LASTEXITCODE = 0
