import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { Presentation, PresentationFile } from "@oai/artifact-tool";

const { SKILL_DIR, TMP_DIR, WORKSPACE_DIR, FINAL_PPTX, RUNTIME_PYTHON } = process.env;
for (const [name, value] of Object.entries({ SKILL_DIR, TMP_DIR, WORKSPACE_DIR, FINAL_PPTX, RUNTIME_PYTHON })) {
  if (!value || !path.isAbsolute(value)) throw new Error(`${name} must be an absolute path`);
}

const { resolvePresentationFont, applyPresentationChartFont, finalizePresentation } = await import(
  pathToFileURL(path.join(SKILL_DIR, "container_tools/artifact_tool_utils.mjs")).href,
);

await fs.mkdir(TMP_DIR, { recursive: true });
await fs.mkdir(path.dirname(FINAL_PPTX), { recursive: true });
const family = resolvePresentationFont();

const W = 1280;
const H = 720;
const C = {
  ink: "#0F2942",
  teal: "#0D9488",
  mint: "#DDF5F0",
  cyan: "#E8F2F8",
  amber: "#F5B942",
  amberBg: "#FFF4D6",
  red: "#C43C35",
  gray: "#526273",
  line: "#D7E0E8",
  soft: "#F5F8FA",
  white: "#FFFFFF",
  dark: "#071A1D",
};

const deck = Presentation.create({ slideSize: { width: W, height: H } });

function shape(slide, geometry, x, y, w, h, fill = "none", line = "none", radius = undefined, name = undefined) {
  return slide.shapes.add({
    geometry,
    name,
    position: { left: x, top: y, width: w, height: h },
    fill,
    line: { style: "solid", fill: line, width: line === "none" ? 0 : 1 },
    ...(radius ? { borderRadius: radius } : {}),
  });
}

function textBox(slide, text, x, y, w, h, opts = {}) {
  const s = shape(slide, "textbox", x, y, w, h, opts.fill ?? "none", opts.line ?? "none", opts.radius, opts.name);
  s.text = text;
  s.text.style = {
    typeface: family,
    fontSize: opts.size ?? 24,
    bold: opts.bold ?? false,
    color: opts.color ?? C.ink,
    alignment: opts.align ?? "left",
    verticalAlignment: opts.valign ?? "top",
    autoFit: opts.autoFit ?? "shrinkText",
    wrap: "square",
    insets: opts.insets ?? { left: 8, right: 8, top: 4, bottom: 4 },
  };
  return s;
}

function rule(slide, x, y, w, color = C.line, height = 2) {
  return shape(slide, "rect", x, y, w, height, color, "none");
}

function baseSlide(kicker, title, number) {
  const slide = deck.slides.add();
  slide.background.fill = C.white;
  shape(slide, "rect", 0, 0, 14, H, C.teal, "none");
  textBox(slide, kicker.toUpperCase(), 64, 36, 400, 28, { size: 13, bold: true, color: C.teal });
  textBox(slide, title, 64, 68, 1060, 62, { size: 34, bold: true, color: C.ink });
  rule(slide, 64, 138, 1152, C.line, 1);
  textBox(slide, String(number).padStart(2, "0"), 1160, 36, 56, 28, { size: 13, bold: true, color: C.gray, align: "right" });
  textBox(slide, "惠民智导 · 可信政策智能软件平台", 64, 682, 500, 22, { size: 11, color: C.gray });
  textBox(slide, "策马奔腾", 1030, 682, 186, 22, { size: 11, color: C.gray, align: "right" });
  return slide;
}

function card(slide, x, y, w, h, title, body, opts = {}) {
  const bg = shape(slide, "roundRect", x, y, w, h, opts.fill ?? C.soft, opts.line ?? C.line, "rounded-xl");
  if (opts.accent) shape(slide, "roundRect", x, y, 8, h, opts.accent, "none", "rounded-full");
  textBox(slide, title, x + 22, y + 18, w - 44, 34, { size: opts.titleSize ?? 19, bold: true, color: opts.titleColor ?? C.ink });
  textBox(slide, body, x + 22, y + 58, w - 44, h - 72, { size: opts.bodySize ?? 14, color: opts.bodyColor ?? C.gray });
  return bg;
}

function metric(slide, x, y, w, label, value, note, color = C.teal) {
  shape(slide, "roundRect", x, y, w, 132, C.white, C.line, "rounded-xl");
  textBox(slide, label, x + 16, y + 14, w - 32, 24, { size: 13, bold: true, color: C.gray });
  textBox(slide, value, x + 16, y + 42, w - 32, 48, { size: 30, bold: true, color });
  textBox(slide, note, x + 16, y + 96, w - 32, 24, { size: 11, color: C.gray });
}

function pill(slide, text, x, y, w, fill = C.mint, color = C.teal) {
  return textBox(slide, text, x, y, w, 34, { size: 13, bold: true, color, fill, line: "none", radius: "rounded-full", align: "center", valign: "middle", insets: { left: 10, right: 10, top: 2, bottom: 2 } });
}

function addNotes(slide, note) {
  slide.speakerNotes.textFrame.setText(note);
}

// 1 Cover
{
  const slide = deck.slides.add();
  slide.background.fill = C.dark;
  shape(slide, "ellipse", 900, -160, 480, 480, "#0F4A49", "none");
  shape(slide, "ellipse", 1010, -55, 240, 240, C.teal, "none");
  shape(slide, "rect", 64, 74, 84, 8, C.teal, "none");
  textBox(slide, "惠民智导", 64, 118, 900, 92, { size: 58, bold: true, color: C.white });
  textBox(slide, "可信政策智能软件平台", 64, 214, 940, 74, { size: 38, bold: true, color: "#CDEFEA" });
  textBox(slide, "模型理解 · 规则裁决 · 原文举证 · 人工发布", 66, 318, 900, 42, { size: 22, color: "#B7C7D4" });
  pill(slide, "AI + 软件创新", 66, 404, 180, "#143D42", "#92E6D8");
  pill(slide, "社会救助深度验证", 260, 404, 220, "#143D42", "#92E6D8");
  textBox(slide, "策马奔腾  ·  广州软件学院  ·  V0.7.1", 66, 590, 850, 28, { size: 15, color: "#9EB2C1" });
  textBox(slide, "队长 林琪东    队员 罗晓蓝    RTX 4060 单机本地运行", 66, 622, 900, 28, { size: 13, color: "#7F98A6" });
  textBox(slide, "可信不是口号，而是每个结论都能回到证据。", 760, 542, 450, 66, { size: 23, bold: true, color: C.white, align: "right" });
  addNotes(slide, "开场：这是一个面向高风险政策服务的可信政策智能软件平台，社会救助是第一个深度验证场景。控制在20秒。数据均来自项目仓库。 ");
}

// 2 Pain
{
  const slide = baseSlide("WHY", "政策服务不是“搜到答案”这么简单", 2);
  card(slide, 64, 184, 350, 356, "群众端", "术语难懂\n条件繁多\n材料不清\n不知道当前适用哪一版", { accent: C.teal, fill: C.mint, titleSize: 24, bodySize: 20 });
  card(slide, 465, 184, 350, 356, "经办端", "重复问询\n信息缺失\n口径更新不一致\n错误传播成本高", { accent: C.amber, fill: C.amberBg, titleSize: 24, bodySize: 20 });
  card(slide, 866, 184, 350, 356, "治理端", "政策转规则慢\n变更影响不可见\n新旧版本易混用\n模型可能自信编造", { accent: C.red, fill: "#FBE9E7", titleSize: 24, bodySize: 20 });
  textBox(slide, "核心矛盾：政策持续变化，但导办必须可解释、可追溯、可拒答。", 64, 578, 1152, 58, { size: 25, bold: true, color: C.ink, align: "center", valign: "middle" });
  addNotes(slide, "问题不是缺一个聊天框，而是缺一条把政策版本、信息缺失、原文证据和人工责任连接起来的可信链路。 ");
}

// 3 Thesis
{
  const slide = baseSlide("POSITIONING", "我们把导办升级为可信政策智能内核", 3);
  textBox(slide, "受约束神经符号架构", 64, 170, 660, 58, { size: 38, bold: true, color: C.teal });
  textBox(slide, "让模型进入高价值理解环节，但不让模型越权裁决。", 64, 236, 720, 42, { size: 21, color: C.gray });
  const steps = [
    ["1", "模型理解", "意图、事实、条款候选"],
    ["2", "规则裁决", "时态规则 + 三值逻辑"],
    ["3", "原文举证", "逐字引文 + 来源哈希"],
    ["4", "人工发布", "影响分析 + 双审门"],
  ];
  steps.forEach((d, i) => {
    const x = 64 + i * 286;
    shape(slide, "roundRect", x, 338, 250, 190, i === 0 ? C.mint : C.soft, C.line, "rounded-xl");
    pill(slide, d[0], x + 18, 356, 42, i === 0 ? C.teal : C.ink, C.white);
    textBox(slide, d[1], x + 18, 408, 214, 34, { size: 22, bold: true, color: C.ink });
    textBox(slide, d[2], x + 18, 456, 214, 48, { size: 14, color: C.gray });
    if (i < 3) textBox(slide, "→", x + 250, 410, 36, 42, { size: 28, bold: true, color: C.teal, align: "center" });
  });
  pill(slide, "失败时：拒答 / 降级 / 转人工，不静默放行", 776, 178, 440, C.amberBg, "#8A5A00");
  addNotes(slide, "一句话技术定义：模型负责理解与候选抽取，规则负责确定性裁决，证据负责追溯，人工负责发布。 ");
}

// 4 Journey
{
  const slide = baseSlide("PRODUCT", "一次咨询如何形成可信导办", 4);
  const flow = [
    ["表达诉求", "自然语言 / 示例家庭", C.mint],
    ["主动补问", "只问最有信息量的问题", C.cyan],
    ["资格预判", "符合 / 可能 / 不足 / 人工", C.amberBg],
    ["原文举证", "逐字引文、版本、来源", C.mint],
    ["行动建议", "材料、机构、下一步", C.cyan],
  ];
  flow.forEach((d, i) => {
    const x = 64 + i * 232;
    shape(slide, "roundRect", x, 216, 198, 166, d[2], C.line, "rounded-xl");
    textBox(slide, String(i + 1), x + 16, 232, 38, 32, { size: 16, bold: true, color: C.white, fill: C.teal, radius: "rounded-full", align: "center", valign: "middle", insets: { left: 2, right: 2, top: 1, bottom: 1 } });
    textBox(slide, d[0], x + 16, 278, 166, 36, { size: 21, bold: true, color: C.ink });
    textBox(slide, d[1], x + 16, 324, 166, 44, { size: 13, color: C.gray });
    if (i < 4) textBox(slide, "→", x + 198, 274, 34, 42, { size: 26, bold: true, color: C.teal, align: "center" });
  });
  card(slide, 64, 442, 550, 138, "UNKNOWN 是合法答案", "用户可以不知道或跳过。缺失值不会被偷偷改写为“不符合”。", { accent: C.teal, fill: C.soft, titleSize: 20, bodySize: 16 });
  card(slide, 666, 442, 550, 138, "系统从不宣布“已批准”", "输出是导办建议，不替代行政机关审批；高风险场景转人工。", { accent: C.red, fill: "#FFF0EE", titleSize: 20, bodySize: 16 });
  addNotes(slide, "现场演示建议从场景验证中心载入案例A，再切案例B展示信息不足状态。 ");
}

// 5 Architecture
{
  const slide = baseSlide("ARCHITECTURE", "一套内核支撑居民、经办与治理三端", 5);
  const layers = [
    ["交互层", "居民端  ·  经办工作台  ·  治理工作台  ·  场景验证中心", C.cyan],
    ["AI 理解层", "意图分类  ·  字段抽取  ·  OCR  ·  Policy2Rule 候选编译", C.mint],
    ["推理与证据层", "时态规则  ·  三值逻辑  ·  主动提问  ·  BM25/向量接口", C.amberBg],
    ["可信安全层", "独立校验器  ·  注入防护  ·  冲突检测  ·  人工发布门", "#FBE9E7"],
    ["工程层", "FastAPI  ·  SQLite  ·  审计日志  ·  CI  ·  离线降级", C.soft],
  ];
  layers.forEach((d, i) => {
    const y = 168 + i * 92;
    shape(slide, "roundRect", 150, y, 1030, 70, d[2], C.line, "rounded-xl");
    textBox(slide, d[0], 172, y + 14, 190, 40, { size: 20, bold: true, color: C.ink, valign: "middle" });
    textBox(slide, d[1], 390, y + 14, 760, 40, { size: 16, color: C.gray, valign: "middle" });
  });
  textBox(slide, "同一事实模型", 36, 190, 92, 414, { size: 18, bold: true, color: C.teal, align: "center", valign: "middle", fill: C.mint, radius: "rounded-xl" });
  addNotes(slide, "强调不是多个互不相干的演示页面：居民端输入的事实模型可直接形成经办摘要，并被治理侧回归集复用。 ");
}

// 6 Policy2Rule
{
  const slide = baseSlide("AI CORE 01", "Policy2Rule：模型产出候选，不拥有发布权", 6);
  const nodes = [
    ["政策原文", "官方网页 / PDF\n本地快照 + SHA-256", C.cyan],
    ["候选抽取", "对象、字段、运算符\n阈值、例外、有效期", C.mint],
    ["五重校验", "Schema / 白名单\n类型 / 原文子串 / 版本", C.amberBg],
    ["影响分析", "冻结案例批量回放\n状态变化与冲突", C.cyan],
    ["人工双审", "批准后才进入正式库\n模型无 publish 权限", "#FBE9E7"],
  ];
  nodes.forEach((d, i) => {
    const x = 50 + i * 244;
    shape(slide, "roundRect", x, 220, 208, 190, d[2], C.line, "rounded-xl");
    textBox(slide, String(i + 1), x + 16, 236, 34, 30, { size: 14, bold: true, color: C.white, fill: i === 4 ? C.red : C.teal, radius: "rounded-full", align: "center", valign: "middle", insets: { left: 1, right: 1, top: 1, bottom: 1 } });
    textBox(slide, d[0], x + 16, 282, 176, 36, { size: 21, bold: true, color: C.ink });
    textBox(slide, d[1], x + 16, 332, 176, 62, { size: 14, color: C.gray });
    if (i < 4) textBox(slide, "→", x + 208, 294, 36, 42, { size: 26, bold: true, color: C.teal, align: "center" });
  });
  metric(slide, 68, 474, 250, "官方条款", "11 条", "真实原文 · 项目组构造金标准");
  metric(slide, 345, 474, 250, "逐字锚定率", "1.000", "候选引文是原文连续子串");
  metric(slide, 622, 474, 250, "条件字段 F1", "0.727", "复杂条件仍是重点", C.amber);
  metric(slide, 899, 474, 250, "参数 F1", "0.500", "如实披露，不掩盖短板", C.red);
  addNotes(slide, "来源：data/evaluation/policy_compiler_real_report.json。11条来自官方政策原文，金标准由项目组构造，不称为独立专家评测。 ");
}

// 7 Temporal + three-valued
{
  const slide = baseSlide("AI CORE 02", "时态规则 + 三值逻辑：防止最危险的“想当然”", 7);
  textBox(slide, "同一问题，不同日期可能有不同答案", 64, 170, 650, 42, { size: 25, bold: true, color: C.ink });
  const timelineY = 292;
  rule(slide, 98, timelineY, 650, C.line, 5);
  shape(slide, "ellipse", 160, timelineY - 13, 30, 30, C.teal, "none");
  shape(slide, "ellipse", 452, timelineY - 13, 30, 30, C.amber, "none");
  shape(slide, "ellipse", 684, timelineY - 13, 30, 30, C.ink, "none");
  textBox(slide, "旧版生效", 112, 326, 126, 30, { size: 15, bold: true, color: C.teal, align: "center" });
  textBox(slide, "版本切换", 402, 326, 128, 30, { size: 15, bold: true, color: "#8A5A00", align: "center" });
  textBox(slide, "查询日期", 636, 326, 126, 30, { size: 15, bold: true, color: C.ink, align: "center" });
  card(slide, 64, 398, 700, 150, "检索先过滤，再召回", "先按地区与查询日期筛选有效版本；过期、未生效和跨地区片段进入排除列表，并解释“为什么没采用”。", { accent: C.teal, fill: C.soft, titleSize: 20, bodySize: 16 });
  const states = [
    ["TRUE", "条件满足", C.mint, C.teal],
    ["FALSE", "条件明确不满足", "#FBE9E7", C.red],
    ["UNKNOWN", "关键事实缺失", C.amberBg, "#8A5A00"],
  ];
  states.forEach((d, i) => {
    const y = 186 + i * 126;
    shape(slide, "roundRect", 844, y, 338, 104, d[2], C.line, "rounded-xl");
    textBox(slide, d[0], 868, y + 16, 150, 34, { size: 22, bold: true, color: d[3] });
    textBox(slide, d[1], 868, y + 54, 280, 28, { size: 15, color: C.gray });
  });
  textBox(slide, "UNKNOWN 不等于 FALSE", 846, 590, 336, 42, { size: 22, bold: true, color: C.ink, align: "center" });
  addNotes(slide, "消融结果：关闭二值保护，会迫使240个信息不足案例中的204个产生武断结果。来源 data/evaluation/ablation_report.json。 ");
}

// 8 Evidence chain
{
  const slide = baseSlide("TRUST", "每个结论都能回到逐字政策原文", 8);
  const x0 = 84;
  const blocks = [
    ["导办结论", "可能符合\n需补充家庭收入", C.ink, C.white],
    ["规则条件", "income_per_capita\n<= local_standard", C.teal, C.white],
    ["逐字引文", "原文连续子串\n不允许模型改写", C.amber, C.ink],
    ["来源快照", "URL / 文件定位\n发布日期 / 地区", "#3B7A97", C.white],
    ["完整性", "SHA-256\n审计时间 / 复核状态", C.dark, C.white],
  ];
  blocks.forEach((d, i) => {
    const x = x0 + i * 226;
    shape(slide, "roundRect", x, 240, 190, 190, d[2], "none", "rounded-xl");
    textBox(slide, d[0], x + 16, 262, 158, 34, { size: 20, bold: true, color: d[3], align: "center" });
    textBox(slide, d[1], x + 16, 318, 158, 74, { size: 14, color: d[3], align: "center", valign: "middle" });
    if (i < 4) textBox(slide, "→", x + 190, 314, 36, 42, { size: 26, bold: true, color: C.teal, align: "center" });
  });
  metric(slide, 160, 492, 260, "证据逐字审计", "18 / 18", "本地快照子串核验");
  metric(slide, 510, 492, 260, "检索 Recall@3", "1.000", "12 条项目内冻结问题");
  metric(slide, 860, 492, 260, "MRR", "0.958", "数据性质已明确标注");
  addNotes(slide, "来源：evidence_quote_audit.json 与 retrieval_report.json。检索只有12条项目内问题，必须明确样本量，不能外推真实使用效果。 ");
}

// 9 Active questioning
{
  const slide = baseSlide("AI CORE 03", "主动信息增益提问：少问，但不漏问", 9);
  card(slide, 64, 174, 430, 172, "传统表单", "按固定顺序询问 17 个字段\n用户负担高，且很多问题与当前事项无关", { accent: C.gray, fill: C.soft, titleSize: 23, bodySize: 17 });
  card(slide, 64, 382, 430, 172, "主动策略", "计算缺失事实对事项状态的区分能力\n优先问最能减少不确定性的问题", { accent: C.teal, fill: C.mint, titleSize: 23, bodySize: 17 });
  textBox(slide, "信息增益", 590, 170, 236, 44, { size: 25, bold: true, color: C.teal, align: "center" });
  textBox(slide, "×", 820, 170, 60, 44, { size: 24, bold: true, color: C.gray, align: "center" });
  textBox(slide, "风险优先级", 878, 170, 266, 44, { size: 25, bold: true, color: C.red, align: "center" });
  rule(slide, 612, 232, 510, C.line, 3);
  const qs = [
    ["家庭人口与共同生活成员？", "事项区分度高", C.teal],
    ["当前收入信息是否明确？", "直接影响多项规则", C.teal],
    ["是否存在紧急风险？", "高风险优先", C.red],
    ["无法确认？", "保留 UNKNOWN，可跳过", C.amber],
  ];
  qs.forEach((d, i) => {
    const y = 260 + i * 78;
    shape(slide, "roundRect", 570, y, 610, 58, C.white, C.line, "rounded-xl");
    shape(slide, "ellipse", 592, y + 16, 26, 26, d[2], "none");
    textBox(slide, d[0], 634, y + 10, 348, 38, { size: 17, bold: true, color: C.ink, valign: "middle" });
    textBox(slide, d[1], 976, y + 10, 180, 38, { size: 13, color: C.gray, align: "right", valign: "middle" });
  });
  textBox(slide, "240 个合成案例 · 状态一致性 100% · 紧急风险漏检 0", 570, 592, 610, 38, { size: 17, bold: true, color: C.ink, align: "center" });
  addNotes(slide, "来源：active_question_report.json。240例为项目内合成场景，用于证明算法机制，不是用户试点。 ");
}

// 10 Results chart
{
  const slide = baseSlide("EVIDENCE", "可复现实验：效率、安全与工程同时量化", 10);
  const chart = slide.charts.add("bar", {
    position: { left: 64, top: 190, width: 540, height: 350 },
    categories: ["固定完整表单", "主动信息增益"],
    series: [{ name: "平均问题数", values: [17, 8.25], fill: C.teal }],
    barOptions: { direction: "column", grouping: "clustered" },
    hasLegend: false,
    dataLabels: { showValue: true, position: "outEnd" },
  });
  applyPresentationChartFont(chart, { fontFamily: family });
  textBox(slide, "平均问题数", 190, 550, 290, 28, { size: 14, color: C.gray, align: "center" });
  metric(slide, 650, 184, 250, "提问减少", "51.47%", "相对 17 字段完整表单");
  metric(slide, 930, 184, 250, "安全回归", "100 / 100", "项目内高风险集通过");
  metric(slide, 650, 344, 250, "并发 30 · P95", "439.8 ms", "本机回环 Uvicorn");
  metric(slide, 930, 344, 250, "自动测试", "64 项", "全量 Pytest 当前通过");
  textBox(slide, "Qwen3画像 F1 1.000 · P95 2.592 s\n混合检索 P95 430 ms · 12/12真实路由", 650, 526, 530, 58, { size: 17, bold: true, color: C.ink, fill: C.amberBg, radius: "rounded-xl", align: "center", valign: "middle" });
  addNotes(slide, "来源：active_question_report.json、high_risk_safety_report.json、http_concurrency_report.json、ai_pipeline_report.json、pytest。画像与检索是项目内构造小样本，不能外推真人效果；并发测试是本机回环，不是生产压测。 ");
}

// 11 Safety
{
  const slide = baseSlide("SAFETY", "八组消融证明：可信机制不是界面装饰", 11);
  const tests = [
    ["三值逻辑", "204 / 240", "若强制二值化，将产生武断结果", C.red],
    ["证据门", "4320 条", "关闭后条件失去可追溯证据", C.red],
    ["主动提问", "+2.75", "固定提问平均额外问题", C.amber],
    ["人工发布门", "11 项", "自动发布候选全部被阻断", C.teal],
  ];
  tests.forEach((d, i) => {
    const x = 64 + (i % 2) * 576;
    const y = 180 + Math.floor(i / 2) * 188;
    shape(slide, "roundRect", x, y, 536, 154, C.soft, C.line, "rounded-xl");
    shape(slide, "rect", x, y, 9, 154, d[3], "none");
    textBox(slide, d[0], x + 28, y + 18, 250, 32, { size: 19, bold: true, color: C.ink });
    textBox(slide, d[1], x + 300, y + 14, 204, 44, { size: 30, bold: true, color: d[3], align: "right" });
    textBox(slide, d[2], x + 28, y + 76, 476, 48, { size: 16, color: C.gray });
  });
  const cats = [["UNKNOWN 保留", "25"], ["时间边界", "20"], ["越权问题", "20"], ["提示注入", "20"], ["发布门", "15"]];
  textBox(slide, "100 条高风险回归覆盖", 64, 584, 270, 34, { size: 19, bold: true, color: C.ink });
  cats.forEach((d, i) => pill(slide, `${d[0]} ${d[1]}`, 340 + i * 174, 582, 160, i === 0 ? C.mint : C.cyan, C.ink));
  addNotes(slide, "来源：ablation_report.json 与 high_risk_safety_report.json。高风险集是项目内构建，不称为独立红队。 ");
}

// 12 Product modules
{
  const slide = baseSlide("SYSTEM", "从居民咨询到政策治理的完整软件闭环", 12);
  const mods = [
    ["居民智能导办", "诉求解析 · 主动补问\n资格预判 · 下一步", C.mint],
    ["政策证据检索", "地区/日期过滤\n逐字引文 · 排除解释", C.cyan],
    ["材料智能预检", "OCR 候选字段\n质量提醒 · 人工确认", C.amberBg],
    ["经办工作台", "五事项摘要\n缺失信息 · 风险标记", C.soft],
    ["治理工作台", "候选规则 · 版本差异\n影响分析 · 双审发布", "#FBE9E7"],
    ["场景验证中心", "A–F 六条路径\n现场稳定复现", C.mint],
  ];
  mods.forEach((d, i) => {
    const col = i % 3;
    const row = Math.floor(i / 3);
    const x = 64 + col * 386;
    const y = 180 + row * 220;
    shape(slide, "roundRect", x, y, 350, 180, d[2], C.line, "rounded-xl");
    textBox(slide, `0${i + 1}`, x + 20, y + 18, 46, 28, { size: 14, bold: true, color: C.teal });
    textBox(slide, d[0], x + 20, y + 58, 310, 34, { size: 22, bold: true, color: C.ink });
    textBox(slide, d[1], x + 20, y + 108, 310, 54, { size: 15, color: C.gray });
  });
  textBox(slide, "一套事实模型 · 一条证据链 · 一套回归体系", 64, 606, 1122, 40, { size: 22, bold: true, color: C.teal, align: "center" });
  addNotes(slide, "现场可快速展示：居民端→证据查询→治理影响分析→可信度中心。 ");
}

// 13 Engineering
{
  const slide = baseSlide("ENGINEERING", "单机可运行、可测试、可审计、可打包", 13);
  const cols = [
    ["运行", ["Python 3.12 + FastAPI", "Qwen3 双模型 100% GPU", "PowerShell 一键启停", "模型不可用显式降级"]],
    ["质量", ["64 项自动测试", "100 条高风险回归", "前端路由契约", "六条演示路径"]],
    ["供应链", ["46 项锁定依赖", "SBOM 软件物料清单", "已知漏洞 0", "数据与源码哈希"]],
  ];
  cols.forEach((d, i) => {
    const x = 64 + i * 386;
    shape(slide, "roundRect", x, 184, 350, 360, i === 1 ? C.mint : C.soft, C.line, "rounded-xl");
    textBox(slide, d[0], x + 22, 206, 306, 44, { size: 27, bold: true, color: i === 1 ? C.teal : C.ink });
    d[1].forEach((v, j) => {
      shape(slide, "ellipse", x + 24, 282 + j * 58, 18, 18, j === 3 ? C.amber : C.teal, "none");
      textBox(slide, v, x + 54, 270 + j * 58, 272, 40, { size: 16, color: C.ink, valign: "middle" });
    });
  });
  textBox(slide, "reproduce_phase12.ps1  →  重跑评测、清单、SBOM 与并发测试", 64, 584, 1122, 44, { size: 18, bold: true, color: C.ink, fill: C.cyan, radius: "rounded-xl", align: "center", valign: "middle" });
  addNotes(slide, "强调供应链和复现：依赖锁定、漏洞审计、SBOM、Git基线和自动化CI都不是答辩文字，而是仓库内真实文件。 ");
}

// 14 Boundaries
{
  const slide = baseSlide("HONESTY", "我们明确知道：什么已经证明，什么尚未证明", 14);
  card(slide, 64, 180, 536, 360, "已经可验证", "✓ 可信软件闭环可运行\n✓ 规则与证据逐字追溯\n✓ Qwen3双模型GPU冻结评测\n✓ 高风险输出被工程护栏阻断\n✓ 单机并发与供应链状态可检查", { accent: C.teal, fill: C.mint, titleSize: 26, bodySize: 20 });
  card(slide, 650, 180, 536, 360, "仍需真人完成", "○ 真实参与者可用性试点\n○ 另一台干净电脑安装验收\n○ 3–5 分钟真人演示视频\n○ 盖章、签字与指定平台提交\n○ 最终平台信息与下载链接", { accent: C.amber, fill: C.amberBg, titleSize: 26, bodySize: 20 });
  textBox(slide, "不把合成数据写成真人数据，不把导办写成审批，不把内部评测写成第三方认证。", 64, 584, 1122, 54, { size: 21, bold: true, color: C.ink, align: "center", valign: "middle" });
  addNotes(slide, "这一页主动说明边界。模型实测已完成；真人试点、第三方干净机验收和团队视频仍必须由真实参与者完成。 ");
}

// 15 Close
{
  const slide = deck.slides.add();
  slide.background.fill = C.dark;
  shape(slide, "rect", 0, 0, 18, H, C.teal, "none");
  textBox(slide, "惠民智导", 74, 82, 450, 62, { size: 42, bold: true, color: "#92E6D8" });
  textBox(slide, "把高风险政策智能做成\n可追溯、可拒答、可回归的软件。", 74, 180, 930, 170, { size: 40, bold: true, color: C.white });
  textBox(slide, "技术主张", 74, 414, 120, 30, { size: 15, bold: true, color: "#92E6D8" });
  textBox(slide, "受约束神经符号架构  /  时态规则  /  三值逻辑  /  原文证据链  /  人工发布门", 74, 454, 1050, 70, { size: 20, color: "#B7C7D4" });
  pill(slide, "现在进入系统演示", 74, 580, 250, C.teal, C.white);
  textBox(slide, "谢谢", 1030, 576, 170, 50, { size: 28, bold: true, color: C.white, align: "right" });
  addNotes(slide, "结束语：惠民智导不是一个政策聊天机器人，而是一套能把生成式AI风险约束进工程流程的可信软件方法。随后进入六条固定演示路径。 ");
}

const requirements = {
  explicitTotalSlideCount: 15,
  requiredNativeTableOwnerSlides: [],
  requiredNativeChartOwnerSlides: [10],
  requiredEmbeddedWorkbookChartOwnerSlides: [],
  materializeLiteralChartWorkbooks: true,
};
const fontPolicy = { basis: "design", families: [family] };
const stagingDir = path.join(TMP_DIR, ".codex-finalizer");
await fs.mkdir(stagingDir, { recursive: true });
const candidatePath = path.join(stagingDir, "candidate.pptx");
await (await PresentationFile.exportPptx(deck)).save(candidatePath);

const result = await finalizePresentation({
  ...requirements,
  workspaceDir: WORKSPACE_DIR,
  candidatePath,
  finalPath: FINAL_PPTX,
  pythonExecutable: RUNTIME_PYTHON,
  integrityValidatorPath: path.join(SKILL_DIR, "container_tools/inspect_presentation_package_integrity.py"),
  layoutValidatorPath: path.join(SKILL_DIR, "container_tools/inspect_presentation_layout_geometry.py"),
  layoutArgs: [
    "--expected-slide-size-emu", "12192000,6858000",
    "--validate-bullet-geometry",
    "--validate-heading-fit",
  ],
  requiredNativeTableOwnerSlides: [],
  fontPolicy,
  verifyArtifactToolImport: true,
  receiptPath: path.join(stagingDir, `${path.basename(FINAL_PPTX)}.validation.json`),
});

const montage = await deck.export({ format: "webp", montage: true, scale: 1 });
await fs.writeFile(path.join(TMP_DIR, "montage.webp"), new Uint8Array(await montage.arrayBuffer()));
console.log(JSON.stringify({ final: FINAL_PPTX, font: family, result }, null, 2));
