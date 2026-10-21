from __future__ import annotations

import argparse
import json
from pathlib import Path

TARGETS = {
    "app/services/policy_compiler.py": 85.0,
    "app/services/policy_qa.py": 90.0,
    "app/main.py": 85.0,
}
TOTAL_TARGET = 90.0


def branch_percent(summary: dict[str, object]) -> float:
    total = int(summary.get("num_branches", 0))
    covered = int(summary.get("covered_branches", 0))
    return 100.0 if total == 0 else covered / total * 100


def main() -> None:
    parser = argparse.ArgumentParser(description="Enforce national-competition branch gates")
    parser.add_argument(
        "report", nargs="?", type=Path, default=Path("data/evaluation/coverage_report.json")
    )
    arguments = parser.parse_args()
    payload = json.loads(arguments.report.read_text(encoding="utf-8"))
    failures = []
    normalized_files = {
        name.replace("\\", "/"): details
        for name, details in payload.get("files", {}).items()
    }
    for module, target in TARGETS.items():
        summary = normalized_files.get(module, {}).get("summary")
        if not isinstance(summary, dict):
            failures.append(f"{module}: missing from coverage report")
            continue
        actual = branch_percent(summary)
        print(f"BRANCH_COVERAGE module={module} actual={actual:.2f}% target={target:.2f}%")
        if actual + 1e-9 < target:
            failures.append(f"{module}: {actual:.2f}% < {target:.2f}%")
    total = branch_percent(payload["totals"])
    print(f"BRANCH_COVERAGE module=TOTAL actual={total:.2f}% target={TOTAL_TARGET:.2f}%")
    if total + 1e-9 < TOTAL_TARGET:
        failures.append(f"TOTAL: {total:.2f}% < {TOTAL_TARGET:.2f}%")
    if failures:
        raise SystemExit("BRANCH_COVERAGE_GATE_FAILED: " + "; ".join(failures))
    print("BRANCH_COVERAGE_GATE_OK")


if __name__ == "__main__":
    main()
