param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8000,

    [ValidateSet('auto', 'deterministic', 'ollama', 'hybrid')]
    [string]$AIMode = 'auto',

    [switch]$DemoMode
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$StorageDirectory = Join-Path $ProjectRoot 'storage'
$PidFile = Join-Path $StorageDirectory 'server.pid'
$PortFile = Join-Path $StorageDirectory 'server.port'
$OutputLog = Join-Path $StorageDirectory 'server.out.log'
$ErrorLog = Join-Path $StorageDirectory 'server.err.log'

if ($DemoMode) {
    $env:DEMO_MODE = 'true'
}
elseif ([string]::IsNullOrWhiteSpace($env:DEMO_MODE)) {
    $env:DEMO_MODE = 'false'
}
if ($env:DEMO_MODE -ne 'true' -and [string]::IsNullOrWhiteSpace($env:ADMIN_API_TOKEN)) {
    throw '非演示模式必须设置ADMIN_API_TOKEN；现场展示请显式使用 .\start.ps1 -DemoMode'
}

# 未显式传入端口时沿用上次记录，避免曾用8010启动后再次执行脚本又在8000启动一份。
if (-not $PSBoundParameters.ContainsKey('Port') -and (Test-Path -LiteralPath $PortFile)) {
    $RecordedPort = 0
    $PortText = (Get-Content -LiteralPath $PortFile -Raw).Trim()
    if ([int]::TryParse($PortText, [ref]$RecordedPort) -and $RecordedPort -ge 1 -and $RecordedPort -le 65535) {
        $Port = $RecordedPort
    }
}
$HealthUri = "http://127.0.0.1:$Port/api/health"

# auto 会在本机同时存在对话与嵌入模型时启用完整混合管线；否则使用确定性安全底座。
# 用户仍可用 -AIMode deterministic 强制无模型演示，或显式选择 ollama/hybrid。
$ResolvedAIMode = $AIMode
if ($AIMode -eq 'auto') {
    $ResolvedAIMode = 'deterministic'
    try {
        $Tags = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -Method Get -TimeoutSec 2
        $ModelNames = @($Tags.models | ForEach-Object { $_.name })
        if (($ModelNames -contains 'qwen3:4b-instruct') -and ($ModelNames -contains 'qwen3-embedding:0.6b')) {
            $ResolvedAIMode = 'hybrid'
        }
        elseif ($ModelNames -contains 'qwen3:4b-instruct') {
            $ResolvedAIMode = 'ollama'
        }
    }
    catch {
        # Ollama 不可达时仍可完整运行确定性导办，不把启动失败转嫁给用户。
    }
}
$env:AI_MODE = $ResolvedAIMode
$env:OLLAMA_MODEL = 'qwen3:4b-instruct'
$env:OLLAMA_EMBED_MODEL = 'qwen3-embedding:0.6b'
$env:OLLAMA_TIMEOUT_SECONDS = '120'

function Test-AppHealth {
    try {
        $Response = Invoke-RestMethod -Uri $HealthUri -Method Get -TimeoutSec 1
        return ($Response.status -eq 'ok' -and $Response.service_id -eq 'huimin-guide')
    }
    catch {
        return $false
    }
}

function Test-LocalPort {
    $Client = [System.Net.Sockets.TcpClient]::new()
    try {
        $ConnectTask = $Client.ConnectAsync('127.0.0.1', $Port)
        if (-not $ConnectTask.Wait(600)) {
            return $false
        }
        return $Client.Connected
    }
    catch {
        return $false
    }
    finally {
        $Client.Dispose()
    }
}

function Test-ManagedProcess {
    param([int]$ProcessId)

    try {
        $Process = Get-Process -Id $ProcessId -ErrorAction Stop
        if ([string]::IsNullOrWhiteSpace($Process.Path)) {
            return $false
        }
        $ActualPath = [System.IO.Path]::GetFullPath($Process.Path)
        $ExpectedPath = [System.IO.Path]::GetFullPath($Python)
        return $ActualPath.Equals($ExpectedPath, [System.StringComparison]::OrdinalIgnoreCase)
    }
    catch {
        return $false
    }
}

if (-not (Test-Path -LiteralPath $Python)) {
    throw '尚未初始化环境。请先运行 .\setup.ps1'
}

New-Item -ItemType Directory -Path $StorageDirectory -Force | Out-Null

if (Test-AppHealth) {
    Write-Host "惠民智导可信政策智能平台已在运行，无需重复启动。" -ForegroundColor Green
    Write-Host "访问地址： http://127.0.0.1:$Port"
    Write-Host "停止服务： .\stop.ps1"
    exit 0
}

if (Test-Path -LiteralPath $PidFile) {
    $RecordedProcessId = 0
    $PidText = (Get-Content -LiteralPath $PidFile -Raw).Trim()
    if ([int]::TryParse($PidText, [ref]$RecordedProcessId) -and (Test-ManagedProcess -ProcessId $RecordedProcessId)) {
        throw "检测到本项目服务进程 PID $RecordedProcessId 仍在运行，但健康检查未通过。请先运行 .\stop.ps1，再查看 storage\server.err.log。"
    }
    [System.IO.File]::Delete($PidFile)
    [System.IO.File]::Delete($PortFile)
}

if (Test-LocalPort) {
    throw "端口 $Port 已被其他程序占用。可关闭占用程序，或使用 .\start.ps1 -Port 8010 启动本项目。"
}

[System.IO.File]::WriteAllText($OutputLog, '', [System.Text.UTF8Encoding]::new($false))
[System.IO.File]::WriteAllText($ErrorLog, '', [System.Text.UTF8Encoding]::new($false))

$Arguments = @(
    '-m', 'uvicorn', 'app.main:app',
    '--host', '127.0.0.1',
    '--port', $Port.ToString()
)

$ServerProcess = Start-Process `
    -FilePath $Python `
    -ArgumentList $Arguments `
    -WorkingDirectory $ProjectRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $OutputLog `
    -RedirectStandardError $ErrorLog `
    -PassThru

[System.IO.File]::WriteAllText($PidFile, $ServerProcess.Id.ToString(), [System.Text.UTF8Encoding]::new($false))
[System.IO.File]::WriteAllText($PortFile, $Port.ToString(), [System.Text.UTF8Encoding]::new($false))

for ($Attempt = 0; $Attempt -lt 60; $Attempt++) {
    if (Test-AppHealth) {
        Write-Host "惠民智导可信政策智能平台启动成功。" -ForegroundColor Green
        Write-Host "访问地址： http://127.0.0.1:$Port"
        Write-Host "进程 PID： $($ServerProcess.Id)"
        Write-Host "AI 模式： $ResolvedAIMode"
        Write-Host "运行模式： $(if ($env:DEMO_MODE -eq 'true') { '显式演示模式' } else { '鉴权模式' })"
        Write-Host "查看状态： .\status.ps1"
        Write-Host "查看日志： .\logs.ps1"
        Write-Host "停止服务： .\stop.ps1"
        exit 0
    }

    if ($ServerProcess.HasExited) {
        break
    }
    Start-Sleep -Milliseconds 250
    $ServerProcess.Refresh()
}

if (-not $ServerProcess.HasExited -and (Test-ManagedProcess -ProcessId $ServerProcess.Id)) {
    Stop-Process -Id $ServerProcess.Id -Force -ErrorAction SilentlyContinue
}
[System.IO.File]::Delete($PidFile)
[System.IO.File]::Delete($PortFile)

$RecentErrors = ''
if (Test-Path -LiteralPath $ErrorLog) {
    $RecentErrors = (Get-Content -LiteralPath $ErrorLog -Tail 30) -join [Environment]::NewLine
}
throw "服务未能通过启动健康检查。请查看 storage\server.err.log。`n$RecentErrors"

