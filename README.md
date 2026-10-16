# 惠民智导可信政策智能平台 1.4.0

面向多类政策服务的可信、可解释、可追溯智能平台；当前以广州市社会救助作为首个完整落地场景，实现政策时态选择、三值资格预筛、组合救助排序、逐条证据解释、材料质量预检和规则治理看板。

> 本系统只做申请前预筛与导办，不具有行政审批效力。最终资格、金额与材料要求以主管部门审核为准。

## 已实现能力

- 5类MVP事项：低收入人口认定、最低生活保障、低保边缘家庭、刚性支出困难家庭、临时救助。
- 日期敏感的政策快照：2026-07-31与2026-08-01使用不同的低保规则状态。
- TRUE / FALSE / UNKNOWN三值规则，缺数据、版本冲突或政策到期时安全拒绝强判断。
- 基于候选事项影响范围与急难优先级的主动补问；不让用户一开始就面对整张复杂表单。
- 反事实式“最少还需确认”解释、属地办理窗口、电话与行动清单，形成线上预筛到线下咨询闭环。
- 每个条件返回理由、实际值、期望值、补充建议、政策原文片段和政府链接。
- 自然语言家庭情况抽取采用“确定性高精度基线 + 可选Schema约束本地大模型”集成；模型冲突、超时或结构非法时可见降级，大模型不参与最终资格求值。
- 本地字符N-gram朴素贝叶斯排序可能关注事项；只影响导办顺序，不影响资格。250条内部合成冻结测试集上相对关键词基线有明确对照，禁止外推为真实用户效果。
- 字段加权BM25政策检索返回条款证据和匹配词；配置本地嵌入模型后使用RRF混合召回，接口始终返回实际检索路径和降级原因。
- JPG/PNG/WEBP/PDF材料包真实预检：文件完整性、缺项、重复项、分辨率、曝光、对比度和清晰度；图片通过本地RapidOCR按内容辅助分类并抽取日期、金额候选。完整OCR文本和原件不进入业务数据库或长期目录；上传框架可能使用请求级系统临时文件，关闭上传对象后清理。
- 居民预筛默认无状态，服务器不保存结构化画像；只有用户主动勾选后才保存30天并生成访问/删除凭证。家庭自由描述始终不落库，反馈评论也必须另行明确同意。
- 规则登记表记录版本、有效期、审核状态、来源与发布控制；治理台展示可核验控制和SHA-256指纹，不使用虚构“安全评分”。
- 数据驱动的事项关系图谱明确B002低保优先核验、B003/B004分层转介及两者可分别认定的并行关系；关系证据、触发条件和路由结果进入API、界面与安全门，避免重复主路径。
- Policy2Rule实验室把公开政策文本编译为带原文引用的候选规则，无法识别事项时返回`unknown`，不再默认映射B001；120条文件级隔离的官方逐字条款在相同冻结集上比较确定性、纯LLM和受控融合，任何轨道都不得用元数据回填，候选规则固定不可直接发布。
- 依据《申请家庭生活状况综合评估指标（第二版）》实现独立、可审计的综合评估计算器：逐项展示D系数、就业成本上限、家庭结构与生活状况调整，缺失信息保持UNKNOWN；该模型仅适用于2026-01-01至2030-12-31，不向2025年历史查询倒灌。
- 居民端、政策证据页和可信治理看板，响应式、键盘可操作，支持大字、减少动画与打印报告。
- 面向低数字素养人群的“一步一问”关怀模式与浏览器本地朗读；同一字段和规则链路，不另造简化结论。
- 运行就绪度看板直接核验政策、证据、窗口、规则指纹、回归集、评测产物与本地AI依赖，不使用虚构评分。
- 请求ID、Server-Timing及PWA离线壳；离线缓存仅覆盖静态界面，任何API结果和群众数据都不进入缓存。
- 自动化测试覆盖政策换版、收入边界、UNKNOWN、异地拦截、文件安全和API闭环。
- 240个可重复生成的合成边界案例、两份公开演示材料，以及100张、10版式、10种质量变化的无真实信息OCR内部测试图。
- 当前所有自动评测均为团队自编合成数据或项目组标注的官方条款，不存在已完成的外部专家评测；这些结果只用于工程回归，不得表述为真实业务准确率。
- 20项政策来源均登记本地快照、项目相对路径和SHA-256；证据包22份PDF逐文件标记为现行主件、重复快照、官方辅助、历史旧版或背景材料，新增未分类PDF会阻断工程就绪。
- 应用、API、前端缓存统一版本1.4.0；依赖锁定、生产鉴权默认拒绝、Docker运行数据隔离和一键复现实验已启用。
- 46个锁定Python依赖已用`pip-audit 2.10.1`查询公开漏洞数据库，当前报告未发现已知漏洞；该结论只对应扫描时间和锁定版本，不替代持续安全维护。
- 320条项目组编写的高风险安全回归集覆盖UNKNOWN保留、政策换版、多锚点关键词夹带、合法资格关系、提示注入和候选规则发布门；它不是独立红队或真实用户测试。
- 冻结测试规模为检索120问、意图250例、画像300例、OCR 100张、Policy2Rule 120条和安全320例；主报告同时保存Wilson 95%置信区间、逐类指标与错误表。
- 真实AI压力脚本通过回环HTTP在并发1/3/5/10下分别执行LLM画像、RRF混合检索、图片OCR、多页PDF和材料包，记录P50/P95、错误率、队列拒绝率、超时率、服务进程RSS峰值与超时恢复。
- 120条合成决策路径分别真实执行动态与固定提问策略并保存逐例轨迹；当前动态平均6.75问、固定8.50问，状态一致率均为100%。减题率只适用于该内部合成集。

## 本地启动

Windows PowerShell：

```powershell
.\setup.ps1
.\start.ps1 -DemoMode
```

浏览器访问：`http://127.0.0.1:8000`

API文档：`http://127.0.0.1:8000/api/docs`

服务在后台运行，终端可直接关闭。重复执行 `start.ps1` 不会重复占用端口。常用管理命令：

```powershell
.\status.ps1          # 查看服务状态
.\logs.ps1            # 查看最近日志
.\logs.ps1 -Follow    # 持续查看日志，Ctrl+C 仅退出日志查看
.\stop.ps1            # 安全停止本项目启动的服务
```

如果8000端口被其他程序占用，可改用另一端口：

```powershell
.\start.ps1 -DemoMode -Port 8010
.\stop.ps1             # 自动读取实际启动端口
```

测试：

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe scripts\check_project.py
.\.venv\Scripts\python.exe scripts\benchmark_api.py
.\.venv\Scripts\python.exe scripts\evaluate_conformance.py
.\.venv\Scripts\python.exe scripts\evaluate_retrieval.py
.\.venv\Scripts\python.exe scripts\evaluate_policy_compiler.py
.\.venv\Scripts\python.exe scripts\build_stage2_benchmarks.py
.\.venv\Scripts\python.exe scripts\evaluate_ocr.py
.\.venv\Scripts\python.exe scripts\benchmark_ai_workloads.py
.\.venv\Scripts\python.exe scripts\build_expert_packet.py
```

完整质量与安全门禁（Ruff、Mypy、分支覆盖率、Bandit、Semgrep、密钥扫描、依赖漏洞审计）：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-quality.txt
.\scripts\run_quality_gates.ps1
```

Windows上若原生Semgrep引擎因平台或路径问题不可用，脚本会明确警告并运行同规则AST检查；
这不等于Semgrep通过。Linux CI必须运行原生Semgrep，正式竞赛包还会使用`-RequireNativeSemgrep`拒绝降级。

只复现本次完成的第一、二阶段（不运行真人试点和正式参赛材料）：

```powershell
.\reproduce_phase12.ps1
```

项目目前没有开展外部专家评测，也没有可计分的独立专家金标。下列工具只为未来真实评测预留，必须由可核验的评审人员独立填写后才能生成结果：

```powershell
.\.venv\Scripts\python.exe scripts\merge_expert_reviews.py
.\.venv\Scripts\python.exe scripts\evaluate_expert_gold.py
.\.venv\Scripts\python.exe scripts\analyze_pilot.py
```

这些脚本不能把团队自标、系统输出或合成标签包装为外部专家结论。没有评审人员身份、原始表、时间记录和独立性说明时，不生成也不引用专家准确率。

Docker：

```powershell
docker compose up --build
```

## 可选本地大模型

先安装 Ollama，再拉取本项目冻结的两套 Apache-2.0 模型：

```powershell
ollama pull qwen3:4b-instruct
ollama pull qwen3-embedding:0.6b
```

若 Windows 混合显卡设备执行 `ollama ps` 显示 `100% CPU`，可由项目脚本安全重启本项目使用的 Ollama 后端。本机 RTX 4060 + 610.78 驱动实测使用 `cuda_v12`：

```powershell
.\start-ai-runtime.ps1 -Backend cuda_v12 -ForceRestart
```

脚本只终止安装目录位于当前用户 Ollama 目录下的 `ollama`/`llama-server` 进程，并把日志写入 `storage`；其他机器应先使用默认 `auto`，不要盲目固定后端。

直接执行 `./start.ps1` 时，脚本会探测本机模型：两套模型齐全则启用 `hybrid`，只有对话模型则启用 `ollama`，不可用则安全回到 `deterministic`。也可显式指定：

```powershell
$env:AI_MODE='hybrid'
$env:OLLAMA_MODEL='qwen3:4b-instruct'
$env:OLLAMA_EMBED_MODEL='qwen3-embedding:0.6b'
$env:OLLAMA_TIMEOUT_SECONDS='120'
.\start.ps1 -DemoMode -AIMode hybrid
.\.venv\Scripts\python.exe scripts\verify_live_ai.py
```

大模型只把口语转换成家庭画像草稿并增强政策召回；字段仍需用户确认，最终资格由确定性规则引擎执行。模型未安装或运行失败时，接口与实验报告会显示真实降级状态，不得宣称语言模型或向量检索已实际启用。
默认只允许连接`127.0.0.1`、`localhost`、`::1`或容器访问宿主机所需的`host.docker.internal`，避免把群众自述误发到外部模型服务。确需使用受控远程服务时，必须在完成传输加密、访问控制和隐私评估后显式设置`ALLOW_REMOTE_OLLAMA=true`。

正式技术包使用硬发布门；它要求干净Git状态、全部质量门、Linux/本机可用的原生Semgrep以及真实对话/向量推理证据：

```powershell
.\scripts\build_release.ps1 -CompetitionRelease
```

OCR默认在依赖可用时启用。如设备资源有限，可在启动前设置 `$env:OCR_ENABLED='false'` 安全降级为图像质量和文件名提示；界面会如实显示OCR未启用。

治理端只有显式传入`-DemoMode`或`DEMO_MODE=true`时才免令牌。非演示环境默认拒绝无鉴权启动；正式运行示例：

```powershell
$env:ADMIN_API_TOKEN='请换成长随机字符串'
$env:DATA_RETENTION_DAYS='30'
.\start.ps1
```

## 工程结构

```text
app/
  domain/          Pydantic领域模型
  repositories/    SQLite持久化与审计
  services/        时态选择、规则引擎、解析、检索、材料预检
  static/          无外部CDN的居民端与治理端
data/
  raw_official/    政府官网原始文件
  processed/       政策、事项和窗口目录
  schemas/         家庭画像和时态规则JSON Schema
tests/             单元与API测试
scripts/           数据/工程一致性检查
demo_assets/       可公开演示的合成材料
政策证据包/        官方政策PDF及证据清单
```

## 当前边界

- 资格预筛规则只覆盖广州首版MVP，不得直接迁移到其他城市。
- 刚性支出困难家庭按已核验的60%刚性支出比例和2025年广州城镇居民人均可支配收入86069元做2026年度预筛；支出范围、收入扣减和财产状况仍须官方核验，其他年度缺参数时自动转人工。
- 当前图片与PDF逐页使用本地RapidOCR/ONNX Runtime做内容分类和日期、金额候选抽取；材料包会提示跨文件日期/金额差异。姓名/证件字段不提取，OCR结果不得用于认定材料真伪。
- 当前默认证据检索为真实的离线字段加权BM25；只有API返回`rrf(bm25,local-embedding)`且实验报告记录模型时，才可宣称语义向量召回已启用。
- 词法与语义检索共用同一不可绕过领域门；领域拒绝发生在嵌入模型调用之前，并有提示注入与关键词夹带回归测试。
- LLM、语义嵌入、OCR和PDF解析均运行在有界工作线程中；队列满、单任务超时、材料包总大小/总页数/总耗时都会显式拒绝。线程任务超时后会尝试取消；已经开始的底层调用受自身网络/处理超时约束，完成后释放容量，运行状态会记录超时与取消计数。
- 当前Policy2Rule是候选规则编译与影响分析管线；没有完成双人复核、签名和发布审批前，不会写入正式规则登记表。
- 管理端是竞赛原型治理看板；生产环境还需统一身份认证、RBAC、HTTPS、密钥管理、备份和正式安全测评。
- 目前保存的是政府公开政策语料与合成/演示输入，不包含真实困难群众敏感训练数据。
- `data/processed` 下的CSV使用UTF-8 BOM编码，可由中文版Excel直接双击打开；请勿另存为ANSI编码。

运行、复现与安全边界以本说明、[复现说明](./REPRODUCIBILITY.md)、[安全边界](./SECURITY.md)和[模型与许可证说明](./MODEL_LICENSES.md)为准。

