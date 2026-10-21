param(
    [ValidateSet('auto', 'cuda_v12', 'cuda_v13', 'cpu')]
    [string]$Backend = 'auto',

    [switch]$ForceRestart,

    # The local Windows experience shows Ollama's system-tray icon by default.
    # CI, kiosk, and server environments can opt out with -Headless.
    [switch]$Headless
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$InstallRoot = Join-Path $env:LOCALAPPDATA 'Programs\Ollama'
$Ollama = Join-Path $InstallRoot 'ollama.exe'
$OllamaApp = Join-Path $InstallRoot 'ollama app.exe'
$StorageDirectory = Join-Path $ProjectRoot 'storage'
$OutputLog = Join-Path $StorageDirectory 'ollama.out.log'
$ErrorLog = Join-Path $StorageDirectory 'ollama.err.log'

if (-not (Test-Path -LiteralPath $Ollama)) {
    throw '未检测到 Ollama。请先从 https://ollama.com/download/windows 安装官方版本。'
}

function Test-OllamaHealth {
    try {
        $Response = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -Method Get -TimeoutSec 2
        return ($null -ne $Response.models)
    }
    catch {
        return $false
    }
}

function Get-ManagedOllamaProcesses {
    return @(Get-Process -ErrorAction SilentlyContinue | Where-Object {
        $_.ProcessName -in @('ollama', 'ollama app', 'llama-server') -and
        -not [string]::IsNullOrWhiteSpace($_.Path) -and
        $_.Path.StartsWith($InstallRoot, [System.StringComparison]::OrdinalIgnoreCase)
    })
}

function Wait-OllamaHealth {
    param(
        [int]$Attempts = 120,
        [int]$DelayMilliseconds = 250
    )

    for ($Attempt = 0; $Attempt -lt $Attempts; $Attempt++) {
        if (Test-OllamaHealth) {
            return $true
        }
        Start-Sleep -Milliseconds $DelayMilliseconds
    }
    return $false
}

function Show-OllamaStatus {
    try {
        & $Ollama list
        & $Ollama ps
    }
    catch {
        # The API health result is authoritative.  A status display failure
        # must not turn an already healthy runtime into a failed startup.
        Write-Warning "Ollama 服务已就绪，但未能显示模型状态：$($_.Exception.Message)"
    }
}

function Ensure-OllamaTrayIcon {
    if ($Headless) {
        return
    }

    if (-not (Test-Path -LiteralPath $OllamaApp)) {
        Write-Warning 'Ollama 服务已就绪，但当前安装中没有 ollama app.exe，无法显示系统托盘图标。'
        return
    }

    $DesktopProcess = Get-Process -Name 'ollama app' -ErrorAction SilentlyContinue
    if ($null -eq $DesktopProcess) {
        Start-Process -FilePath $OllamaApp | Out-Null
        Start-Sleep -Milliseconds 800
    }

    Write-Host 'Ollama 桌面应用已启动；图标位于 Windows 任务栏右下角（可能收纳在“隐藏的图标”箭头中）。' -ForegroundColor Green
}

if ((Test-OllamaHealth) -and -not $ForceRestart) {
    Write-Host 'Ollama 已在运行；未改变现有后端。若需切换后端，请增加 -ForceRestart。' -ForegroundColor Yellow
    Ensure-OllamaTrayIcon
    Show-OllamaStatus
    exit 0
}

# Ollama's Windows process can exist for several seconds before /api/tags is
# ready (GPU discovery is the usual cause).  Do not treat that warm-up window
# as a failed start or touch log files that the existing process still owns.
$ManagedProcesses = Get-ManagedOllamaProcesses
if ($ManagedProcesses.Count -gt 0 -and -not $ForceRestart) {
    Write-Host '检测到 Ollama 进程正在初始化，正在等待服务就绪……' -ForegroundColor Yellow
    if (Wait-OllamaHealth) {
        Write-Host 'Ollama 已启动并通过健康检查。' -ForegroundColor Green
        Ensure-OllamaTrayIcon
        Show-OllamaStatus
        exit 0
    }

    throw '检测到 Ollama 进程，但服务在 30 秒内未就绪。请查看 storage\ollama.err.log；确认无任务运行后，可使用 -ForceRestart 重启。'
}

if ($ForceRestart) {
    $ManagedProcesses = Get-ManagedOllamaProcesses
    $ManagedProcesses | Stop-Process -Force

    # Wait until every managed process has exited so redirected log handles are
    # released before the files are truncated for the next run.
    for ($Attempt = 0; $Attempt -lt 40; $Attempt++) {
        if ((Get-ManagedOllamaProcesses).Count -eq 0) {
            break
        }
        Start-Sleep -Milliseconds 250
    }

    if ((Get-ManagedOllamaProcesses).Count -gt 0) {
        throw 'Ollama 进程未能在 10 秒内退出，未继续覆盖日志或重复启动。'
    }
}

New-Item -ItemType Directory -Path $StorageDirectory -Force | Out-Null
[System.IO.File]::WriteAllText($OutputLog, '', [System.Text.UTF8Encoding]::new($false))
[System.IO.File]::WriteAllText($ErrorLog, '', [System.Text.UTF8Encoding]::new($false))

if ($Backend -ne 'auto') {
    $env:OLLAMA_LLM_LIBRARY = $Backend
}
else {
    Remove-Item Env:OLLAMA_LLM_LIBRARY -ErrorAction SilentlyContinue
}
$env:OLLAMA_DEBUG = 'INFO'

Start-Process `
    -FilePath $Ollama `
    -ArgumentList @('serve') `
    -WindowStyle Hidden `
    -RedirectStandardOutput $OutputLog `
    -RedirectStandardError $ErrorLog | Out-Null

if (Wait-OllamaHealth -Attempts 240) {
    Write-Host "Ollama 启动成功；请求后端：$Backend" -ForegroundColor Green
    Write-Host "日志：$ErrorLog"
    Ensure-OllamaTrayIcon
    Show-OllamaStatus
    exit 0
}

$RecentErrors = (Get-Content -LiteralPath $ErrorLog -Tail 40 -ErrorAction SilentlyContinue) -join [Environment]::NewLine
throw "Ollama 未能通过健康检查。`n$RecentErrors"
