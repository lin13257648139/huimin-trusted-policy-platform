param(
    [string]$Version = "0.7.1",
    [string]$DeliveryName = "惠民智导_最终交付_20261003"
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$deliveryRoot = Join-Path $projectRoot "最终交付"
$outputRoot = Join-Path $deliveryRoot $DeliveryName

if (Test-Path -LiteralPath $outputRoot) {
    throw "目标交付目录已存在，请更换 DeliveryName，避免覆盖已有成果：$outputRoot"
}

$docxSource = Join-Path $projectRoot "deliverables\惠民智导_项目说明书.docx"
$pdfSource = Join-Path $projectRoot "deliverables\惠民智导_项目说明书.pdf"
$pptxSource = Join-Path $projectRoot "deliverables\pptx\惠民智导_答辩演示.pptx"
$pptPdfSource = Join-Path $projectRoot "deliverables\pptx\惠民智导_答辩演示.pdf"
$requiredArtifacts = @($docxSource, $pdfSource, $pptxSource, $pptPdfSource)
foreach ($artifact in $requiredArtifacts) {
    if (-not (Test-Path -LiteralPath $artifact -PathType Leaf)) {
        throw "缺少正式交付文件：$artifact"
    }
}

New-Item -ItemType Directory -Path $outputRoot -Force | Out-Null
Copy-Item -LiteralPath $docxSource -Destination (Join-Path $outputRoot "01_惠民智导_项目说明书.docx")
Copy-Item -LiteralPath $pdfSource -Destination (Join-Path $outputRoot "01_惠民智导_项目说明书.pdf")
Copy-Item -LiteralPath $pptxSource -Destination (Join-Path $outputRoot "02_惠民智导_答辩演示.pptx")
Copy-Item -LiteralPath $pptPdfSource -Destination (Join-Path $outputRoot "02_惠民智导_答辩演示.pdf")

$stageRoot = Join-Path $projectRoot ("tmp\final-software-stage-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $stageRoot -Force | Out-Null

$rootFiles = @(
    ".dockerignore", ".editorconfig", ".env.example",
    "compose.yaml", "Dockerfile", "pyproject.toml",
    "requirements.lock", "requirements.txt",
    "setup.ps1", "start.ps1", "stop.ps1", "status.ps1", "logs.ps1",
    "start-ai-runtime.ps1", "reproduce_phase12.ps1"
)
foreach ($relative in $rootFiles) {
    $source = Join-Path $projectRoot $relative
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        throw "运行包缺少必需文件：$relative"
    }
    Copy-Item -LiteralPath $source -Destination (Join-Path $stageRoot $relative)
}

$includedRoots = @("app", "data", "demo_assets", "scripts", "tests", "storage", "政策证据包")
$excludedNames = @(
    "expert_review_A.csv", "expert_review_B.csv", "expert_review_C.csv",
    "pilot_observations.csv", "pilot_participants.csv", "expert_gold_master.csv",
    "B002逐例误差分析.xlsx", "build_release.ps1", "build_final_delivery.ps1"
)
$excludedExtensions = @(".md", ".txt", ".pyc", ".pyo", ".log", ".db", ".pid", ".port")

foreach ($rootName in $includedRoots) {
    $sourceRoot = Join-Path $projectRoot $rootName
    if (-not (Test-Path -LiteralPath $sourceRoot -PathType Container)) {
        throw "运行包缺少必需目录：$rootName"
    }
    Get-ChildItem -LiteralPath $sourceRoot -Recurse -File -Force | Where-Object {
        ($excludedNames -notcontains $_.Name) -and
        ($excludedExtensions -notcontains $_.Extension.ToLowerInvariant()) -and
        ($_.FullName -notmatch "[\\/]__pycache__[\\/]")
    } | ForEach-Object {
        $relative = $_.FullName.Substring($projectRoot.Length).TrimStart("\")
        $destination = Join-Path $stageRoot $relative
        New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
        Copy-Item -LiteralPath $_.FullName -Destination $destination
    }
}

$payloadEntries = Get-ChildItem -LiteralPath $stageRoot -Recurse -File | Sort-Object FullName | ForEach-Object {
    $relative = $_.FullName.Substring($stageRoot.Length).TrimStart("\")
    [ordered]@{
        path = $relative.Replace("\", "/")
        bytes = $_.Length
        sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}

$manifest = [ordered]@{
    schema_version = "huimin-final-package.v1"
    project = "惠民智导——可信政策智能软件平台"
    version = $Version
    team = [ordered]@{
        name = "策马奔腾"
        captain = "林琪东"
        member = "罗晓蓝"
        school = "广州软件学院"
    }
    created_at = (Get-Date).ToString("o")
    privacy = [ordered]@{
        raw_expert_reviews_included = $false
        human_pilot_records_included = $false
        runtime_database_included = $false
        model_weights_included = $false
    }
    payload_file_count = $payloadEntries.Count
    files = @($payloadEntries)
}
$manifest | ConvertTo-Json -Depth 7 | Set-Content -LiteralPath (Join-Path $stageRoot "MANIFEST.json") -Encoding utf8

$softwareZip = Join-Path $outputRoot "03_惠民智导_软件运行包.zip"
Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::CreateFromDirectory(
    $stageRoot,
    $softwareZip,
    [System.IO.Compression.CompressionLevel]::Optimal,
    $false
)

$deliveryFiles = Get-ChildItem -LiteralPath $outputRoot -File | Sort-Object Name | ForEach-Object {
    [ordered]@{
        file = $_.Name
        bytes = $_.Length
        sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}
$deliveryManifest = [ordered]@{
    schema_version = "huimin-delivery.v1"
    project = "惠民智导——可信政策智能软件平台"
    version = $Version
    team = "策马奔腾"
    school = "广州软件学院"
    files = @($deliveryFiles)
}
$deliveryManifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $outputRoot "04_交付校验清单.json") -Encoding utf8

[pscustomobject]@{
    Output = $outputRoot
    FileCount = (Get-ChildItem -LiteralPath $outputRoot -File).Count
    SoftwareFiles = $payloadEntries.Count
    SoftwareZipSHA256 = (Get-FileHash -LiteralPath $softwareZip -Algorithm SHA256).Hash.ToLowerInvariant()
} | Format-List
