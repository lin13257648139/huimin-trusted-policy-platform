param(
    [int]$Port = 0
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$StorageDirectory = Join-Path $ProjectRoot 'storage'
$PidFile = Join-Path $StorageDirectory 'server.pid'
$PortFile = Join-Path $StorageDirectory 'server.port'

if ($Port -lt 0 -or $Port -gt 65535) {
    throw '端口必须在 1 到 65535 之间；省略参数时将自动读取运行记录。'
}

if ($Port -eq 0 -and (Test-Path -LiteralPath $PortFile)) {
    $RecordedPort = 0
    $PortText = (Get-Content -LiteralPath $PortFile -Raw).Trim()
    if ([int]::TryParse($PortText, [ref]$RecordedPort) -and $RecordedPort -ge 1 -and $RecordedPort -le 65535) {
        $Port = $RecordedPort
    }
}
if ($Port -eq 0) {
    $Port = 8000
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

function Clear-ServerMetadata {
    [System.IO.File]::Delete($PidFile)
    [System.IO.File]::Delete($PortFile)
}

$TargetProcessId = 0
if (Test-Path -LiteralPath $PidFile) {
    $PidText = (Get-Content -LiteralPath $PidFile -Raw).Trim()
    $RecordedProcessId = 0
    if ([int]::TryParse($PidText, [ref]$RecordedProcessId) -and (Test-ManagedProcess -ProcessId $RecordedProcessId)) {
        $TargetProcessId = $RecordedProcessId
    }
}

if ($TargetProcessId -eq 0 -and (Test-AppHealth)) {
    $Connection = Get-NetTCPConnection `
        -LocalAddress '127.0.0.1' `
        -LocalPort $Port `
        -State Listen `
        -ErrorAction SilentlyContinue | Select-Object -First 1

    if ($null -ne $Connection -and (Test-ManagedProcess -ProcessId $Connection.OwningProcess)) {
        $TargetProcessId = [int]$Connection.OwningProcess
    }
    else {
        throw "端口 $Port 上检测到惠民智导，但无法确认它属于本项目的 Python 环境。为避免误杀其他程序，未执行停止。"
    }
}

if ($TargetProcessId -eq 0) {
    Clear-ServerMetadata
    Write-Host "惠民智导当前未运行；已清理可能残留的启动记录。" -ForegroundColor Yellow
    exit 0
}

Stop-Process -Id $TargetProcessId -Force
for ($Attempt = 0; $Attempt -lt 20; $Attempt++) {
    if (-not (Get-Process -Id $TargetProcessId -ErrorAction SilentlyContinue)) {
        break
    }
    Start-Sleep -Milliseconds 250
}

if (Get-Process -Id $TargetProcessId -ErrorAction SilentlyContinue) {
    throw "进程 PID $TargetProcessId 未能停止，请以管理员身份检查该进程。"
}

Clear-ServerMetadata
Write-Host "惠民智导已停止（PID $TargetProcessId，端口 $Port）。" -ForegroundColor Green
