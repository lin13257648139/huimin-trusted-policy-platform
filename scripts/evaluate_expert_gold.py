from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.domain.models import HouseholdProfile  # noqa: E402
from app.services.rule_engine import evaluate_profile  # noqa: E402
BENEFIT_IDS = ("B001", "B002", "B003", "B004", "B005")
ALLOWED = {"likely", "unlikely", "incomplete", "manual_review"}
AUTO_LABELS = {"likely", "unlikely"}


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _profile_key(profile_json: str) -> str:
    return json.dumps(
        json.loads(profile_json), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _metric_block(values: Counter[str]) -> dict[str, float | int | None]:
    return {
        "cases": values["total"],
        "strict_exact_accuracy": _ratio(values["exact"], values["total"]),
        "likely_precision": _ratio(values["true_likely"], values["predicted_likely"]),
        "likely_recall": _ratio(values["true_likely"], values["gold_likely"]),
        "high_risk_false_positive_rate": _ratio(
            values["false_positive"], values["predicted_likely"]
        ),
        "auto_coverage": _ratio(values["auto"], values["total"]),
        "selective_accuracy": _ratio(values["auto_correct"], values["auto"]),
        "unsafe_automation_rate": _ratio(values["auto_wrong"], values["auto"]),
        "manual_review_rate": _ratio(values["manual_review"], values["total"]),
        "incomplete_rate": _ratio(values["incomplete"], values["total"]),
        "abstention_rate": _ratio(values["abstention"], values["total"]),
    }


def evaluate(path: Path) -> dict[str, object]:
    if not path.exists():
        raise SystemExit("专家金标主表尚未生成；请先完成A/B盲评并运行merge_expert_reviews.py。")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise SystemExit("专家金标表为空。")
    original_record_count = len(rows)
    unique_rows: list[dict[str, str]] = []
    seen: dict[str, tuple[str, ...]] = {}
    for row in rows:
        missing = [benefit for benefit in BENEFIT_IDS if row.get(f"gold_{benefit}", "") not in ALLOWED]
        if missing:
            raise SystemExit(
                f"{row.get('case_id')} 尚未完成金标：{', '.join(missing)}。禁止输出不完整准确率。"
            )
        key = _profile_key(row["profile_json"])
        labels = tuple(row[f"gold_{benefit}"] for benefit in BENEFIT_IDS)
        if key in seen:
            if seen[key] != labels:
                raise SystemExit(
                    f"{row.get('case_id')} 与同画像重复案例的金标冲突；请先裁决后再评测。"
                )
            continue
        seen[key] = labels
        unique_rows.append(row)

    metrics: dict[str, object] = {}
    overall: Counter[str] = Counter()
    snapshot_exact = 0
    snapshot_total = 0
    by_benefit: dict[str, Counter[str]] = defaultdict(Counter)
    confusion: dict[str, Counter[str]] = defaultdict(Counter)
    for row in unique_rows:
        profile = HouseholdProfile.model_validate(json.loads(row["profile_json"]))
        snapshot, results, _ = evaluate_profile(profile)
        predicted = {item.benefit_id: item.status.value for item in results}
        if row.get("gold_policy_snapshot"):
            snapshot_total += 1
            snapshot_exact += int(snapshot.snapshot_id == row["gold_policy_snapshot"])
        for benefit in BENEFIT_IDS:
            gold = row[f"gold_{benefit}"]
            guess = predicted[benefit]
            exact = guess == gold
            values = by_benefit[benefit]
            for counter in (values, overall):
                counter["total"] += 1
                counter["exact"] += int(exact)
                counter["predicted_likely"] += int(guess == "likely")
                counter["gold_likely"] += int(gold == "likely")
                counter["true_likely"] += int(guess == "likely" and gold == "likely")
                counter["auto"] += int(guess in AUTO_LABELS)
                counter["auto_correct"] += int(guess in AUTO_LABELS and exact)
                counter["auto_wrong"] += int(guess in AUTO_LABELS and not exact)
                counter["manual_review"] += int(guess == "manual_review")
                counter["incomplete"] += int(guess == "incomplete")
                counter["abstention"] += int(guess not in AUTO_LABELS)
            false_positive = guess == "likely" and gold != "likely"
            values["false_positive"] += int(false_positive)
            overall["false_positive"] += int(false_positive)
            confusion[benefit][f"{gold}->{guess}"] += 1
    for benefit in BENEFIT_IDS:
        values = by_benefit[benefit]
        metrics[benefit] = _metric_block(values) | {
            "confusion": dict(sorted(confusion[benefit].items()))
        }
    return {
        "dataset": (
            path.resolve().relative_to(ROOT).as_posix()
            if path.resolve().is_relative_to(ROOT)
            else path.name
        ),
        "original_record_count": original_record_count,
        "unique_case_count": len(unique_rows),
        "duplicate_records_excluded": original_record_count - len(unique_rows),
        "decision_count": overall["total"],
        "overall": _metric_block(overall),
        "policy_snapshot_accuracy": _ratio(snapshot_exact, snapshot_total),
        "by_benefit": metrics,
        "interpretation": (
            "严格准确率把人工复核和信息不足也按四分类计算；自动覆盖率只统计likely/unlikely；"
            "选择性准确率衡量自动输出中的正确比例；高风险假阳性指系统给出likely但专家金标不是likely。"
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="只对完整专家金标集计算业务指标。")
    parser.add_argument(
        "--gold",
        type=Path,
        default=ROOT / "data" / "evaluation" / "expert_gold_master.csv",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = evaluate(args.gold)
    content = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(content, encoding="utf-8")
    print(content)


if __name__ == "__main__":
    main()
