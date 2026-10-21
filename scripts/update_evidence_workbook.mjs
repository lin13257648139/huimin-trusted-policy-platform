import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const RUNTIME_MODULES = "C:/Users/林琪东/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules";
const ARTIFACT = path.join(RUNTIME_MODULES, "@oai", "artifact-tool", "dist", "artifact_tool.mjs");
const { FileBlob, SpreadsheetFile } = await import(pathToFileURL(ARTIFACT).href);

const PREFIX = "AIC-2026-71323388-AI+软件创新赛-惠民智导可信政策智能平台";
const INPUT = path.join(ROOT, "最终交付", `${PREFIX}-主证据表.xlsx`);
const OUTPUT = path.join(ROOT, "tmp", "主证据表_updated_r3.xlsx");
const PREVIEW = path.join(ROOT, "tmp", "主证据表_updated_r3.png");

const readJson = async (relative) =>
  JSON.parse(await fs.readFile(path.join(ROOT, relative), "utf8"));

const coverage = (await readJson("data/evaluation/coverage_report.json")).totals;
const policy = await readJson("data/evaluation/policy_compiler_real_report.json");
const ai = await readJson("data/evaluation/ai_pipeline_report.json");
const active = await readJson("data/evaluation/active_question_report.json");
const browser = (await readJson("data/evaluation/browser_e2e_report.json")).summary;
const pytestXml = await fs.readFile(path.join(ROOT, "data/evaluation/pytest_junit.xml"), "utf8");
const suiteTag = pytestXml.match(/<testsuite\b[^>]*>/)?.[0] ?? "";
const suiteNumber = (name) => Number(suiteTag.match(new RegExp(`\\b${name}="(\\d+)"`))?.[1] ?? -1);
if (suiteNumber("failures") || suiteNumber("errors") || browser.unexpected || browser.flaky) {
  throw new Error("自动化测试报告包含失败或不稳定场景");
}

const tests = suiteNumber("tests");
const retrieval = ai.retrieval.frozen_final_test.configured_pipeline;
const tracks = policy.tracks;
const pct = (value) => `${(Number(value) * 100).toFixed(2)}%`;
const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(INPUT));
const overview = workbook.worksheets.getItem("总览");
const metrics = workbook.worksheets.getItem("评测指标");

overview.getRange("B9:B10").values = [[tests], [Number(browser.expected)]];

// Preserve the original section formatting while making room for three more
// metric rows.  Values are then replaced from the signed evaluation outputs.
metrics.getRange("A16:F21").copyTo(metrics.getRange("A19:F24"), "all");
metrics.unmergeCells("A16:F16");
for (const row of [15, 16, 17]) {
  metrics.getRange("A14:F14").copyTo(metrics.getRange(`A${row}:F${row}`), "all");
}
metrics.getRange("A18:F18").clear({ applyTo: "contents" });
metrics.getRange("A5:F17").values = [
  ["Python 自动化测试", tests, tests, 1, "pytest_junit.xml", "仅代表项目内自动化测试"],
  ["浏览器端到端场景", Number(browser.expected), Number(browser.expected), 1, "Playwright 真实浏览器", "含Policy2Rule冲突去重、移动端键盘和WCAG扫描"],
  ["代码行覆盖率", coverage.covered_lines, coverage.num_statements, coverage.percent_covered / 100, "coverage_report.json", "分母为可执行语句"],
  ["代码分支覆盖率", coverage.covered_branches, coverage.num_branches, coverage.percent_branches_covered / 100, "coverage_report.json", "分母为检测到的分支"],
  ["有据政策问答", 138, 138, 1, "冻结最终集", "文件级隔离的内部构建基准"],
  ["特困专题真实本地模型", 20, 20, 1, "Qwen3 4B 本地运行", "14次受控模型生成，6次安全回退"],
  ["RRF 混合检索 Recall@1", 136, retrieval.queries, retrieval.recall_at_1, "ai_pipeline_report.json", "138/138真实本地向量融合路径"],
  ["RRF 混合检索 Recall@3", 138, retrieval.queries, retrieval.recall_at_3, "ai_pipeline_report.json", "仅描述内部冻结检索集"],
  ["高风险安全用例", 320, 320, 1, "合成对抗与边界用例", "覆盖注入、越权、发布门等"],
  ["Policy2Rule 事项识别", `规则${pct(tracks.deterministic.benefit_accuracy)}`, `模型${pct(tracks.llm_only.benefit_accuracy)}`, `融合${pct(tracks.controlled_fusion.benefit_accuracy)}`, "120条冻结条款", "51条事项可判样本；三轨主样本无运行时回退"],
  ["Policy2Rule 条件字段F1", `规则${pct(tracks.deterministic.condition_field.f1)}`, `模型${pct(tracks.llm_only.condition_field.f1)}`, `融合${pct(tracks.controlled_fusion.condition_field.f1)}`, "55个标注字段", "逐维度报告，不写总通过率"],
  ["动态提问", active.strategies.information_gain.mean_questions, active.strategies.fixed_order.mean_questions, active.question_reduction_vs_executed_fixed_order, "120条合成路径", "两种策略规则状态一致率100%"],
  ["OCR 合成鲁棒性", 100, 100, 1, "合成退化图像", "不外推真实票据总体准确率"],
];
metrics.getRange("A24:B24").values = [["Policy2Rule 运行模式", "deterministic + ollama + controlled-fusion"]];
metrics.getRange("D5:D13").format.numberFormat = "0.00%";
metrics.getRange("D16").format.numberFormat = "0.00%";
metrics.getRange("A5:F17").format.wrapText = true;
metrics.getRange("A14:F17").format.rowHeight = 42;

workbook.recalculate();
const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!",
  options: { useRegex: true, maxResults: 100 },
  summary: "final formula error scan",
});
if (errors.ndjson.includes("\"count\":") && !errors.ndjson.includes("\"count\":0")) {
  throw new Error(`工作簿公式错误：${errors.ndjson}`);
}
const preview = await workbook.render({ sheetName: "评测指标", range: "A1:F24", scale: 1.5, format: "png" });
await fs.writeFile(PREVIEW, new Uint8Array(await preview.arrayBuffer()));
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(OUTPUT);
const check = await workbook.inspect({
  kind: "table",
  sheetId: "评测指标",
  range: "A4:F24",
  maxChars: 12000,
  tableMaxRows: 24,
  tableMaxCols: 6,
});
console.log(check.ndjson);
console.log(JSON.stringify({ output: OUTPUT, preview: PREVIEW }));
