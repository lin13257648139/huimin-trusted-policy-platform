from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
METHODS = {"baseline", "system"}
NUMERIC_FIELDS = (
    "success",
    "time_seconds",
    "question_count",
    "comprehension_correct",
    "confidence_1_5",
)


def _mean(values: list[float]) -> float | None:
    return round(statistics.mean(values), 3) if values else None


def _ci95(values: list[float]) -> list[float] | None:
    if len(values) < 2:
        return None
    center = statistics.mean(values)
    margin = 1.96 * statistics.stdev(values) / (len(values) ** 0.5)
    return [round(center - margin, 3), round(center + margin, 3)]


def analyze(path: Path) -> dict[str, object]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise SystemExit("试点记录为空，不能生成应用效果结论。")
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for index, row in enumerate(rows, 2):
        method = row.get("method", "").strip()
        if method not in METHODS:
            raise SystemExit(f"第{index}行method必须是baseline或system。")
        parsed: dict[str, object] = dict(row)
        for field in NUMERIC_FIELDS:
            try:
                parsed[field] = float(row[field])
            except (KeyError, TypeError, ValueError):
                raise SystemExit(f"第{index}行{field}为空或不是数字。") from None
        if parsed["success"] not in {0.0, 1.0} or parsed["comprehension_correct"] not in {
            0.0,
            1.0,
        }:
            raise SystemExit(f"第{index}行成功/理解字段只能是0或1。")
        if not 1 <= float(parsed["confidence_1_5"]) <= 5:
            raise SystemExit(f"第{index}行confidence_1_5必须在1到5之间。")
        grouped[method].append(parsed)
    if not all(grouped[method] for method in METHODS):
        raise SystemExit("baseline和system都必须至少有一条记录。")

    summary: dict[str, object] = {}
    for method in sorted(METHODS):
        items = grouped[method]
        summary[method] = {
            "observations": len(items),
            "participants": len({str(item["participant_id"]) for item in items}),
            **{
                field: {
                    "mean": _mean([float(item[field]) for item in items]),
                    "ci95": _ci95([float(item[field]) for item in items]),
                }
                for field in NUMERIC_FIELDS
            },
        }
    baseline = summary["baseline"]
    system = summary["system"]
    baseline_time = baseline["time_seconds"]["mean"]
    system_time = system["time_seconds"]["mean"]
    time_reduction = (
        round((baseline_time - system_time) / baseline_time, 4) if baseline_time else None
    )
    return {
        "study_type": "small_scale_within_subject_usability_pilot",
        "source": str(path),
        "summary": summary,
        "system_vs_baseline": {
            "time_reduction_rate": time_reduction,
            "success_rate_difference": round(
                system["success"]["mean"] - baseline["success"]["mean"], 4
            ),
            "comprehension_difference": round(
                system["comprehension_correct"]["mean"]
                - baseline["comprehension_correct"]["mean"],
                4,
            ),
        },
        "warning": "小样本试点只能作为可用性和应用效果初证，不能外推到全体困难群众。",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="分析真实填写的小规模对照试点记录。")
    parser.add_argument(
        "--input",
        type=Path,
        default=ROOT / "data" / "evaluation" / "pilot_observations.csv",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = analyze(args.input)
    content = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(content, encoding="utf-8")
    print(content)


if __name__ == "__main__":
    main()
