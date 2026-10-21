param(
    [switch]$SkipDependencyAudit,
    [switch]$RequireNativeSemgrep
)

$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Python = Join-Path $Root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python)) {
    throw '缺少.venv，请先运行setup.ps1'
}
Set-Location -LiteralPath $Root

function Invoke-Gate {
    param([string]$Name, [string[]]$Arguments)
    Write-Host "[quality] $Name" -ForegroundColor Cyan
    & $Python @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Name 未通过（exit=$LASTEXITCODE）"
    }
}

Invoke-Gate 'Ruff' @('-m', 'ruff', 'check', 'app', 'scripts', 'tests')
Invoke-Gate 'Mypy' @('-m', 'mypy', 'app')
Invoke-Gate 'Pytest + branch coverage' @(
    '-m', 'pytest', '--cov=app', '--cov-branch', '--cov-report=term-missing',
    '--cov-report=json:data/evaluation/coverage_report.json'
)
Invoke-Gate 'National-competition branch thresholds' @('scripts/check_coverage.py')
Invoke-Gate 'Bandit' @('-m', 'bandit', '-q', '-r', 'app')
Invoke-Gate 'AST static security policy' @('scripts/static_security_policy.py', 'app', 'scripts')

Write-Host '[quality] Semgrep local rules' -ForegroundColor Cyan
$Semgrep = Join-Path $Root '.venv\Scripts\pysemgrep.exe'
$SemgrepConfig = Join-Path $Root 'tmp\semgrep-config'
New-Item -ItemType Directory -Force -Path $SemgrepConfig | Out-Null
$previousXdgConfig = $env:XDG_CONFIG_HOME
$env:XDG_CONFIG_HOME = $SemgrepConfig
$semgrepPassed = $false
try {
    if (Test-Path -LiteralPath $Semgrep) {
        & $Semgrep scan --config .semgrep.yml --error --quiet app scripts
        $semgrepPassed = $LASTEXITCODE -eq 0
    }
}
finally {
    $env:XDG_CONFIG_HOME = $previousXdgConfig
}
if (-not $semgrepPassed) {
    if ($RequireNativeSemgrep) {
        throw '原生Semgrep未通过；正式竞赛发布不允许以本地AST策略替代'
    }
    Write-Warning '本机Semgrep引擎不可用；AST同规则检查已通过，但原生Semgrep仍必须在Linux CI通过。'
}

Write-Host '[quality] detect-secrets' -ForegroundColor Cyan
# Hex-escape the quote characters so Windows PowerShell 5.1 and pwsh 7 pass
# the same regex to Python; literal nested quotes are stripped differently.
$SecretJson = & $Python -m detect_secrets scan --all-files --exclude-lines '\x22source_sha256\x22\s*:' app scripts tests .env.example compose.yaml Dockerfile README.md
if ($LASTEXITCODE -ne 0) {
    throw "detect-secrets执行失败（exit=$LASTEXITCODE）"
}
$SecretReportPath = Join-Path $Root 'tmp\secret-scan.local.json'
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$SecretText = $SecretJson -join [Environment]::NewLine
[System.IO.File]::WriteAllText($SecretReportPath, $SecretText, $Utf8NoBom)
try {
    & $Python -c "import json,sys; p=json.load(open(sys.argv[1], encoding='utf-8')); n=sum(len(v) for v in p['results'].values()); print('secret_candidates=', n); sys.exit(n != 0)" $SecretReportPath
    $SecretScanExit = $LASTEXITCODE
}
finally {
    Remove-Item -LiteralPath $SecretReportPath -Force -ErrorAction SilentlyContinue
}
if ($SecretScanExit -ne 0) {
    throw '密钥扫描发现未审查候选，请移除真实密钥或建立经审查基线'
}

if (-not $SkipDependencyAudit) {
    Invoke-Gate 'pip-audit locked dependencies' @(
        '-m', 'pip_audit', '-r', 'requirements.lock', '--no-deps', '--disable-pip',
        '--cache-dir', 'tmp/pip-audit-cache', '--timeout', '10', '--progress-spinner', 'off'
    )
}
Invoke-Gate 'Installed dependency consistency' @('-m', 'pip', 'check')
Write-Host 'QUALITY_GATES_OK' -ForegroundColor Green
