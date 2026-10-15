from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.domain.models import PolicyCompileRequest  # noqa: E402
from app.services.policy_compiler import compile_policy  # noqa: E402

NEGATIVE_CASES = (
    ("NEG-001", "一般行政通知", "本通知规定会议室设备维护、值班安排和办公用品采购流程。"),
    ("NEG-002", "网络设备巡检规范", "机房交换机每季度巡检一次，故障后填写维修登记表并由管理员签字确认。"),
    ("NEG-003", "档案移交工作方案", "各部门应当按年度目录整理档案并完成移交，同时核对目录编号和文件数量。"),
    ("NEG-004", "公共体育场馆开放公告", "体育场馆周一至周五开放，入场人员应当遵守秩序并爱护公共设施。"),
    ("NEG-005", "城市道路施工通告", "施工期间部分道路临时围蔽，请过往车辆按照现场交通标志安全绕行。"),
    ("NEG-006", "软件采购验收办法", "采购的软件应完成安装测试和资产登记，并提交功能测试记录和验收报告。"),
    ("NEG-007", "公园绿化养护规范", "绿化养护包括浇灌、修剪和病虫害防治，作业完成后填写每日记录。"),
    ("NEG-008", "办公节能倡议", "离开办公室时请关闭照明与空调设备，下班前检查门窗和公共区域电源。"),
    ("NEG-009", "培训会议安排", "参会人员应在会议开始前完成签到，培训结束后按要求提交学习记录。"),
    ("NEG-010", "图书借阅规则", "图书借期三十日，逾期应办理续借手续，归还前请检查图书是否完好。"),
)


def _f1(true_positive: int, predicted: int, gold: int) -> dict[str, float | None]:
    precision = true_positive / predicted if predicted else None
    recall = true_positive / gold if gold else None
    score = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and precision + recall
        else None
    )
    return {
        "precision": round(precision, 4) if precision is not None else None,
        "recall": round(recall, 4) if recall is not None else None,
        "f1": round(score, 4) if score is not None else None,
    }


def _date_visible_in_text(value: str | None, text: str) -> bool:
    if not value:
        return False
    parsed = date.fromisoformat(value)
    variants = {
        value,
        f"{parsed.year}年{parsed.month}月{parsed.day}日",
        f"{parsed.year}年{parsed.month:02d}月{parsed.day:02d}日",
    }
    return any(item in text for item in variants)


def _assisted_context(row: dict[str, object]) -> dict[str, object]:
    context = row.get("assisted_input")
    if isinstance(context, dict):
        return context
    return {
        "benefit_hint": row.get("benefit_hint"),
        "effective_from": row.get("effective_from_input"),
        "effective_to": row.get("effective_to_input"),
    }


def _evaluate_track(
    rows: list[dict[str, object]], *, use_llm: bool, assisted: bool
) -> dict[str, object]:
    benefit_correct = 0
    benefit_total = 0
    parameter_counts = Counter()
    condition_counts = Counter()
    grounded_quotes = 0
    total_quotes = 0
    providers = Counter()
    details: list[dict[str, object]] = []
    start_total = start_correct = 0
    end_total = end_correct = 0
    missing_start_total = missing_start_correct = 0

    for row in rows:
        expected = row["expected"]
        if not isinstance(expected, dict):
            raise TypeError("expected must be an object")
        context = _assisted_context(row) if assisted else {}
        result = compile_policy(
            PolicyCompileRequest(
                source_id=str(row["source_id"]),
                title=str(row["title"]),
                source_text=str(row["text"]),
                benefit_hint=context.get("benefit_hint"),
                effective_from=(
                    date.fromisoformat(str(context["effective_from"]))
                    if context.get("effective_from")
                    else None
                ),
                effective_to=(
                    date.fromisoformat(str(context["effective_to"]))
                    if context.get("effective_to")
                    else None
                ),
                use_llm=use_llm,
            )
        )
        candidate = result.candidate
        benefit_evaluable = assisted or bool(row.get("unassisted_benefit_evaluable", True))
        if benefit_evaluable:
            benefit_total += 1
            benefit_correct += int(candidate.benefit_id == expected["benefit_id"])
        actual_start = candidate.effective_from.isoformat() if candidate.effective_from else None
        actual_end = candidate.effective_to.isoformat() if candidate.effective_to else None
        text = str(row["text"])
        expected_start = expected.get("effective_from")
        expected_end = expected.get("effective_to")
        if assisted or _date_visible_in_text(expected_start, text):
            start_total += 1
            start_correct += int(actual_start == expected_start)
        if assisted or _date_visible_in_text(expected_end, text):
            end_total += 1
            end_correct += int(actual_end == expected_end)
        if not expected_start:
            missing_start_total += 1
            missing_start_correct += int(
                any(item.code == "missing_effective_from" for item in result.validation)
            )

        predicted_parameters = {key: str(value) for key, value in candidate.parameters.items()}
        gold_parameters = {key: str(value) for key, value in expected["parameters"].items()}
        predicted_pairs = set(predicted_parameters.items())
        gold_pairs = set(gold_parameters.items())
        parameter_counts["tp"] += len(predicted_pairs & gold_pairs)
        parameter_counts["predicted"] += len(predicted_pairs)
        parameter_counts["gold"] += len(gold_pairs)
        predicted_fields = {item.field for item in candidate.conditions}
        gold_fields = set(expected["condition_fields"])
        condition_counts["tp"] += len(predicted_fields & gold_fields)
        condition_counts["predicted"] += len(predicted_fields)
        condition_counts["gold"] += len(gold_fields)
        for condition in candidate.conditions:
            total_quotes += 1
            grounded_quotes += int(condition.source_quote in text)
        providers[candidate.provider] += 1
        details.append(
            {
                "case_id": row["case_id"],
                "benefit_match": candidate.benefit_id == expected["benefit_id"],
                "effective_from": actual_start,
                "effective_to": actual_end,
                "predicted_parameters": candidate.parameters,
                "predicted_condition_fields": sorted(predicted_fields),
            }
        )

    count = len(rows)
    return {
        "track": "metadata_assisted_compilation" if assisted else "unassisted_text_extraction",
        "case_count": count,
        "providers": dict(providers),
        "benefit_accuracy": round(benefit_correct / max(benefit_total, 1), 4),
        "benefit_evaluable_cases": benefit_total,
        "benefit_context_dependent_cases": count - benefit_total,
        "effective_from_accuracy": round(start_correct / start_total, 4) if start_total else None,
        "effective_from_evaluable_cases": start_total,
        "effective_to_accuracy": round(end_correct / end_total, 4) if end_total else None,
        "effective_to_evaluable_cases": end_total,
        "missing_effective_from_guard_accuracy": (
            round(missing_start_correct / missing_start_total, 4) if missing_start_total else None
        ),
        "missing_effective_from_cases": missing_start_total,
        "parameter_pair": _f1(
            parameter_counts["tp"], parameter_counts["predicted"], parameter_counts["gold"]
        ),
        "condition_field": _f1(
            condition_counts["tp"], condition_counts["predicted"], condition_counts["gold"]
        ),
        "source_quote_grounding_rate": (
            round(grounded_quotes / total_quotes, 4) if total_quotes else None
        ),
        "details": details,
    }


def _evaluate_unknown_rejection() -> dict[str, object]:
    details: list[dict[str, object]] = []
    for case_id, title, text in NEGATIVE_CASES:
        result = compile_policy(
            PolicyCompileRequest(
                source_id=case_id,
                title=title,
                source_text=text,
                use_llm=False,
            )
        )
        passed = result.candidate.benefit_id == "unknown" and not result.publishable
        details.append(
            {
                "case_id": case_id,
                "passed": passed,
                "predicted_benefit_id": result.candidate.benefit_id,
            }
        )
    return {
        "dataset_origin": "project-authored synthetic out-of-domain negatives",
        "case_count": len(details),
        "passed": sum(bool(item["passed"]) for item in details),
        "accuracy": round(sum(bool(item["passed"]) for item in details) / len(details), 4),
        "details": details,
    }


def evaluate(path: Path, use_llm: bool) -> dict[str, object]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    return {
        "report_schema": "policy2rule-evaluation/2.0",
        "benchmark_role": (
            rows[0].get("dataset_role", "internally_curated_policy_compiler_benchmark")
            if rows
            else "empty"
        ),
        "case_count": len(rows),
        "unassisted_text_extraction": _evaluate_track(
            rows, use_llm=use_llm, assisted=False
        ),
        "metadata_assisted_compilation": _evaluate_track(
            rows, use_llm=use_llm, assisted=True
        ),
        "unknown_rejection": _evaluate_unknown_rejection(),
        "claim_boundary": (
            "主结果是不给benefit_hint和有效期元数据的原文抽取轨；辅助编译轨单独报告，"
            "不得把元数据回填计作模型抽取。标签由项目组按官方条款制作，未做外部双人盲标，"
            "且规则开发与本基准来源存在重叠，因此只用于回归验证，不宣称独立泛化性能。"
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="评测Policy2Rule候选编译器。")
    parser.add_argument(
        "--benchmark",
        type=Path,
        default=ROOT / "data" / "evaluation" / "policy_compiler_benchmark.jsonl",
    )
    parser.add_argument("--use-llm", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = evaluate(args.benchmark, args.use_llm)
    content = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(content + "\n", encoding="utf-8")
    print(content)


if __name__ == "__main__":
    main()
