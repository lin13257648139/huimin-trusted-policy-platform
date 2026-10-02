param(
    [ValidateRange(1, 1000)]
    [int]$Lines = 80,
    [switch]$Follow
)

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$OutputLog = Join-Path $ProjectRoot 'storage\server.out.log'
$ErrorLog = Join-Path $ProjectRoot 'storage\server.err.log'
$LogFiles = @($OutputLog, $ErrorLog) | Where-Object { Test-Path -LiteralPath $_ }

if ($LogFiles.Count -eq 0) {
    Write-Host '尚无服务日志。请先运行 .\start.ps1。' -ForegroundColor Yellow
    exit 0
}

if ($Follow) {
    Write-Host '正在持续显示日志，按 Ctrl+C 退出（不会停止服务）。'
    Get-Content -LiteralPath $LogFiles -Tail $Lines -Wait
}
else {
    Get-Content -LiteralPath $LogFiles -Tail $Lines
}
