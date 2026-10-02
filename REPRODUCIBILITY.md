# 第一、二阶段复现说明

本文件只覆盖工程可信性与内部AI实验，不把专家评审、真人试点或外部证明混入自动结果。

## 固定环境

- Python：3.11或3.12，当前冻结环境为3.12.14。
- 应用版本：`0.7.0`；规则引擎版本由API返回，当前为`rule-engine/0.4.1`。
- 依赖：`requirements.lock`固定直接与传递依赖；`requirements.txt`只表达允许升级的开发约束。
- 政策原件：`data/raw_official/provenance_manifest.json`记录项目相对路径、大小与SHA-256。
- 随机性：语言模型请求固定temperature=0、seed=20261002；模型名、提示指纹和延迟写入响应或实验报告。

## 一键复现

```powershell
.\setup.ps1
.\reproduce_phase12.ps1
```

脚本依次重建来源指纹和内部画像基准，运行规则回归、检索评测、Policy2Rule评测、AI主线评测、架构消融、工程检查及全部单元/API测试。任何一步失败都会停止。

关键机器可读产物：

- `data/evaluation/ai_pipeline_report.json`
- `data/evaluation/ablation_report.json`
- `data/evaluation/retrieval_report.json`
- `data/evaluation/policy_compiler_report.json`
- `data/raw_official/provenance_manifest.json`

所有报告仅保存项目相对路径，不保存个人用户名、Python绝对路径或群众原文。

## 可选本地大模型复现

当前代码在没有模型时会如实标记`not_run`并安全降级。若本机已安装Ollama并已下载模型，可在新PowerShell中设置：

```powershell
$env:AI_MODE='hybrid'
$env:OLLAMA_MODEL='qwen2.5:7b-instruct-q4_K_M'
$env:OLLAMA_EMBED_MODEL='bge-m3'
.\start.ps1
.\.venv\Scripts\python.exe scripts\evaluate_ai_pipeline.py
```

只有报告中`schema_constrained_llm_ensemble`状态为完成、且`actual_routes`出现`rrf(bm25,local-embedding)`时，才可声称相应模型实验实际运行。模型不可用、部分请求降级或语义模型缺失时，不得引用模型指标。

## 结果边界

画像、意图与检索基准均为团队内部构造数据；规则回归标签来自确定性引擎。它们用于算法选型、回归和安全消融，不是第三阶段真人试点，也不能证明真实业务效果。
