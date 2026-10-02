param(
    [switch]$RefreshDependencies
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPython = Join-Path $ProjectRoot '.venv\Scripts\python.exe'

Set-Location -LiteralPath $ProjectRoot
if (-not (Test-Path -LiteralPath $VenvPython)) {
    $PythonCommand = Get-Command 'py.exe' -ErrorAction SilentlyContinue
    if ($PythonCommand) {
        & $PythonCommand.Source -3.12 -m venv .venv
    }
    else {
        $PythonCommand = Get-Command 'python.exe' -ErrorAction SilentlyContinue
        if (-not $PythonCommand) {
            throw 'Python was not found. Install Python 3.11 or 3.12 and add it to PATH.'
        }
        & $PythonCommand.Source -m venv .venv
    }
}

& $VenvPython -c "import sys; assert (3, 11) <= sys.version_info[:2] < (3, 13), 'Python 3.11 or 3.12 is required'"
if ($RefreshDependencies) {
    & $VenvPython -m pip install --upgrade pip
}
& $VenvPython -m pip install -r requirements.lock
Write-Output 'Environment ready. Run .\start.ps1 and open http://127.0.0.1:8000'
