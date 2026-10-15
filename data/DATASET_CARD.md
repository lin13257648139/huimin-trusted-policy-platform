# 数据集卡

## 数据范围

当前项目只使用政府公开政策文件、团队自编合成家庭画像、程序生成演示材料和项目组制作的评测标签，不包含真实困难群众的姓名、证件号、电话、地址或业务档案。

## 数据资产

1. `processed/synthetic_conformance_cases.jsonl`：依据已登记规则生成的合成边界案例，用于回归。
2. `evaluation/profile_extraction_benchmark.jsonl`：团队自编的自然语言家庭情况，用于信息抽取测试。
3. `evaluation/retrieval_benchmark.json`：团队自编的政策检索查询及期望证据。
4. `evaluation/policy_compiler_benchmark.jsonl`：团队自编政策条款模板。
5. `evaluation/policy_compiler_real_benchmark.jsonl`：官方政策逐字条款，期望标签由项目组制作。
6. `evaluation/high_risk_safety_benchmark.jsonl`：团队编写的越域、注入、UNKNOWN和时态边界案例。
7. `evaluation/ocr_synthetic/`：程序生成的无个人信息材料图片。
8. `evaluation/active_question_decision_cases.jsonl`：项目组构造的120条决策路径，用于真实逐轮比较动态与固定提问策略。

## 标签独立性

所有现有标签均非外部独立标注。项目尚未开展专家评测或真人试点，因此任何内部指标只能用于工程回归与方案比较，不能证明真实业务准确率或实际应用效果。

## 数据治理

- 所有报告需记录数据文件SHA-256、应用版本、规则引擎版本和源码树指纹。
- 评测集与训练或提示调优数据必须在后续实验中明确分离。
- 新增真人或专家数据前，必须补充授权、去标识化、用途、保存期限和删除机制。
- 不得通过复制系统预测结果制造人工金标。
- 主动提问减题率只适用于合成决策路径，不得表述为真人填写效率。

机器可读清单见 `evaluation/dataset_governance_manifest.json`。
