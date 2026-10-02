param(
    [ValidateSet('auto', 'cuda_v12', 'cuda_v13', 'cpu')]
    [string]$Backend = 'auto',

    [switch]$ForceRestart
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$InstallRoot = Join-Path $env:LOCALAPPDATA 'Programs\Ollama'
$Ollama = Join-Path $InstallRoot 'ollama.exe'
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

if ((Test-OllamaHealth) -and -not $ForceRestart) {
    Write-Host 'Ollama 已在运行；未改变现有后端。若需切换后端，请增加 -ForceRestart。' -ForegroundColor Yellow
    & $Ollama list
    & $Ollama ps
    exit 0
}

if ($ForceRestart) {
    $ManagedProcesses = Get-Process -ErrorAction SilentlyContinue | Where-Object {
        $_.ProcessName -in @('ollama', 'ollama app', 'llama-server') -and
        -not [string]::IsNullOrWhiteSpace($_.Path) -and
        $_.Path.StartsWith($InstallRoot, [System.StringComparison]::OrdinalIgnoreCase)
    }
    $ManagedProcesses | Stop-Process -Force
    Start-Sleep -Milliseconds 800
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

for ($Attempt = 0; $Attempt -lt 60; $Attempt++) {
    if (Test-OllamaHealth) {
        Write-Host "Ollama 启动成功；请求后端：$Backend" -ForegroundColor Green
        Write-Host "日志：$ErrorLog"
        & $Ollama list
        exit 0
    }
    Start-Sleep -Milliseconds 250
}

$RecentErrors = (Get-Content -LiteralPath $ErrorLog -Tail 40 -ErrorAction SilentlyContinue) -join [Environment]::NewLine
throw "Ollama 未能通过健康检查。`n$RecentErrors"
