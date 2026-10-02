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


def evaluate(path: Path, use_llm: bool) -> dict[str, object]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    benefit_correct = 0
    start_correct = 0
    end_correct = 0
    date_error_correct = 0
    parameter_counts = Counter()
    condition_counts = Counter()
    grounded_quotes = 0
    total_quotes = 0
    details = []
    providers = Counter()
    for row in rows:
        result = compile_policy(
            PolicyCompileRequest(
                source_id=row["source_id"],
                title=row["title"],
                source_text=row["text"],
                benefit_hint=row.get("benefit_hint"),
                effective_from=(date.fromisoformat(row["effective_from_input"]) if row.get("effective_from_input") else None),
                effective_to=(date.fromisoformat(row["effective_to_input"]) if row.get("effective_to_input") else None),
                use_llm=use_llm,
            )
        )
        candidate = result.candidate
        expected = row["expected"]
        benefit_correct += int(candidate.benefit_id == expected["benefit_id"])
        actual_start = candidate.effective_from.isoformat() if candidate.effective_from else None
        actual_end = candidate.effective_to.isoformat() if candidate.effective_to else None
        start_correct += int(actual_start == expected["effective_from"])
        end_correct += int(actual_end == expected["effective_to"])
        has_date_error = any(item.code == "missing_effective_from" for item in result.validation)
        date_error_correct += int(has_date_error == expected["date_error"])
        predicted_parameters = {key: str(value) for key, value in candidate.parameters.items()}
        gold_parameters = {key: str(value) for key, value in expected["parameters"].items()}
        predicted_parameter_pairs = set(predicted_parameters.items())
        gold_parameter_pairs = set(gold_parameters.items())
        parameter_counts["tp"] += len(predicted_parameter_pairs & gold_parameter_pairs)
        parameter_counts["predicted"] += len(predicted_parameter_pairs)
        parameter_counts["gold"] += len(gold_parameter_pairs)
        predicted_fields = {item.field for item in candidate.conditions}
        gold_fields = set(expected["condition_fields"])
        condition_counts["tp"] += len(predicted_fields & gold_fields)
        condition_counts["predicted"] += len(predicted_fields)
        condition_counts["gold"] += len(gold_fields)
        for condition in candidate.conditions:
            total_quotes += 1
            grounded_quotes += int(condition.source_quote in row["text"])
        providers[candidate.provider] += 1
        details.append(
            {
                "case_id": row["case_id"],
                "benefit_match": candidate.benefit_id == expected["benefit_id"],
                "effective_from_match": actual_start == expected["effective_from"],
                "effective_to_match": actual_end == expected["effective_to"],
                "predicted_parameters": candidate.parameters,
                "predicted_condition_fields": sorted(predicted_fields),
            }
        )
    count = len(rows)
    return {
        "benchmark_role": rows[0].get("dataset_role", "internally_curated_policy_compiler_benchmark") if rows else "empty",
        "case_count": count,
        "providers": dict(providers),
        "benefit_accuracy": round(benefit_correct / count, 4),
        "effective_from_accuracy": round(start_correct / count, 4),
        "effective_to_accuracy": round(end_correct / count, 4),
        "missing_date_guard_accuracy": round(date_error_correct / count, 4),
        "parameter_pair": _f1(
            parameter_counts["tp"], parameter_counts["predicted"], parameter_counts["gold"]
        ),
        "condition_field": _f1(
            condition_counts["tp"], condition_counts["predicted"], condition_counts["gold"]
        ),
        "source_quote_grounding_rate": round(grounded_quotes / total_quotes, 4)
        if total_quotes
        else None,
        "details": details,
        "warning": (
            "本基准标签由项目组从官方条款编制，尚不是独立双人盲标结果；不得包装为外部专家评测。"
            if rows and rows[0].get("dataset_role") == "real_official_clause_project_authored_gold"
            else "这是内部合成条款基准，只证明编译管线可重复；正式结果必须增加真实政策条款双人标注测试集。"
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
        args.output.write_text(content, encoding="utf-8")
    print(content)


if __name__ == "__main__":
    main()
