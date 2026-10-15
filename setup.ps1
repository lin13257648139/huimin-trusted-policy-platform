param(
    [switch]$RefreshDependencies
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPython = Join-Path $ProjectRoot '.venv\Scripts\python.exe'

Set-Location -LiteralPath $ProjectRoot
if (-not (Test-Path -LiteralPath $VenvPython)) {
    $PythonCommand = Get-Command 'py.exe' -ErrorAction SilentlyContinue
    if ($PythonCommand) {
        & $PythonCommand.Source -3.12 -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw "创建虚拟环境失败，退出码：$LASTEXITCODE" }
    }
    else {
        $PythonCommand = Get-Command 'python.exe' -ErrorAction SilentlyContinue
        if (-not $PythonCommand) {
            throw 'Python was not found. Install Python 3.11 or 3.12 and add it to PATH.'
        }
        & $PythonCommand.Source -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw "创建虚拟环境失败，退出码：$LASTEXITCODE" }
    }
}

& $VenvPython -c "import sys; assert (3, 11) <= sys.version_info[:2] < (3, 13), 'Python 3.11 or 3.12 is required'"
if ($LASTEXITCODE -ne 0) { throw "Python版本检查失败，退出码：$LASTEXITCODE" }
if ($RefreshDependencies) {
    & $VenvPython -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw "pip升级失败，退出码：$LASTEXITCODE" }
}
& $VenvPython -m pip install -r requirements.lock
if ($LASTEXITCODE -ne 0) { throw "依赖安装失败，退出码：$LASTEXITCODE" }
Write-Output 'Environment ready. Run .\start.ps1 and open http://127.0.0.1:8000'
