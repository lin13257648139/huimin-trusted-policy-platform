# 数据集卡：惠民智导 V0.6

## 组成

1. `raw_official/` 与 `政策证据包/`：国家、广东省、广州市政府官网网页或PDF原始文件。
2. `processed/policy_source_catalog.csv`：政策元数据、有效期、来源URL和使用风险。
3. `processed/benefit_catalog_seed.csv`：11个救助及关联事项，其中5个进入MVP。
4. `processed/office_directory_seed.csv`：广州市及11区民政部门公开联系方式。
5. `processed/synthetic_conformance_cases.jsonl`：240个确定性生成的边界/缺失/换版/急难案例。
6. `evaluation/retrieval_benchmark.json`：12条内部人工整理的政策检索查询，只评估当前13条证据片段。
7. `evaluation/expert_review_A.csv`、`expert_review_B.csv`：两名专家已完成的120条独立盲评记录，不含系统答案；按画像去重后为107例。
8. `evaluation/policy_compiler_benchmark.jsonl`：10条内部合成政策条款，用于验证候选编译器的可重复性与安全拦截。
9. `evaluation/ocr_synthetic/`：4类材料×4种图像扰动，共16张无真实信息的OCR鲁棒性测试图及清单。
10. `ml/intent_dataset.json`：团队内部编写的40条训练语句和20条冻结测试语句，用于事项意图路由；不含真人数据。
11. `evaluation/profile_extraction_benchmark.jsonl`：40条内部合成画像表达，用于比较确定性抽取与Schema约束模型集成。

## 合成案例用途

`synthetic_conformance_cases.jsonl`中的预期标签由当前规则引擎生成，只用于回归、接口联调和前端演示，不能用于证明业务准确率。`evaluation/expert_gold_master.csv`虽然复用了其中的家庭画像，但标签来自A/B独立评审和专家C裁决，可用于报告当前构造案例上的专家评测结果；仍不能替代真实群众案例和用户试点。

固定随机种子：`20260929`。可用以下命令重新生成和复核：

```powershell
.\.venv\Scripts\python.exe scripts\generate_synthetic_cases.py
.\.venv\Scripts\python.exe scripts\evaluate_conformance.py
```

## 正式国赛评测集建设要求

- 从合成集另行抽取并改写100—150个案例，请社会工作、公共管理、法律或基层经办人员双人独立标注。
- 专家标注集必须冻结，开发期间不能直接修改答案。
- 报告标注人员构成、分歧裁决方式、一致性指标和脱敏流程。
- 真实案例必须取得知情同意；不保存无必要的姓名、证件号、银行卡号和完整医疗原件。
- 按普通、阈值边界、信息缺失、政策换版、跨地区、急难情形和对抗输入分层报告结果。

## 已知局限

- 当前规则只覆盖广州市首版MVP。
- 刚性支出困难家庭仅按已核验的60%支出比例和2025年广州城镇居民人均可支配收入86069元进行2026年度预筛；支出范围、收入扣减和财产核对仍由经办部门确认。
- 政策状态以2026-09-30为核验基准，正式试点和提交前必须再次检查。
- 检索基准规模很小，当前结果不能外推到扩大后的政策语料库；扩充语料后必须重新冻结评测集。
- A/B专家盲评及专家C对6条记录、10个分歧决定的裁决均已完成。金标已冻结，120条记录含13条重复画像，正式报告按107个唯一画像、535个事项决定计算。该结果只代表当前构造案例，不得外推为真实群众场景准确率。
- Policy2Rule内部合成基准规模小且围绕当前字段设计，即使取得高分也不能替代真实政策条款双人标注测试。
- OCR合成基准来自固定模板，不能代表真实拍摄、复杂版式或手写材料；正式报告必须补充独立模板和人工标注测试集。
- 意图与画像抽取基准均由团队围绕现有五类事项构造，存在模板和词汇偏差；只用于第二阶段算法对照，不能替代第三阶段真人试点。

