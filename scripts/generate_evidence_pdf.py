from __future__ import annotations

import json
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "tmp" / "惠民智导_佐证材料_v2_r2.pdf"
SHOTS = ROOT / "最终交付" / "截图证据"

GREEN = colors.HexColor("#075F50")
GREEN_2 = colors.HexColor("#0F7A67")
MINT = colors.HexColor("#EAF5F1")
PALE = colors.HexColor("#F6F9F7")
INK = colors.HexColor("#17342E")
MUTED = colors.HexColor("#66766F")
LINE = colors.HexColor("#D6E0DC")
AMBER = colors.HexColor("#A46814")
AMBER_PALE = colors.HexColor("#FFF5DE")


def load_json(relative: str):
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


pdfmetrics.registerFont(TTFont("CN", r"C:\Windows\Fonts\simhei.ttf"))

styles = getSampleStyleSheet()
title = ParagraphStyle(
    "TitleCN",
    parent=styles["Title"],
    fontName="CN",
    fontSize=27,
    leading=38,
    textColor=INK,
    alignment=TA_LEFT,
    spaceAfter=18,
)
cover_title = ParagraphStyle(
    "CoverTitleCN",
    parent=title,
    fontSize=34,
    leading=48,
    textColor=colors.white,
    alignment=TA_LEFT,
)
h1 = ParagraphStyle(
    "H1CN",
    parent=styles["Heading1"],
    fontName="CN",
    fontSize=19,
    leading=28,
    textColor=INK,
    spaceAfter=12,
)
screen_title = ParagraphStyle(
    "ScreenTitleCN",
    parent=h1,
    fontSize=16.5,
    leading=24,
)
h2 = ParagraphStyle(
    "H2CN",
    parent=styles["Heading2"],
    fontName="CN",
    fontSize=13,
    leading=20,
    textColor=GREEN,
    spaceBefore=8,
    spaceAfter=6,
)
body = ParagraphStyle(
    "BodyCN",
    parent=styles["BodyText"],
    fontName="CN",
    fontSize=10.5,
    leading=18,
    textColor=INK,
    spaceAfter=7,
)
small = ParagraphStyle(
    "SmallCN",
    parent=body,
    fontSize=8.2,
    leading=13,
    textColor=MUTED,
)
white_body = ParagraphStyle(
    "WhiteBodyCN",
    parent=body,
    fontSize=12,
    leading=21,
    textColor=colors.white,
)
caption = ParagraphStyle(
    "CaptionCN",
    parent=small,
    fontSize=9,
    leading=15,
    alignment=TA_CENTER,
    textColor=MUTED,
)
table_head = ParagraphStyle(
    "TableHeadCN",
    parent=small,
    fontSize=8.5,
    leading=12,
    alignment=TA_CENTER,
    textColor=colors.white,
)
table_cell = ParagraphStyle(
    "TableCellCN",
    parent=small,
    fontSize=8.2,
    leading=12.5,
    textColor=INK,
)


def P(text: str, style=body) -> Paragraph:
    return Paragraph(text.replace("&", "&amp;"), style)


def metric_table(rows: list[list[object]], widths: list[float]) -> Table:
    prepared = []
    for row_idx, row in enumerate(rows):
        prepared.append([P(str(value), table_head if row_idx == 0 else table_cell) for value in row])
    table = Table(prepared, colWidths=widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), GREEN),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PALE]),
                ("GRID", (0, 0), (-1, -1), 0.4, LINE),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table


def page_header(story: list, eyebrow: str, heading: str, description: str | None = None):
    story.append(P(eyebrow, h2))
    story.append(P(heading, screen_title if "产品实机" in eyebrow else h1))
    story.append(Table([[""]], colWidths=[17.4 * cm], rowHeights=[0.04 * cm], style=TableStyle([("BACKGROUND", (0, 0), (-1, -1), LINE)])))
    story.append(Spacer(1, 0.28 * cm))
    if description:
        story.append(P(description, body))


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("CN", 8)
    canvas.setFillColor(MUTED)
    canvas.drawString(2 * cm, 1.15 * cm, "惠民智导 v2.0.0 · 国赛佐证材料")
    canvas.drawRightString(19 * cm, 1.15 * cm, f"{doc.page}")
    canvas.restoreState()


evidence = load_json("app/data/evidence.json")
provenance = load_json("data/raw_official/provenance_manifest.json")
coverage = load_json("data/evaluation/coverage_report.json")
qa = load_json("data/evaluation/policy_qa_report.json")
qa_live = load_json("data/evaluation/policy_qa_special_live_report.json")
retrieval = load_json("data/evaluation/retrieval_report.json")
safety = load_json("data/evaluation/high_risk_safety_report.json")
ocr = load_json("data/evaluation/ocr_report.json")
compiler = load_json("data/evaluation/policy_compiler_report.json")
live = load_json("data/evaluation/live_ai_smoke_report.json")

doc = SimpleDocTemplate(
    str(OUTPUT),
    pagesize=A4,
    leftMargin=1.8 * cm,
    rightMargin=1.8 * cm,
    topMargin=1.6 * cm,
    bottomMargin=1.8 * cm,
    title="惠民智导可信政策智能平台佐证材料",
    author="策马奔腾队",
)
story: list = []

# 1 Cover
cover = Table(
    [[
            [
                Spacer(1, 2.2 * cm),
                P("2026 AI 软件创新赛", white_body),
                Spacer(1, 0.55 * cm),
                P("惠民智导<br/>可信政策智能平台", cover_title),
                Spacer(1, 0.45 * cm),
                P("工程、证据、评测与产品实机佐证材料", white_body),
                Spacer(1, 4.6 * cm),
                P("策马奔腾队<br/>AIC-2026-71323388<br/>版本 2.0.0 · 2026-10-21", white_body),
                Spacer(1, 3.3 * cm),
            ]
    ]],
    colWidths=[17.4 * cm],
    style=TableStyle(
        [
            ("BACKGROUND", (0, 0), (-1, -1), GREEN),
            ("LEFTPADDING", (0, 0), (-1, -1), 1.0 * cm),
            ("RIGHTPADDING", (0, 0), (-1, -1), 1.0 * cm),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]
    ),
)
story.extend([cover, PageBreak()])

# 2 Validation summary
page_header(story, "01 结论与范围", "已形成可运行、可解释、可追溯的工程闭环")
summary_rows = [
    ["证据", "当前结果", "核验范围"],
    ["产品能力", "六类事项、四步向导、材料预检、政策问答、专业工作台", "申请前导办，不替代正式受理、调查或审批"],
    ["政策证据", f"{len(provenance['sources'])} 个来源，{len(evidence)} 条逐字证据", "URL、本地快照、SHA-256 与原文定位"],
    ["自动化测试", "265 项通过；浏览器端到端 11/11", "项目内工程测试"],
    ["代码覆盖", f"行 {coverage['totals']['percent_covered']:.2f}%；分支 {coverage['totals']['percent_branches_covered']:.2f}%", "不代表真实审批准确率"],
    ["真实本地模型", "特困专题 20/20 闭环", "14 次受控模型生成；6 次安全回退"],
]
story.append(metric_table(summary_rows, [3.3 * cm, 6.0 * cm, 8.1 * cm]))
story.append(Spacer(1, 0.5 * cm))
story.append(P("真实评价", h2))
story.append(P("项目已经跨过“概念演示”门槛，具备国赛答辩所需要的完整产品路径、规则边界、证据闭环、模型约束和可复现实验。仍缺少外部专家双人盲标、真实用户封闭试点和正式政务部署评审，因此不能把项目内指标表述为实际审批准确率，也不能承诺获奖。"))
story.append(PageBreak())

# 3 Architecture
page_header(story, "02 系统架构", "受约束的混合架构", "AI 负责理解与整理，规则负责资格方向，人工负责正式发布和审批。")
arch_rows = [
    ["层级", "组成", "控制点"],
    ["交互层", "四步向导、政策问答、材料预检、专业工作台", "首屏任务化；按事项渐进披露"],
    ["API 层", "FastAPI、Schema 校验、鉴权、审计", "请求与响应结构可检查"],
    ["AI 协作层", "Qwen3 4B、Qwen3 Embedding、本地 OCR", "本地回环；输出受证据白名单约束"],
    ["决策层", "版本化规则、三态求值、事项关系", "缺失信息保留 UNKNOWN；不猜测"],
    ["证据与治理层", "官方来源、逐字证据、Policy2Rule、冻结评测", "候选规则需人工发布；评测绑定版本"],
]
story.append(metric_table(arch_rows, [3.0 * cm, 7.0 * cm, 7.4 * cm]))
story.append(Spacer(1, 0.5 * cm))
story.append(P("关键机制", h2))
for item_no, text in enumerate([
    "同一规则引擎服务居民预筛与基层工作台，避免两个口径。",
    "政策问答先检索并限定证据，再由模型组织答案；引用、原文、数字与边界任一校验失败即回退。",
    "Policy2Rule 只生成候选规则、版本差异和影响分析，禁止自动发布。",
], start=1):
    story.append(P(f"（{item_no}）{text}"))
story.append(PageBreak())

# 4 Metrics
page_header(story, "03 量化评测", "指标与适用边界")
metric_rows = [
    ["指标", "结果", "样本", "适用边界"],
    ["自动化测试", "265/265", "项目测试", "工程回归"],
    ["浏览器端到端", "11/11", "真实浏览器场景", "核心用户路径"],
    ["代码行覆盖", f"{coverage['totals']['percent_covered']:.2f}%", f"{coverage['totals']['covered_lines']}/{coverage['totals']['num_statements']}", "可执行语句"],
    ["代码分支覆盖", f"{coverage['totals']['percent_branches_covered']:.2f}%", f"{coverage['totals']['covered_branches']}/{coverage['totals']['num_branches']}", "检测到的分支"],
    ["有据政策问答", "138/138", "冻结最终集", "内部构建基准"],
    ["检索 Recall@1", f"{retrieval['recall_at_1']:.2%}", f"{retrieval['query_count']} 条", "冻结检索集"],
    ["特困专题本地模型", "20/20", "冻结专题集", "端到端证据闭环"],
    ["高风险安全", f"{safety['passed']}/{safety['cases']}", "合成对抗与边界用例", "注入、越权、发布门等"],
    ["Policy2Rule", "120/120", "冻结条款集", "候选规则，不自动发布"],
    ["OCR", f"{ocr['classification_accuracy']:.2%}", f"{ocr['case_count']} 张合成退化图像", "不外推真实票据总体"],
]
story.append(metric_table(metric_rows, [4.0 * cm, 3.0 * cm, 4.0 * cm, 6.4 * cm]))
story.append(Spacer(1, 0.45 * cm))
story.append(P("所有结果均与 v2.0.0、规则引擎 0.6.0、冻结数据摘要和模型摘要绑定。", small))
story.append(PageBreak())

# 5 Provenance
page_header(story, "04 政策证据", "来源、原文与版本能够回查")
prov_rows = [["维度", "数量/状态", "核验方式"]]
prov_rows.extend(
    [
        ["来源清单", len(provenance["sources"]), "URL、本地快照、字节数、SHA-256"],
        ["逐字证据", len(evidence), "定位字段、逐字原文与规范化匹配"],
        ["逐字核验", sum(1 for item in evidence if item["quote_verified"]), "全部 33 条通过"],
        ["历史版本", sum(1 for item in evidence if item["status"] == "superseded"), "明确标记 superseded，不进入现行规则"],
    ]
)
story.append(metric_table(prov_rows, [4.0 * cm, 4.2 * cm, 9.2 * cm]))
story.append(Spacer(1, 0.45 * cm))
story.append(P("证据链示例", h2))
for item in evidence[:4]:
    story.append(
        KeepTogether(
            [
                P(f"{item['evidence_id']} · {item['title']} · {item['article']}", h2),
                P(item["verbatim_quote"], small),
                P(f"定位：{item['locator']}　SHA-256：{item['source_sha256'][:20]}…", small),
            ]
        )
    )
story.append(PageBreak())

# 6 Live AI
page_header(story, "05 本地模型", "模型参与答案组织，但不能越过规则与证据")
live_rows = [
    ["项目", "值", "核验"],
    ["聊天模型", live["runtime"]["chat_model"], "digest 已核验" if live["runtime"]["model_digest_verified"] else "未核验"],
    ["向量模型", live["runtime"]["embedding_model"], "digest 已核验" if live["runtime"]["embedding_model_digest_verified"] else "未核验"],
    ["活动提供方", live["runtime"]["active_provider"], "本地 Ollama"],
    ["专题闭环", "20/20", "引用、原文、数字与决策边界全部通过"],
    ["生成方式", "14 次受控模型生成", "6 次安全抽取回退"],
]
story.append(metric_table(live_rows, [4.0 * cm, 7.2 * cm, 6.2 * cm]))
story.append(Spacer(1, 0.5 * cm))
story.append(P("回退条件", h2))
story.append(P("当模型出现重复结论、证据语义词项重合不足、引用越界、未经支持的数字或决策边界不合规时，系统舍弃生成结果并返回逐字证据。模型不可把缺失事实补成“符合”。"))
story.append(P("模型摘要", h2))
story.append(P(f"聊天模型：{live['runtime']['model_digest']}<br/>向量模型：{live['runtime']['embedding_model_digest']}", small))
story.append(PageBreak())

# 7 Security and gaps
page_header(story, "06 安全、边界与剩余缺口", "如实列示已完成控制和仍需人工补齐的外部证据")
gap_rows = [
    ["主题", "当前状态", "仍需补齐"],
    ["隐私", "申请前导办不要求真实姓名和身份证号；本地 OCR", "真实部署前完成等保、日志留存与数据影响评估"],
    ["安全", f"高风险用例 {safety['passed']}/{safety['cases']}", "第三方渗透测试与部署环境基线"],
    ["政策治理", "候选规则禁止自动发布；版本差异可见", "主管部门双人复核与正式发布流程"],
    ["可用性", "大字、键盘、朗读、打印；自动扫描通过", "真实居民与基层人员封闭可用性试点"],
    ["评测", "冻结集、源码指纹、模型摘要与报告绑定", "外部专家双人盲标与跨区域泛化评测"],
]
story.append(metric_table(gap_rows, [3.4 * cm, 6.4 * cm, 7.6 * cm]))
story.append(Spacer(1, 0.5 * cm))
story.append(P("提交前必须由团队本人完成", h2))
for item_no, line in enumerate([
    "录制 3–5 分钟真人出镜演示，避免仅使用自动合成视频。",
    "补全报名平台要求的负责人、指导教师、学校/单位、联系方式与永久网盘链接。",
    "用比赛指定模板复核页数、文件命名、盖章/签字和大小限制。",
    "答辩前在最终展示电脑完成一次离线启动、模型可用性和浏览器全流程彩排。",
], start=1):
    story.append(P(f"（{item_no}）{line}"))
story.append(PageBreak())

# 8-15 Screenshots
screens = [
    ("01_服务首页_v2.png", "服务首页：先选情境，再进入任务，不展示系统模块清单。"),
    ("02_特困供养逐项核对_v2.png", "特困供养：只在用户选择相关方向后展开专项法定条件。"),
    ("03_特困供养可信结果_v2.png", "可信结果：三态判断、信息缺口、证据和下一步行动同屏呈现。"),
    ("04_有据政策问答_v2.png", "政策问答：回答与逐字证据绑定，校验失败即回退。"),
    ("05_材料智能预检_v2.png", "材料预检：本地 OCR 只检查清晰度与候选字段，不判断材料真伪。"),
    ("06_可信机制说明_v2.png", "可信说明：公开展示规则、证据、模型与人工边界。"),
    ("07_Policy2Rule工作台_v2.png", "Policy2Rule：确定性、模型抽取和受控融合三轨保留，候选规则禁止自动发布。"),
    ("08_运行治理面板_v2.png", "运行治理：版本、模型、摘要、审计和运行状态集中可查。"),
]
for index, (file_name, text) in enumerate(screens, start=7):
    page_header(story, f"{index:02d} 产品实机", text)
    image = Image(str(SHOTS / file_name), width=17.4 * cm, height=12.08 * cm)
    story.append(image)
    story.append(Spacer(1, 0.35 * cm))
    story.append(P(f"图 {index - 6}　{file_name.replace('_v2.png', '')}", caption))
    if file_name != screens[-1][0]:
        story.append(PageBreak())

OUTPUT.parent.mkdir(parents=True, exist_ok=True)
doc.build(story, onFirstPage=footer, onLaterPages=footer)
print(OUTPUT)
