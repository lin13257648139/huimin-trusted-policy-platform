$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'

Set-Location -LiteralPath $ProjectRoot
if (-not (Test-Path -LiteralPath $Python)) {
    throw 'Environment is missing. Run .\setup.ps1 first.'
}

& $Python scripts\build_provenance_manifest.py
& $Python scripts\generate_ai_benchmark.py
& $Python scripts\evaluate_conformance.py
& $Python scripts\evaluate_retrieval.py
& $Python scripts\evaluate_policy_compiler.py
& $Python scripts\evaluate_ai_pipeline.py
& $Python scripts\evaluate_question_strategy.py
& $Python scripts\evaluate_ablation.py
& $Python scripts\build_safety_benchmark.py
& $Python scripts\evaluate_safety_benchmark.py
& $Python scripts\build_dataset_manifest.py
& $Python scripts\build_sbom.py
& $Python scripts\benchmark_concurrency.py
& $Python scripts\check_project.py
& $Python -m pytest -q

Write-Host 'Phase 1-2 reproduction passed: provenance, AI experiments, safety ablation, governance manifests, HTTP benchmark, checks and tests.' -ForegroundColor Green
