from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.domain.models import HouseholdProfile  # noqa: E402
from app.services.rule_engine import evaluate_profile  # noqa: E402


DATASET = ROOT / "data" / "processed" / "synthetic_conformance_cases.jsonl"


def main() -> None:
    total = 0
    snapshot_ok = 0
    status_checks = 0
    status_ok = 0
    categories: Counter[str] = Counter()

    with DATASET.open("r", encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            total += 1
            categories[record["category"]] += 1
            profile = HouseholdProfile.model_validate(record["profile"])
            snapshot, results, _ = evaluate_profile(profile)
            snapshot_ok += snapshot.snapshot_id == record["expected_policy_snapshot"]
            actual = {item.benefit_id: item.status.value for item in results}
            for benefit_id, expected in record["expected_status"].items():
                status_checks += 1
                status_ok += actual[benefit_id] == expected

    report = {
        "dataset": "synthetic_conformance_cases",
        "cases": total,
        "policy_snapshot_accuracy": snapshot_ok / total if total else 0,
        "status_regression_accuracy": status_ok / status_checks if status_checks else 0,
        "categories": dict(categories),
        "warning": "这是确定性引擎回归一致性，不是专家标注的业务准确率。",
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if snapshot_ok != total or status_ok != status_checks:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

