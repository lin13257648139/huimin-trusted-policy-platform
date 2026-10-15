# 离线评测区

本目录保存可复现的工程评测资产。当前所有基准均为团队自编合成数据，或由项目组依据官方政策原文制作的标注；截至当前版本，项目没有开展外部专家评测、真人试点或独立第三方测评。

## 可以引用的结论

- 规则回归、证据完整性、安全门、检索、Policy2Rule、OCR和性能结果，只能描述对应冻结数据集与运行环境。
- 报告必须保留数据来源、样本量、版本、源码指纹、生成时间和限制说明。
- 官方条款基准中的原文来自政策证据包，但其期望标签由项目组制作，不具有独立专家属性。

## 禁止表述

- 不得使用“专家评测”“外部评审”“独立盲评”“第三方验证”等尚未发生的表述。
- 不得把合成案例上的一致率表述为真实群众业务准确率、政策审核正确率或上线效果。
- 不得把系统按照自身规则生成的标签用于证明系统优于人工。

## 未来人工评测工具

`build_expert_packet.py`、`merge_expert_reviews.py`和`evaluate_expert_gold.py`仅是未来工作流工具。只有在评审人员身份、独立填写记录、原始表、裁决记录与授权说明均可核验时，才允许生成专家评测报告。当前发布包不包含专家评测结果。

## 当前主要资产

- `synthetic_conformance_cases.jsonl`：确定性规则的合成边界回归集。
- `profile_extraction_benchmark.jsonl`：团队自编口语画像抽取集。
- `retrieval_benchmark.json`：团队自编政策检索问题。
- `policy_compiler_real_benchmark.jsonl`：官方条款原文与项目组制作的期望标签。
- `high_risk_safety_benchmark.jsonl`：项目组编写的安全回归案例。
- `active_question_decision_cases.jsonl`：动态与固定策略逐轮运行的合成决策路径，轨迹保存在`active_question_traces.jsonl`。
- `ocr_synthetic/`：程序生成的无真实个人信息OCR材料。

机器可读的数据治理边界见 `dataset_governance_manifest.json`。
