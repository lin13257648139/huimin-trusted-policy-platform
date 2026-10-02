param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8000
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$StorageDirectory = Join-Path $ProjectRoot 'storage'
$PidFile = Join-Path $StorageDirectory 'server.pid'
$PortFile = Join-Path $StorageDirectory 'server.port'
$OutputLog = Join-Path $StorageDirectory 'server.out.log'
$ErrorLog = Join-Path $StorageDirectory 'server.err.log'

# 未显式传入端口时沿用上次记录，避免曾用8010启动后再次执行脚本又在8000启动一份。
if (-not $PSBoundParameters.ContainsKey('Port') -and (Test-Path -LiteralPath $PortFile)) {
    $RecordedPort = 0
    $PortText = (Get-Content -LiteralPath $PortFile -Raw).Trim()
    if ([int]::TryParse($PortText, [ref]$RecordedPort) -and $RecordedPort -ge 1 -and $RecordedPort -le 65535) {
        $Port = $RecordedPort
    }
}
$HealthUri = "http://127.0.0.1:$Port/api/health"

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
    Write-Host "惠民智导已在运行，无需重复启动。" -ForegroundColor Green
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
        Write-Host "惠民智导启动成功。" -ForegroundColor Green
        Write-Host "访问地址： http://127.0.0.1:$Port"
        Write-Host "进程 PID： $($ServerProcess.Id)"
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

