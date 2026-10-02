param(
    [int]$Port = 0
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$StorageDirectory = Join-Path $ProjectRoot 'storage'
$PidFile = Join-Path $StorageDirectory 'server.pid'
$PortFile = Join-Path $StorageDirectory 'server.port'
$OutputLog = Join-Path $StorageDirectory 'server.out.log'
$ErrorLog = Join-Path $StorageDirectory 'server.err.log'

if ($Port -eq 0 -and (Test-Path -LiteralPath $PortFile)) {
    $RecordedPort = 0
    $PortText = (Get-Content -LiteralPath $PortFile -Raw).Trim()
    if ([int]::TryParse($PortText, [ref]$RecordedPort)) {
        $Port = $RecordedPort
    }
}
if ($Port -eq 0) {
    $Port = 8000
}
if ($Port -lt 1 -or $Port -gt 65535) {
    throw '端口必须在 1 到 65535 之间。'
}

$ProcessText = '无运行记录'
if (Test-Path -LiteralPath $PidFile) {
    $ProcessText = (Get-Content -LiteralPath $PidFile -Raw).Trim()
}

try {
    $Response = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health" -Method Get -TimeoutSec 2
    if ($Response.status -eq 'ok' -and $Response.service_id -eq 'huimin-guide') {
        Write-Host "运行状态： 正常" -ForegroundColor Green
        Write-Host "访问地址： http://127.0.0.1:$Port"
        Write-Host "进程 PID： $ProcessText"
        Write-Host "标准输出： $OutputLog"
        Write-Host "错误日志： $ErrorLog"
        exit 0
    }
}
catch {
    # 统一在下方输出离线状态。
}

Write-Host "运行状态： 未运行或健康检查失败" -ForegroundColor Yellow
Write-Host "检查端口： $Port"
Write-Host "进程记录： $ProcessText"
Write-Host "错误日志： $ErrorLog"
exit 1
