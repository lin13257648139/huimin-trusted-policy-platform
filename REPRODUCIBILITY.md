# 第一、二阶段复现说明

本文件只覆盖工程可信性与内部AI实验，不把专家评审、真人试点或外部证明混入自动结果。

## 固定环境

- Python：3.11或3.12，当前冻结环境为3.12.14。
- 应用版本：`1.3.0`；规则引擎版本由API返回，当前为`rule-engine/0.5.0`。
- 依赖：`requirements.lock`固定直接与传递依赖；`requirements.txt`只表达允许升级的开发约束。
- 政策原件：`data/raw_official/provenance_manifest.json`记录项目相对路径、大小与SHA-256。
- 随机性：语言模型请求固定temperature=0、seed=20261002；模型名、提示指纹和延迟写入响应或实验报告。

## 一键复现

```powershell
.\setup.ps1
.\reproduce_phase12.ps1
```

脚本依次重建来源指纹、第二阶段冻结基准、合成规则回归集和主动提问决策路径，运行规则回归、检索评测、Policy2Rule三轨评测、AI主线评测、架构消融、安全回归、OCR、接口性能、工程检查及全部单元/API测试。每条外部命令都检查退出码，任何一步失败都会立即停止，不会输出虚假的成功提示。Policy2Rule与检索的开发/最终集以完整政策文件为隔离单元，隔离结果和数据哈希记录于`stage2_split_manifest.json`。

关键机器可读产物：

- `data/evaluation/ai_pipeline_report.json`
- `data/evaluation/ablation_report.json`
- `data/evaluation/retrieval_report.json`
- `data/evaluation/policy_compiler_report.json`
- `data/evaluation/policy_compiler_real_report.json`
- `data/evaluation/release_manifest.json`
- `data/evaluation/stage2_split_manifest.json`
- `data/evaluation/ai_workload_pressure_report.json`
- `data/raw_official/provenance_manifest.json`

所有报告仅保存项目相对路径，不保存个人用户名、Python绝对路径或群众原文。

## 可选本地大模型复现

代码在没有模型时会如实标记 `not_run` 并安全降级。先拉取冻结模型，再在新 PowerShell 中复现：

```powershell
ollama pull qwen3:4b-instruct
ollama pull qwen3-embedding:0.6b
$env:AI_MODE='hybrid'
$env:OLLAMA_MODEL='qwen3:4b-instruct'
$env:OLLAMA_EMBED_MODEL='qwen3-embedding:0.6b'
$env:OLLAMA_TIMEOUT_SECONDS='120'
.\start.ps1
.\.venv\Scripts\python.exe scripts\evaluate_ai_pipeline.py
.\.venv\Scripts\python.exe scripts\evaluate_policy_compiler.py --benchmark data\evaluation\policy_compiler_real_benchmark.jsonl --split frozen_final_test --tracks all --require-live-llm --output data\evaluation\policy_compiler_real_report.json
.\.venv\Scripts\python.exe scripts\benchmark_ai_workloads.py
```

只有报告中`schema_constrained_llm_ensemble`状态为完成、`actual_routes`出现`rrf(bm25,local-embedding)`、Policy2Rule报告的LLM轨提供真实Ollama provider，且压力报告覆盖并发1/3/5/10时，才可声称相应模型实验实际运行。模型不可用、部分请求降级或语义模型缺失时，不得引用模型指标。

## 结果边界

画像、意图与检索基准均为团队内部构造数据；规则回归标签来自确定性引擎。它们用于算法选型、回归和安全消融，不是第三阶段真人试点，也不能证明真实业务效果。
