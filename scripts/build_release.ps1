param(
    [string]$Version = "1.2.0",
    [switch]$CompetitionRelease
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$releaseRoot = Join-Path $projectRoot "release"
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$releaseName = "惠民智导可信政策智能平台-v$Version-$stamp"
$stageRoot = Join-Path $releaseRoot $releaseName
$zipPath = Join-Path $releaseRoot "$releaseName.zip"

if ($CompetitionRelease) {
    $dirty = & git -C $projectRoot status --porcelain
    if ($LASTEXITCODE -ne 0) {
        throw '正式竞赛发布必须位于可用的Git工作区'
    }
    if ($dirty) {
        throw '正式竞赛发布要求干净Git工作区；请先审查并提交当前改动'
    }
    & (Join-Path $PSScriptRoot 'run_quality_gates.ps1') -RequireNativeSemgrep
    if ($LASTEXITCODE -ne 0) {
        throw '正式竞赛发布质量门未通过'
    }
    $python = Join-Path $projectRoot '.venv\Scripts\python.exe'
    & $python (Join-Path $PSScriptRoot 'verify_live_ai.py')
    if ($LASTEXITCODE -ne 0) {
        throw '正式竞赛发布要求真实对话模型和向量模型冒烟证据'
    }
}

New-Item -ItemType Directory -Force -Path $stageRoot | Out-Null

$excludedDirectoryNames = @(
    ".git", ".venv", ".pytest_cache", ".mypy_cache", "__pycache__",
    "tmp", "logs", "release", "deliverables", "最终交付", "用户试点", "真人试点填写示例_U00_虚构"
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
    project = "惠民智导可信政策智能平台"
    version = $Version
    competition_release_gate = [bool]$CompetitionRelease
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
        competition_deliverables = $true
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
