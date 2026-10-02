# 模型与运行时许可证登记

本项目的正式规则、政策证据与评测数据不依赖云端 API。生成式能力采用本机 Ollama 运行，可在模型不可用时显式降级到确定性管线。

| 组件 | 固定版本/标签 | 用途 | 许可证 | 是否随源码包分发 |
| --- | --- | --- | --- | --- |
| Ollama | 0.35.0 | 本地模型运行时 | MIT | 否，提供官方安装方式 |
| Qwen3 4B Instruct | `qwen3:4b-instruct`；4.0B；Q4_K_M；2,497,293,803 B | 结构化事实候选抽取 | Apache-2.0 | 否，由 Ollama 官方模型库拉取 |
| Qwen3 Embedding 0.6B | `qwen3-embedding:0.6b`；595.78M；Q8_0；639,150,858 B | 本地语义向量检索 | Apache-2.0 | 否，由 Ollama 官方模型库拉取 |

本机冻结摘要（2026-10-03）：

- `qwen3:4b-instruct`：`0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0`
- `qwen3-embedding:0.6b`：`ac6da0dfba84a81fdbfbaf330198c33cd77c4cdfc53e8bc50eb581914a15621d`
- 评测硬件：NVIDIA GeForce RTX 4060 Laptop GPU（8,188 MiB）；610.78 驱动下自动探测曾回退 CPU，使用项目脚本固定 `cuda_v12` 后，`ollama ps` 已核验两套模型均为 `100% GPU`。最终性能报告仅引用该 GPU 复跑结果。

官方依据（核验日期：2026-10-03）：

- Ollama 官方仓库许可证：https://github.com/ollama/ollama/blob/main/LICENSE
- Qwen3 官方仓库许可证说明：https://github.com/QwenLM/Qwen3
- Ollama 官方 Qwen3 模型页：https://ollama.com/library/qwen3
- Ollama 官方 Qwen3 Embedding 模型页：https://ollama.com/library/qwen3-embedding

发布要求：

1. 不把模型权重打入竞赛源码 ZIP，避免包体过大与许可证遗漏。
2. 在部署说明中记录实际模型标签、Ollama 版本、模型摘要和拉取日期。
3. 模型输出仅作为候选；正式规则发布、资格状态和政策证据仍受确定性约束。
4. 若赛前更换模型，必须重新运行 AI 管线评测、高风险回归和许可证登记。
