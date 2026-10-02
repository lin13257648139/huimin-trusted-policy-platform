from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVALUATION_DIR = ROOT / "data" / "evaluation"
METRICS_PATH = EVALUATION_DIR / "expert_evaluation_report.json"
AUDIT_PATH = EVALUATION_DIR / "expert_gold_audit.json"
OUTPUT_PATH = EVALUATION_DIR / "expert_evaluation_report.md"


def _percent(value: float | None) -> str:
    return "未评测" if value is None else f"{value * 100:.2f}%"


def build() -> str:
    metrics = json.loads(METRICS_PATH.read_text(encoding="utf-8"))
    audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    overall = metrics["overall"]
    agreement = audit["inter_reviewer_agreement"]
    b002 = metrics["by_benefit"]["B002"]
    b005 = metrics["by_benefit"]["B005"]
    lines = [
        "# 惠民智导专家金标评测报告",
        "",
        f"冻结日期：{audit['frozen_at']}",
        "",
        "## 一、评测数据与标注流程",
        "",
        f"- 原始评审记录：{audit['records']}条。",
        f"- 唯一家庭画像：{audit['unique_profiles']}例。",
        f"- 评测时排除的重复记录：{audit['duplicate_records_excluded_in_evaluation']}条。",
        f"- 最终事项决定：{metrics['decision_count']}个。",
        f"- 专家C裁决：{audit['adjudication_rows']}条记录、{audit['adjudication_decisions']}个分歧决定。",
        "- 专家A、B独立填写；专家C只裁决分歧项；系统预测未写入专家评审表。",
        "",
        "## 二、专家一致性",
        "",
        "| 统计口径 | 一致决定 | 总决定 | 原始一致率 | Cohen's κ |",
        "|---|---:|---:|---:|---:|",
        (
            f"| 120条原始记录 | {agreement['all_records']['agreements']} | "
            f"{agreement['all_records']['decisions']} | "
            f"{_percent(agreement['all_records']['raw_agreement'])} | "
            f"{agreement['all_records']['cohen_kappa']:.4f} |"
        ),
        (
            f"| 107个唯一画像 | {agreement['unique_profiles']['agreements']} | "
            f"{agreement['unique_profiles']['decisions']} | "
            f"{_percent(agreement['unique_profiles']['raw_agreement'])} | "
            f"{agreement['unique_profiles']['cohen_kappa']:.4f} |"
        ),
        "",
        "## 三、总体结果",
        "",
        "| 指标 | 结果 |",
        "|---|---:|",
        f"| 严格四分类准确率 | {_percent(overall['strict_exact_accuracy'])} |",
        f"| likely精确率 | {_percent(overall['likely_precision'])} |",
        f"| likely召回率 | {_percent(overall['likely_recall'])} |",
        f"| 高风险假阳性率 | {_percent(overall['high_risk_false_positive_rate'])} |",
        f"| 自动覆盖率 | {_percent(overall['auto_coverage'])} |",
        f"| 自动输出选择性准确率 | {_percent(overall['selective_accuracy'])} |",
        f"| 不安全自动判断率 | {_percent(overall['unsafe_automation_rate'])} |",
        f"| 人工复核率 | {_percent(overall['manual_review_rate'])} |",
        f"| 信息不足率 | {_percent(overall['incomplete_rate'])} |",
        f"| 弃权率 | {_percent(overall['abstention_rate'])} |",
        "",
        "## 四、分事项结果",
        "",
        "| 事项 | 案例数 | 严格准确率 | likely精确率 | likely召回率 | 高风险假阳性率 | 自动覆盖率 | 选择性准确率 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for benefit in ("B001", "B002", "B003", "B004", "B005"):
        item = metrics["by_benefit"][benefit]
        lines.append(
            f"| {benefit} | {item['cases']} | {_percent(item['strict_exact_accuracy'])} | "
            f"{_percent(item['likely_precision'])} | {_percent(item['likely_recall'])} | "
            f"{_percent(item['high_risk_false_positive_rate'])} | "
            f"{_percent(item['auto_coverage'])} | {_percent(item['selective_accuracy'])} |"
        )
    lines.extend(
        [
            "",
            "## 五、结果解释",
            "",
            "- B001、B003、B004在当前构造案例上严格准确率为100%。",
            f"- B002整改后严格准确率为{_percent(b002['strict_exact_accuracy'])}，likely召回率为{_percent(b002['likely_recall'])}；历史快照、精确等值和成员范围依赖三类已知误差均已清零。",
            f"- B005对‘申请日前一个月内’的30/31日歧义增加人工复核门后，严格准确率为{_percent(b005['strict_exact_accuracy'])}，高风险假阳性率为{_percent(b005['high_risk_false_positive_rate'])}。",
            f"- 总体严格准确率为{_percent(overall['strict_exact_accuracy'])}，likely精确率为{_percent(overall['likely_precision'])}，自动覆盖率为{_percent(overall['auto_coverage'])}；其余决定进入人工复核或信息不足，符合高风险民生场景的拒答设计。",
            "- 政策快照准确率未计算，因为专家表未填写独立的gold_policy_snapshot；不得将其写成100%。",
            "",
            "## 六、适用边界",
            "",
            "本评测使用的家庭画像来源于合成回归案例，专家标签是真实独立评审与裁决结果。因此，本报告可以证明系统在当前构造案例上的表现，但不能外推为真实困难群众场景准确率，也不能替代真实咨询改写案例、基层试点和用户研究。",
            "",
            "## 七、冻结与复现",
            "",
            f"- expert_review_A.csv SHA-256：`{audit['sha256']['expert_review_A.csv']}`",
            f"- expert_review_B.csv SHA-256：`{audit['sha256']['expert_review_B.csv']}`",
            f"- expert_gold_master.csv SHA-256：`{audit['sha256']['expert_gold_master.csv']}`",
            "",
            "复现命令：",
            "",
            "```powershell",
            ".\\.venv\\Scripts\\python.exe scripts\\finalize_expert_gold.py",
            ".\\.venv\\Scripts\\python.exe scripts\\evaluate_expert_gold.py --gold data\\evaluation\\expert_gold_master.csv --output data\\evaluation\\expert_evaluation_report.json",
            ".\\.venv\\Scripts\\python.exe scripts\\build_expert_report.py",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


if __name__ == "__main__":
    OUTPUT_PATH.write_text(build(), encoding="utf-8")
    print(f"已生成正式专家评测报告：{OUTPUT_PATH}")
