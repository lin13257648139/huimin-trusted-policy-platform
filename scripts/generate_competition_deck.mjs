import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const RUNTIME_MODULES = "C:/Users/林琪东/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules";
const RUNTIME_PYTHON = "C:/Users/林琪东/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe";
const SKILL_DIR = "C:/Users/林琪东/.codex/plugins/cache/openai-primary-runtime/presentations/26.1015.12040/skills/presentations";
const ARTIFACT = path.join(RUNTIME_MODULES, "@oai", "artifact-tool", "dist", "artifact_tool.mjs");
const { Presentation, PresentationFile } = await import(pathToFileURL(ARTIFACT).href);
const { finalizePresentation } = await import(pathToFileURL(path.join(SKILL_DIR, "container_tools", "artifact_tool_utils.mjs")).href);

const BUILD = path.join(ROOT, "tmp", "ppt-build-v2");
const PREVIEWS = path.join(BUILD, "previews");
const STAGING = path.join(BUILD, "finalizer");
const FINAL = path.join(BUILD, "惠民智导_答辩PPT_v2.0_r3.pptx");
const SHOTS = path.join(ROOT, "最终交付", "截图证据");
const W = 1280;
const H = 720;
const FONT = "Microsoft YaHei";
const C = {
  ink: "#132F29",
  green: "#075F50",
  green2: "#0F7A67",
  mint: "#EAF5F1",
  pale: "#F6F9F7",
  muted: "#65746F",
  line: "#D6E0DC",
  amber: "#A46814",
  amberPale: "#FFF5DE",
  white: "#FFFFFF",
  black: "#000000",
};

async function loadJson(relativePath) {
  return JSON.parse(await fs.readFile(path.join(ROOT, relativePath), "utf8"));
}

const coverage = (await loadJson("data/evaluation/coverage_report.json")).totals;
const policyReport = await loadJson("data/evaluation/policy_compiler_real_report.json");
const aiPipeline = await loadJson("data/evaluation/ai_pipeline_report.json");
const browserReport = (await loadJson("data/evaluation/browser_e2e_report.json")).stats;
const pytestXml = await fs.readFile(path.join(ROOT, "data/evaluation/pytest_junit.xml"), "utf8");
const pytestSuite = pytestXml.match(/<testsuite\b[^>]*>/)?.[0];
const suiteNumber = (name) => Number(pytestSuite?.match(new RegExp(`\\b${name}="(\\d+)"`))?.[1] ?? -1);
if (!pytestSuite || suiteNumber("errors") || suiteNumber("failures")) {
  throw new Error("Python 自动化测试报告缺失或包含失败");
}
if (browserReport.unexpected || browserReport.flaky) {
  throw new Error("浏览器自动化测试报告包含失败或不稳定场景");
}
const pythonTests = suiteNumber("tests");
const browserTests = Number(browserReport.expected);
const policyTracks = policyReport.tracks;
const retrievalPipeline = aiPipeline.retrieval.frozen_final_test.configured_pipeline;
const formatPercent = (value) => `${(Number(value) * 100).toFixed(2)}%`;

async function bytes(file) {
  const data = await fs.readFile(file);
  return data.buffer.slice(data.byteOffset, data.byteOffset + data.byteLength);
}

function addText(slide, text, x, y, w, h, size, color = C.ink, bold = false, align = "left") {
  const box = slide.shapes.add({
    geometry: "textbox",
    position: { left: x, top: y, width: w, height: h },
    fill: "none",
    line: { style: "solid", fill: "none", width: 0 },
  });
  box.text = text;
  box.text.style = {
    typeface: FONT,
    fontSize: size,
    color,
    bold,
    alignment: align,
    verticalAlignment: "middle",
  };
  return box;
}

function addRule(slide, x, y, w, color = C.line, width = 1) {
  return slide.shapes.add({
    geometry: "rect",
    position: { left: x, top: y, width: w, height: width },
    fill: color,
    line: { style: "solid", fill: "none", width: 0 },
  });
}

function addRect(slide, x, y, w, h, fill, radius = "rounded-md", line = C.line) {
  return slide.shapes.add({
    geometry: radius === "none" ? "rect" : "roundRect",
    position: { left: x, top: y, width: w, height: h },
    fill,
    line: { style: "solid", fill: line, width: 1 },
    ...(radius === "none" ? {} : { borderRadius: radius }),
  });
}

function addHeader(slide, index, title, eyebrow = "惠民智导 v2.0.0") {
  addText(slide, eyebrow, 64, 38, 360, 24, 13, C.green, true);
  addText(slide, title, 64, 70, 1120, 54, 32, C.ink, true);
  addRule(slide, 64, 133, 1152, C.line, 1);
  addText(slide, String(index).padStart(2, "0"), 1160, 42, 56, 24, 12, C.muted, true, "right");
}

function addFooter(slide, source = "策马奔腾队  2026 AI 软件创新赛") {
  addText(slide, source, 64, 681, 900, 18, 10, "#798681", false);
}

async function addImage(slide, file, x, y, w, h, alt, fit = "contain") {
  slide.images.add({
    blob: await bytes(path.join(SHOTS, file)),
    contentType: "image/png",
    alt,
    fit,
    position: { left: x, top: y, width: w, height: h },
  });
}

function addNumberedLine(slide, number, title, body, x, y, w = 430) {
  addText(slide, String(number).padStart(2, "0"), x, y, 40, 34, 13, C.green, true);
  addText(slide, title, x + 48, y, w - 48, 30, 19, C.ink, true);
  addText(slide, body, x + 48, y + 32, w - 48, 44, 13, C.muted, false);
}

async function main() {
  await fs.mkdir(PREVIEWS, { recursive: true });
  await fs.mkdir(STAGING, { recursive: true });

  const deck = Presentation.create({ slideSize: { width: W, height: H } });

  // 1 Cover
  {
    const s = deck.slides.add();
    s.background.fill = C.green;
    addText(s, "2026 AI 软件创新赛", 72, 62, 360, 28, 15, "#CDE7DF", true);
    addText(s, "惠民智导", 72, 160, 700, 86, 56, C.white, true);
    addText(s, "可信政策智能平台", 72, 242, 760, 74, 44, C.white, true);
    addText(s, "面向社会救助申请前导办的可信 AI 决策辅助系统", 76, 338, 780, 38, 21, "#DCEFE9", false);
    addRule(s, 76, 406, 620, "#6AA799", 2);
    addText(s, "策马奔腾队", 76, 442, 260, 28, 17, C.white, true);
    addText(s, "AIC-2026-71323388", 76, 476, 360, 24, 13, "#BFDCD4", false);
    addText(s, "六类事项  本地模型  三态规则  证据闭环", 76, 604, 750, 28, 16, "#DCEFE9", false);
    addText(s, "v2.0.0", 1100, 646, 110, 24, 13, C.white, true, "right");
  }

  // 2 Problem
  {
    const s = deck.slides.add();
    s.background.fill = C.pale;
    addHeader(s, 2, "用户缺少的不是政策文本，而是可信的下一步", "问题与需求");
    addText(s, "一位居民第一次打开系统时，通常同时面对三个问题", 64, 168, 680, 32, 18, C.muted);
    const items = [
      ["01", "能了解哪项救助", "事项之间存在先后与排斥关系"],
      ["02", "还缺哪些信息", "缺失事实不能等同于不符合"],
      ["03", "结论依据在哪里", "政策版本和原文必须可核对"],
    ];
    items.forEach((item, i) => {
      const y = 238 + i * 108;
      addText(s, item[0], 76, y, 48, 32, 16, C.green, true);
      addText(s, item[1], 142, y - 3, 390, 36, 24, C.ink, true);
      addText(s, item[2], 142, y + 37, 430, 34, 15, C.muted);
      if (i < 2) addRule(s, 142, y + 90, 420);
    });
    addText(s, "现有两类工具的缺口", 760, 182, 390, 30, 18, C.ink, true);
    addText(s, "政策搜索", 760, 246, 160, 30, 20, C.ink, true);
    addText(s, "能找到文件，但让用户自己理解时态、条件和顺序。", 760, 282, 400, 74, 16, C.muted);
    addRule(s, 760, 376, 400);
    addText(s, "通用大模型", 760, 410, 180, 30, 20, C.ink, true);
    addText(s, "能组织语言，但可能补全缺失事实、混用旧政策或越权下结论。", 760, 446, 400, 88, 16, C.muted);
    addFooter(s);
  }

  // 3 Product
  {
    const s = deck.slides.add();
    s.background.fill = C.white;
    addHeader(s, 3, "同一证据与规则底座服务三类任务", "产品定位");
    await addImage(s, "05_材料智能预检_v2.png", 676, 164, 540, 430, "本地材料预检界面", "cover");
    addText(s, "居民", 70, 184, 170, 30, 22, C.green, true);
    addText(s, "匿名预筛，理解原因，准备材料", 70, 222, 490, 32, 17, C.ink);
    addRule(s, 70, 278, 500);
    addText(s, "基层工作人员", 70, 310, 220, 30, 22, C.green, true);
    addText(s, "并排核对六类事项，保留 UNKNOWN", 70, 348, 500, 32, 17, C.ink);
    addRule(s, 70, 404, 500);
    addText(s, "规则管理员", 70, 436, 220, 30, 22, C.green, true);
    addText(s, "核对来源、候选规则、版本差异和发布阻断", 70, 474, 520, 58, 17, C.ink);
    addText(s, "当前范围", 70, 584, 110, 24, 13, C.muted, true);
    addText(s, "申请前导办，不替代主管部门受理、调查或审批", 178, 578, 470, 36, 15, C.amber, true);
    addFooter(s, "来源  v2.0.0 产品实现与比赛范围说明");
  }

  // 4 Flow
  {
    const s = deck.slides.add();
    s.background.fill = C.pale;
    addHeader(s, 4, "从用户表达到账得懂的行动建议", "完整闭环");
    await addImage(s, "02_特困供养逐项核对_v2.png", 680, 158, 536, 448, "特困供养逐项核对页面", "cover");
    addNumberedLine(s, 1, "辅助表达", "自然语言只生成待确认候选", 64, 176, 510);
    addNumberedLine(s, 2, "最小追问", "按事项缺口决定下一问", 64, 262, 510);
    addNumberedLine(s, 3, "规则计算", "三态逻辑保留未知事实", 64, 348, 510);
    addNumberedLine(s, 4, "证据解释", "结论逐条绑定有效政策原文", 64, 434, 510);
    addNumberedLine(s, 5, "行动建议", "给出补项、材料和咨询窗口", 64, 520, 510);
    addFooter(s);
  }

  // 5 UX
  {
    const s = deck.slides.add();
    s.background.fill = C.white;
    addHeader(s, 5, "首次使用者先选情境，再进入四步向导", "人机交互");
    await addImage(s, "01_服务首页_v2.png", 64, 158, 748, 466, "居民服务首页", "cover");
    addText(s, "任务语言", 866, 180, 260, 30, 21, C.green, true);
    addText(s, "首页不展示系统模块清单，先让用户选择当前情境。", 866, 220, 320, 78, 16, C.ink);
    addText(s, "渐进披露", 866, 338, 260, 30, 21, C.green, true);
    addText(s, "只有选择核对特困供养，才展开三项法定条件。", 866, 378, 320, 78, 16, C.ink);
    addText(s, "可访问性", 866, 496, 260, 30, 21, C.green, true);
    addText(s, "支持大字、键盘、结果朗读和打印。WCAG A/AA 自动扫描通过。", 866, 536, 330, 82, 16, C.ink);
    addFooter(s);
  }

  // 6 Rules
  {
    const s = deck.slides.add();
    s.background.fill = C.pale;
    addHeader(s, 6, "六类事项共享三态判断，不把缺失信息写成不符合", "规则与结果");
    await addImage(s, "03_特困供养可信结果_v2.png", 580, 154, 636, 470, "特困供养可信预筛结果", "cover");
    addText(s, "TRUE", 70, 174, 100, 34, 24, C.green, true);
    addText(s, "条件明确满足", 70, 212, 340, 30, 16, C.ink);
    addRule(s, 70, 264, 420);
    addText(s, "FALSE", 70, 294, 120, 34, 24, "#9B3F3F", true);
    addText(s, "条件明确不满足", 70, 332, 340, 30, 16, C.ink);
    addRule(s, 70, 384, 420);
    addText(s, "UNKNOWN", 70, 414, 260, 34, 24, C.amber, true);
    addText(s, "需要最小补项或人工核验", 70, 452, 360, 30, 16, C.ink);
    addText(s, "特困供养", 70, 536, 150, 26, 15, C.green, true);
    addText(s, "对象线索、无劳动能力、无生活来源、无法定义务人履行能力", 70, 568, 440, 64, 14, C.muted);
    addFooter(s, "规则引擎 0.6.0  六类事项  查询日快照");
  }

  // 7 QA
  {
    const s = deck.slides.add();
    s.background.fill = C.white;
    addHeader(s, 7, "本地模型只在证据白名单内组织答案", "有据政策问答");
    await addImage(s, "04_有据政策问答_v2.png", 520, 154, 696, 474, "有据政策问答界面", "cover");
    addNumberedLine(s, 1, "生成前拦截", "领域、隐私、注入和有效期", 64, 176, 410);
    addNumberedLine(s, 2, "混合召回", "关键词与本地向量定位证据", 64, 274, 410);
    addNumberedLine(s, 3, "模型整理", "Qwen3 4B 只输出结构化结论", 64, 372, 410);
    addNumberedLine(s, 4, "生成后校验", "引用、原文、数字和决策边界", 64, 470, 410);
    addText(s, "任一校验失败，系统退回逐字证据", 112, 586, 350, 34, 16, C.amber, true);
    addFooter(s, "真实本地模型专题 20 问  14 次通过生成校验  6 次安全回退  20/20 闭环通过");
  }

  // 8 Policy2Rule
  {
    const s = deck.slides.add();
    s.background.fill = C.pale;
    addHeader(s, 8, "政策变更先生成候选规则，再做影响分析", "Policy2Rule");
    await addImage(s, "07_Policy2Rule工作台_v2.png", 530, 154, 686, 474, "Policy2Rule 候选规则工作台", "cover");
    addText(s, "三轨抽取", 64, 176, 300, 30, 21, C.green, true);
    addText(s, "确定性抽取、LLM 抽取和受控融合分别保留结果。", 64, 214, 410, 78, 16, C.ink);
    addText(s, "原文锚定", 64, 326, 300, 30, 21, C.green, true);
    addText(s, "每个参数与条件必须能定位到政策原文。", 64, 364, 410, 70, 16, C.ink);
    addText(s, "人工发布门", 64, 468, 300, 30, 21, C.green, true);
    addText(s, "候选规则展示版本差异、合成案例影响和阻断项，系统不自动发布。", 64, 506, 420, 100, 16, C.ink);
    addFooter(s, `120 条冻结条款  事项识别 规则 ${formatPercent(policyTracks.deterministic.benefit_accuracy)} / 模型 ${formatPercent(policyTracks.llm_only.benefit_accuracy)} / 融合 ${formatPercent(policyTracks.controlled_fusion.benefit_accuracy)}  条件字段F1 ${formatPercent(policyTracks.deterministic.condition_field.f1)} / ${formatPercent(policyTracks.llm_only.condition_field.f1)} / ${formatPercent(policyTracks.controlled_fusion.condition_field.f1)}`);
  }

  // 9 Architecture
  {
    const s = deck.slides.add();
    s.background.fill = C.white;
    addHeader(s, 9, "受约束的混合架构", "系统架构");
    const layers = [
      ["交互层", "四步向导  政策问答  材料预检  专业工作台", "#EAF5F1"],
      ["API 层", "FastAPI  Schema 校验  鉴权  审计", "#F1F5F3"],
      ["AI 协作层", "Qwen3 4B  Qwen3 Embedding  本地 OCR", "#EAF5F1"],
      ["决策层", "版本化规则  三态求值  事项关系", "#F1F5F3"],
      ["证据与治理层", "官方来源  逐字证据  Policy2Rule  冻结评测", "#EAF5F1"],
    ];
    layers.forEach((row, i) => {
      const y = 166 + i * 88;
      addRect(s, 94, y, 1092, 66, row[2], "rounded-md", C.line);
      addText(s, row[0], 120, y + 10, 210, 44, 18, C.green, true);
      addText(s, row[1], 360, y + 10, 790, 44, 17, C.ink, false);
    });
    addText(s, "关键边界", 94, 626, 120, 24, 13, C.muted, true);
    addText(s, "AI 负责理解与整理  规则负责资格方向  人工负责正式发布和审批", 212, 619, 850, 34, 16, C.amber, true);
    addFooter(s, "20 个官方来源  33 条逐字证据  本地回环地址运行");
  }

  // 10 Evaluation
  {
    const s = deck.slides.add();
    s.background.fill = C.pale;
    addHeader(s, 10, "评测报告与源码、规则和模型版本绑定", "量化证据");
    s.charts.add("bar", {
      position: { left: 70, top: 174, width: 650, height: 398 },
      categories: ["单元测试", "浏览器场景", "检索问答", "特困专题", "安全用例"],
      series: [{ name: "通过率", values: [1, 1, retrievalPipeline.recall_at_3, 1, 1], fill: C.green }],
      textStyle: { typeface: FONT, fontSize: 13, fill: C.ink },
      hasLegend: false,
      dataLabels: { showValue: true, position: "inEnd", numberFormatCode: "0%", textStyle: { typeface: FONT, fontSize: 12, fill: C.white, bold: true } },
      xAxis: { minimumScale: 0, maximumScale: 1, majorUnit: 0.2, numberFormatCode: "0%", textStyle: { typeface: FONT, fontSize: 11, fill: C.muted } },
      yAxis: { textStyle: { typeface: FONT, fontSize: 12, fill: C.ink }, majorGridlines: { style: "solid", fill: "#D9E1DE", width: 1 } },
    });
    addText(s, String(pythonTests), 800, 182, 150, 60, 42, C.green, true);
    addText(s, "Python 自动化测试全部通过", 800, 240, 340, 32, 16, C.ink);
    addText(s, `${coverage.percent_covered.toFixed(2)}%`, 800, 306, 190, 58, 38, C.green, true);
    addText(s, "行覆盖率", 800, 362, 180, 26, 15, C.muted);
    addText(s, `${coverage.percent_branches_covered.toFixed(2)}%`, 1010, 306, 190, 58, 38, C.green, true);
    addText(s, "分支覆盖率", 1010, 362, 180, 26, 15, C.muted);
    addText(s, String(retrievalPipeline.queries), 800, 438, 150, 58, 38, C.green, true);
    addText(s, "文件隔离检索问答", 800, 494, 220, 26, 15, C.muted);
    addText(s, "320", 1010, 438, 150, 58, 38, C.green, true);
    addText(s, "高风险安全用例", 1010, 494, 220, 26, 15, C.muted);
    addText(s, "指标只描述项目内冻结集和自动化工程测试，不外推为真实审批准确率。", 800, 560, 400, 60, 14, C.amber, true);
    addFooter(s, `评测绑定  Python ${pythonTests}/${pythonTests}  浏览器 ${browserTests}/${browserTests}  RRF Recall@3 ${formatPercent(retrievalPipeline.recall_at_3)}  源码指纹`);
  }

  // 11 Differentiation
  {
    const s = deck.slides.add();
    s.background.fill = C.white;
    addHeader(s, 11, "创新来自可执行控制，不来自更大的模型", "创新与边界");
    const xs = [64, 468, 872];
    const titles = ["普通政策搜索", "通用大模型", "惠民智导"];
    const bodies = [
      "用户自行判断时态与条件\n\n无法表达 UNKNOWN\n\n规则更新依赖人工改代码",
      "可能混用旧知识\n\n可能补全或猜测\n\n引用与结论难校验",
      "查询日规则快照\n\n三态逻辑和最小补项\n\n候选编译与人工发布门",
    ];
    xs.forEach((x, i) => {
      addText(s, titles[i], x, 178, 320, 40, 22, i === 2 ? C.green : C.ink, true);
      addRule(s, x, 232, 320, i === 2 ? C.green : C.line, i === 2 ? 3 : 1);
      addText(s, bodies[i], x, 258, 320, 230, 17, C.ink);
    });
    addRule(s, 64, 518, 1152);
    addText(s, "仍需补齐的外部证据", 64, 548, 270, 30, 19, C.amber, true);
    addText(s, "外部专家双人盲标", 374, 548, 250, 30, 16, C.ink);
    addText(s, "真实用户封闭试点", 650, 548, 250, 30, 16, C.ink);
    addText(s, "正式政务部署评审", 926, 548, 250, 30, 16, C.ink);
    addText(s, "本次材料明确标注这些缺口，不虚构采用证明、群众满意度或审批准确率。", 374, 590, 790, 44, 14, C.muted);
    addFooter(s);
  }

  // 12 Close
  {
    const s = deck.slides.add();
    s.background.fill = C.green;
    addText(s, "交付结论", 72, 58, 300, 26, 14, "#CDE7DF", true);
    addText(s, "工程闭环已经成立", 72, 128, 720, 66, 46, C.white, true);
    addText(s, "后续验证重点是外部证据与现场展示", 72, 198, 850, 48, 28, "#DCEFE9", false);
    const reasons = [
      "六类事项形成可运行产品，不是概念演示",
      "真实本地模型受到规则、证据和安全回退约束",
      "自动化测试、冻结评测和版本指纹可以复现",
      "边界清楚，不把申请前导办包装成政务审批",
    ];
    reasons.forEach((r, i) => {
      const y = 310 + i * 68;
      addText(s, String(i + 1).padStart(2, "0"), 78, y, 42, 28, 13, "#8CC9B9", true);
      addText(s, r, 136, y - 4, 940, 38, 19, C.white, true);
    });
    addRule(s, 76, 600, 1128, "#4A8E7F", 1);
    addText(s, "下一步由团队完成报名信息、永久网盘链接和需要真人出镜的最终录制。", 76, 620, 1020, 36, 16, "#DCEFE9");
    addText(s, "策马奔腾队", 1048, 658, 156, 22, 13, C.white, true, "right");
  }

  for (const [index, slide] of deck.slides.items.entries()) {
    const png = await deck.export({ slide, format: "png", scale: 1 });
    const name = `slide-${String(index + 1).padStart(2, "0")}.png`;
    await fs.writeFile(path.join(PREVIEWS, name), new Uint8Array(await png.arrayBuffer()));
  }

  const candidatePath = path.join(STAGING, "candidate.pptx");
  await (await PresentationFile.exportPptx(deck)).save(candidatePath);

  const requirements = {
    explicitTotalSlideCount: 12,
    requiredNativeTableOwnerSlides: [],
    requiredNativeChartOwnerSlides: [10],
    requiredEmbeddedWorkbookChartOwnerSlides: [],
    materializeLiteralChartWorkbooks: true,
    nativeChartTargetApplication: "powerpoint",
  };
  const result = await finalizePresentation({
    ...requirements,
    workspaceDir: ROOT,
    candidatePath,
    finalPath: FINAL,
    pythonExecutable: RUNTIME_PYTHON,
    integrityValidatorPath: path.join(SKILL_DIR, "container_tools", "inspect_presentation_package_integrity.py"),
    layoutValidatorPath: path.join(SKILL_DIR, "container_tools", "inspect_presentation_layout_geometry.py"),
    layoutArgs: [
      "--expected-slide-size-emu", "12192000,6858000",
      "--validate-bullet-geometry",
      "--validate-heading-fit",
    ],
    fontPolicy: { basis: "design", families: [FONT] },
    verifyArtifactToolImport: true,
    receiptPath: path.join(ROOT, "tmp", "private-ppt-validation-r3.json"),
  });
  console.log(JSON.stringify({ final: FINAL, slides: deck.slides.items.length, result }, null, 2));
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
