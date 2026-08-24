[CmdletBinding()]
param([string]$OutputRoot = "")

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location -LiteralPath $projectRoot
& (Join-Path $PSScriptRoot "test-railway-deployment.ps1")
if ($LASTEXITCODE -ne 0) { throw "Railway preflight must pass before packaging source." }

if (-not $OutputRoot) { $OutputRoot = Join-Path $projectRoot "var\releases" }
$outputRootAbsolute = [System.IO.Path]::GetFullPath($OutputRoot, $projectRoot)
New-Item -ItemType Directory -Force -Path $outputRootAbsolute | Out-Null
$token = [guid]::NewGuid().ToString("N").Substring(0, 12)
$timestamp = [DateTimeOffset]::UtcNow.ToString("yyyyMMddTHHmmssZ")
$archivePath = Join-Path $outputRootAbsolute "jjwxc-source-release-$timestamp-$token.zip"
$checksumPath = "$archivePath.sha256"
if ((Test-Path -LiteralPath $archivePath) -or (Test-Path -LiteralPath $checksumPath)) {
    throw "Source release target already exists."
}

$listedFiles = @(& git -c core.quotepath=false ls-files --cached --others --exclude-standard)
if ($LASTEXITCODE -ne 0 -or -not $listedFiles.Count) { throw "Git file inventory is unavailable." }

function Test-ExcludedPath {
    param([Parameter(Mandatory = $true)][string]$RelativePath)
    $path = $RelativePath.Replace('\', '/')
    if ($path.StartsWith("/") -or $path -match '(^|/)\.\.(/|$)') { return $true }
    if ($path -match '(^|/)(\.git|\.venv|node_modules|\.next|__pycache__|var|\.tmp)(/|$)') { return $true }
    if ($path -match '(?i)\.(dump|pem|key|p12|pfx|log)$') { return $true }
    if ($path -match '(^|/)\.env($|\.)' -and $path -notmatch '(?i)\.example$') { return $true }
    return $false
}

$files = [System.Collections.Generic.List[object]]::new()
foreach ($relativeRaw in $listedFiles) {
    $relative = [string]$relativeRaw
    if (-not $relative -or (Test-ExcludedPath $relative)) { continue }
    $absolute = [System.IO.Path]::GetFullPath((Join-Path $projectRoot $relative))
    if (-not $absolute.StartsWith($projectRoot + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "A source file resolved outside the project root."
    }
    if (-not (Test-Path -LiteralPath $absolute -PathType Leaf)) { continue }
    $files.Add([ordered]@{
        path = $relative.Replace('\', '/')
        absolute = $absolute
        size_bytes = (Get-Item -LiteralPath $absolute).Length
        sha256 = (Get-FileHash -LiteralPath $absolute -Algorithm SHA256).Hash.ToLowerInvariant()
    })
}
if (-not $files.Count) { throw "No safe source files were selected." }

$secretValues = [ordered]@{}
$localEnvironment = Join-Path $projectRoot ".env"
if (Test-Path -LiteralPath $localEnvironment -PathType Leaf) {
    foreach ($line in Get-Content -LiteralPath $localEnvironment) {
        if ($line -match '^([A-Z][A-Z0-9_]*)=(.*)$') {
            $name = $matches[1]
            $value = $matches[2].Trim().Trim('"').Trim("'")
            if ($name -match '(PASSWORD|TOKEN|SECRET|API_KEY|DATABASE_URL|COOKIE|SESSION)' -and
                $value.Length -ge 12 -and $value -ne "change-me-local-only" -and
                $value -notmatch '^(GENERATE_|USER:)') {
                $secretValues[$name] = $value
            }
        }
    }
}
$textExtensions = @(".cjs", ".cmd", ".css", ".html", ".js", ".json", ".md", ".mjs", ".ps1", ".py", ".toml", ".ts", ".tsx", ".txt", ".yaml", ".yml")
$violations = [System.Collections.Generic.List[string]]::new()
foreach ($file in $files) {
    $extension = [System.IO.Path]::GetExtension([string]$file.path).ToLowerInvariant()
    if ($extension -notin $textExtensions) { continue }
    $content = Get-Content -Raw -LiteralPath ([string]$file.absolute)
    if ($content -match '-----BEGIN [A-Z ]*PRIVATE KEY-----') {
        $violations.Add("Private key marker found in $($file.path)")
    }
    foreach ($entry in $secretValues.GetEnumerator()) {
        if ($content.Contains([string]$entry.Value, [System.StringComparison]::Ordinal)) {
            $violations.Add("Local environment value for $($entry.Key) found in $($file.path)")
        }
    }
}
if ($violations.Count) { throw ($violations -join [Environment]::NewLine) }

$gitCommit = ((& git rev-parse HEAD) -join "").Trim()
$gitBranch = ((& git branch --show-current) -join "").Trim()
$dirty = [bool](((& git status --porcelain) -join "").Trim())
$manifest = [ordered]@{
    source_format = "jjwxc_yuri_source_release"
    schema_version = 1
    generated_at = [DateTimeOffset]::UtcNow.ToString("o")
    git_commit = $gitCommit
    git_branch = $gitBranch
    working_tree_included = $true
    working_tree_dirty = $dirty
    file_count = $files.Count
    excluded_runtime_data = $true
    excluded_environment_secrets = $true
    excluded_git_history = $true
    files = @($files | ForEach-Object {
        [ordered]@{ path = $_.path; size_bytes = $_.size_bytes; sha256 = $_.sha256 }
    })
}
$manifestJson = $manifest | ConvertTo-Json -Depth 8

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$fileStream = [System.IO.File]::Open($archivePath, [System.IO.FileMode]::CreateNew)
try {
    $archive = [System.IO.Compression.ZipArchive]::new(
        $fileStream,
        [System.IO.Compression.ZipArchiveMode]::Create,
        $false
    )
    try {
        foreach ($file in $files) {
            [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
                $archive,
                [string]$file.absolute,
                [string]$file.path,
                [System.IO.Compression.CompressionLevel]::Optimal
            ) | Out-Null
        }
        $entry = $archive.CreateEntry("release-manifest.json", [System.IO.Compression.CompressionLevel]::Optimal)
        $writer = [System.IO.StreamWriter]::new($entry.Open(), [System.Text.UTF8Encoding]::new($false))
        try { $writer.Write($manifestJson) } finally { $writer.Dispose() }
    } finally { $archive.Dispose() }
} finally { $fileStream.Dispose() }

$archiveSha256 = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
"$archiveSha256  $([System.IO.Path]::GetFileName($archivePath))" | `
    Set-Content -LiteralPath $checksumPath -Encoding ascii
$report = [ordered]@{
    status = "passed"
    generated_at = [DateTimeOffset]::UtcNow.ToString("o")
    archive_path = $archivePath
    archive_sha256 = $archiveSha256
    archive_size_bytes = (Get-Item -LiteralPath $archivePath).Length
    source_file_count = $files.Count
    working_tree_dirty = $dirty
    railway_preflight = "passed"
    secret_scan = "passed"
}
$reportPath = Join-Path $projectRoot "var\reports\source_release_latest.json"
$report | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $reportPath -Encoding utf8
Write-Host "Cloud source release created."
Write-Host "Archive: $archivePath"
Write-Host "SHA-256: $archiveSha256"
$global:LASTEXITCODE = 0
