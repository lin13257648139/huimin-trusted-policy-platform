# 数据集卡

## 数据范围

当前项目只使用政府公开政策文件、团队自编合成家庭画像、程序生成演示材料和项目组制作的评测标签，不包含真实困难群众的姓名、证件号、电话、地址或业务档案。

## 数据资产

1. `processed/synthetic_conformance_cases.jsonl`：依据已登记规则生成的合成边界案例，用于回归。
2. `ml/intent_dataset.json`：100条开发语句与250条冻结测试语句，模板族隔离。
3. `evaluation/profile_extraction_benchmark.jsonl`：300条程序渲染的项目组自编家庭情况，覆盖10类表达。
4. `evaluation/retrieval_benchmark.json`：40条开发查询与120条冻结查询；按完整政策文件隔离。
5. `evaluation/policy_compiler_benchmark.jsonl`：团队自编政策条款模板。
6. `evaluation/policy_compiler_real_benchmark.jsonl`：50条开发条款与120条冻结官方逐字条款；期望标签由项目组按公开指南制作。
7. `evaluation/high_risk_safety_benchmark.jsonl`：320条越域、注入、UNKNOWN、时态和发布门案例。
8. `evaluation/ocr_synthetic/`：程序生成的100张无个人信息材料图片，覆盖10种版式和10种质量变化。
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

## 冻结和隔离

- 机器可读分组见`evaluation/stage2_split_manifest.json`，其中保存数据文件SHA-256、规模和类别分布。
- 检索与Policy2Rule以`source_id`为最小隔离单元；同一政策文件的条款、切片和改写不得跨开发集与最终测试集。
- 意图分类的开发模板族与最终模板族分离；画像和OCR只有冻结内部测试用途，不是自然人分布抽样。
- 任何修改抽取器、检索器、提示词或阈值后，必须重新冻结新版本，不得根据最终集错误逐例调参后仍沿用原报告。
