$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$env:PYTHONUTF8 = '1'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'

Set-Location -LiteralPath $ProjectRoot
if (-not (Test-Path -LiteralPath $Python)) {
    throw 'Environment is missing. Run .\setup.ps1 first.'
}

function Invoke-CheckedPython {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    & $Python @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "命令失败（退出码 $LASTEXITCODE）：python $($Arguments -join ' ')"
    }
}

Invoke-CheckedPython scripts\build_provenance_manifest.py
Invoke-CheckedPython scripts\generate_ai_benchmark.py
Invoke-CheckedPython scripts\generate_synthetic_cases.py
Invoke-CheckedPython scripts\evaluate_conformance.py
Invoke-CheckedPython scripts\evaluate_retrieval.py
Invoke-CheckedPython scripts\evaluate_policy_compiler.py --output data\evaluation\policy_compiler_report.json
Invoke-CheckedPython scripts\build_real_policy_benchmark.py
Invoke-CheckedPython scripts\evaluate_policy_compiler.py --benchmark data\evaluation\policy_compiler_real_benchmark.jsonl --output data\evaluation\policy_compiler_real_report.json
Invoke-CheckedPython scripts\evaluate_ai_pipeline.py
Invoke-CheckedPython scripts\build_question_strategy_benchmark.py
Invoke-CheckedPython scripts\evaluate_question_strategy.py
Invoke-CheckedPython scripts\evaluate_ablation.py
Invoke-CheckedPython scripts\build_safety_benchmark.py
Invoke-CheckedPython scripts\evaluate_safety_benchmark.py
Invoke-CheckedPython scripts\generate_ocr_benchmark.py
Invoke-CheckedPython scripts\evaluate_ocr.py
Invoke-CheckedPython scripts\build_dataset_manifest.py
Invoke-CheckedPython scripts\build_sbom.py
Invoke-CheckedPython scripts\benchmark_api.py
Invoke-CheckedPython scripts\benchmark_concurrency.py
Invoke-CheckedPython scripts\build_release_manifest.py
Invoke-CheckedPython scripts\stamp_evaluation_reports.py
Invoke-CheckedPython scripts\check_project.py
Invoke-CheckedPython -m pytest -q

Write-Host 'Phase 1-2 reproduction passed: provenance, AI experiments, safety ablation, governance manifests, HTTP benchmark, checks and tests.' -ForegroundColor Green
