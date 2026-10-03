param(
    [string]$Version = "0.7.1"
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$releaseRoot = Join-Path $projectRoot "release"
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$releaseName = "惠民智导-v$Version-$stamp"
$stageRoot = Join-Path $releaseRoot $releaseName
$zipPath = Join-Path $releaseRoot "$releaseName.zip"

New-Item -ItemType Directory -Force -Path $stageRoot | Out-Null

$excludedDirectoryNames = @(
    ".git", ".venv", ".pytest_cache", ".mypy_cache", "__pycache__",
    "tmp", "logs", "release", "用户试点", "真人试点填写示例_U00_虚构"
)
$excludedRelativePrefixes = @(
    ".chart-data-",
    "deliverables\_qa_",
    "deliverables\_ppt_build"
)
$excludedFileNames = @(
    "app.db", "app.db-shm", "app.db-wal",
    "expert_review_A.csv", "expert_review_B.csv", "expert_review_C.csv",
    "pilot_observations.csv", "pilot_participants.csv",
    "惠民智导_答辩材料_v1.pdf", "惠民智导_答辩材料_v1.pptx"
)
$excludedExtensions = @(
    ".pyc", ".pyo", ".log",
    ".gguf", ".safetensors", ".onnx", ".pt", ".pth"
)

$sourceFiles = Get-ChildItem -LiteralPath $projectRoot -Recurse -File -Force | Where-Object {
    $full = $_.FullName
    $relative = $full.Substring($projectRoot.Length).TrimStart("\")
    $segments = $relative -split "\\"
    $hasExcludedDir = $false
    foreach ($segment in $segments[0..([Math]::Max(0, $segments.Count - 2))]) {
        if ($excludedDirectoryNames -contains $segment) {
            $hasExcludedDir = $true
            break
        }
    }
    $hasExcludedPrefix = $false
    foreach ($prefix in $excludedRelativePrefixes) {
        if ($relative.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            $hasExcludedPrefix = $true
            break
        }
    }
    (-not $hasExcludedDir) -and
    (-not $hasExcludedPrefix) -and
    ($excludedFileNames -notcontains $_.Name) -and
    ($excludedExtensions -notcontains $_.Extension.ToLowerInvariant())
}

foreach ($file in $sourceFiles) {
    $relative = $file.FullName.Substring($projectRoot.Length).TrimStart("\")
    $destination = Join-Path $stageRoot $relative
    $destinationDirectory = Split-Path -Parent $destination
    New-Item -ItemType Directory -Force -Path $destinationDirectory | Out-Null
    Copy-Item -LiteralPath $file.FullName -Destination $destination
}

$manifestEntries = Get-ChildItem -LiteralPath $stageRoot -Recurse -File | Sort-Object FullName | ForEach-Object {
    $relative = $_.FullName.Substring($stageRoot.Length).TrimStart("\")
    $hash = Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256
    [pscustomobject]@{
        path = $relative.Replace("\", "/")
        bytes = $_.Length
        sha256 = $hash.Hash.ToLowerInvariant()
    }
}

$manifest = [ordered]@{
    schema_version = "release-manifest.v1"
    project = "惠民智导——可信政策智能软件平台"
    version = $Version
    created_at = (Get-Date).ToString("o")
    payload_file_count = $manifestEntries.Count
    exclusions = [ordered]@{
        runtime_database = $true
        logs_and_temp = $true
        virtual_environment = $true
        raw_expert_files = $true
        human_pilot_files = $true
        model_weights = $true
        qa_intermediates = $true
    }
    files = @($manifestEntries)
}
$manifestPath = Join-Path $stageRoot "RELEASE_MANIFEST.json"
$manifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $manifestPath -Encoding utf8

Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::CreateFromDirectory(
    $stageRoot,
    $zipPath,
    [System.IO.Compression.CompressionLevel]::Optimal,
    $false
)
$zipHash = Get-FileHash -LiteralPath $zipPath -Algorithm SHA256
$zipHashPath = "$zipPath.sha256.txt"
"$($zipHash.Hash.ToLowerInvariant())  $([System.IO.Path]::GetFileName($zipPath))" | Set-Content -LiteralPath $zipHashPath -Encoding ascii

[pscustomobject]@{
    Stage = $stageRoot
    Zip = $zipPath
    Bytes = (Get-Item -LiteralPath $zipPath).Length
    SHA256 = $zipHash.Hash.ToLowerInvariant()
    PayloadFiles = $manifestEntries.Count
} | Format-List
