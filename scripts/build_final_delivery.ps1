param(
    [string]$Version = "1.2.0",
    [string]$DeliveryName = "惠民智导可信政策智能平台",
    [string]$VideoPath = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$deliveryRoot = Join-Path $projectRoot "最终交付"
$outputRoot = Join-Path $deliveryRoot $DeliveryName

if (Test-Path -LiteralPath $outputRoot) {
    throw "目标交付目录已存在，请更换 DeliveryName，避免覆盖已有成果：$outputRoot"
}

$docxSource = Join-Path $projectRoot "deliverables\惠民智导_作品方案.docx"
$pdfSource = Join-Path $projectRoot "deliverables\惠民智导_作品方案.pdf"
$pptxSource = Join-Path $projectRoot "deliverables\pptx\惠民智导_答辩演示.pptx"
$pptPdfSource = Join-Path $projectRoot "deliverables\pptx\惠民智导_答辩演示.pdf"
$evidenceSource = Join-Path $projectRoot "deliverables\惠民智导_佐证材料.pdf"
$guideSource = Join-Path $projectRoot "deliverables\惠民智导_软件使用说明.pdf"
if ([string]::IsNullOrWhiteSpace($VideoPath)) {
    $VideoPath = Join-Path $deliveryRoot "惠民智导可信政策智能平台\惠民智导_演示视频.mp4"
}
$requiredArtifacts = @($docxSource, $pdfSource, $pptxSource, $pptPdfSource, $evidenceSource, $guideSource, $VideoPath)
foreach ($artifact in $requiredArtifacts) {
    if (-not (Test-Path -LiteralPath $artifact -PathType Leaf)) {
        throw "缺少正式交付文件：$artifact"
    }
}

New-Item -ItemType Directory -Path $outputRoot -Force | Out-Null
Copy-Item -LiteralPath $docxSource -Destination (Join-Path $outputRoot "01_惠民智导_作品方案.docx")
Copy-Item -LiteralPath $pdfSource -Destination (Join-Path $outputRoot "01_惠民智导_作品方案.pdf")
Copy-Item -LiteralPath $pptxSource -Destination (Join-Path $outputRoot "02_惠民智导_答辩演示.pptx")
Copy-Item -LiteralPath $pptPdfSource -Destination (Join-Path $outputRoot "02_惠民智导_答辩演示.pdf")
Copy-Item -LiteralPath $VideoPath -Destination (Join-Path $outputRoot "03_惠民智导_演示视频.mp4")
Copy-Item -LiteralPath $evidenceSource -Destination (Join-Path $outputRoot "05_惠民智导_佐证材料.pdf")
Copy-Item -LiteralPath $guideSource -Destination (Join-Path $outputRoot "06_惠民智导_软件使用说明.pdf")

$introduction = @"
作品名称：惠民智导可信政策智能平台

作品简介：
面向社会救助政策专业、分散且持续更新造成的群众理解难、材料准备难和基层重复解释问题，本作品构建本地运行的可信政策智能平台。系统采用受约束神经符号架构：大模型负责意图与事实候选抽取，版本化规则和三值逻辑负责确定性导办，混合检索提供逐字政策证据，Policy2Rule候选编译、影响分析和人工发布门约束政策更新风险。平台提供居民导办、材料预检、工作人员复核、治理工作台与场景验证功能；模型不可用时可安全降级。系统输出仅为导办建议，不替代行政审批，现有指标明确区分内部合成测试、专家构造案例与外部验证边界。
"@
[System.IO.File]::WriteAllText((Join-Path $outputRoot "作品名称及简介.txt"), $introduction, [System.Text.UTF8Encoding]::new($true))

$stageRoot = Join-Path $projectRoot ("tmp\final-software-stage-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $stageRoot -Force | Out-Null

$rootFiles = @(
    ".dockerignore", ".editorconfig", ".env.example",
    "compose.yaml", "Dockerfile", "pyproject.toml",
    "requirements.lock", "requirements.txt",
    "README.md", "REPRODUCIBILITY.md", "SECURITY.md", "MODEL_LICENSES.md",
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
    "pilot_observations.csv", "pilot_participants.csv",
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
    project = "惠民智导可信政策智能平台"
    version = $Version
    team = [ordered]@{
        name = "策马奔腾"
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

$softwareZip = Join-Path $outputRoot "04_惠民智导_软件运行包.zip"
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
    project = "惠民智导可信政策智能平台"
    version = $Version
    team = "策马奔腾"
    files = @($deliveryFiles)
}
$deliveryManifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $outputRoot "07_交付校验清单.json") -Encoding utf8

[pscustomobject]@{
    Output = $outputRoot
    FileCount = (Get-ChildItem -LiteralPath $outputRoot -File).Count
    SoftwareFiles = $payloadEntries.Count
    SoftwareZipSHA256 = (Get-FileHash -LiteralPath $softwareZip -Algorithm SHA256).Hash.ToLowerInvariant()
} | Format-List
