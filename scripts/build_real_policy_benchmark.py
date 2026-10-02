from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "app" / "data" / "evidence.json"
OUTPUT = ROOT / "data" / "evaluation" / "policy_compiler_real_benchmark.jsonl"


# These labels are project-authored from official clauses.  They are not presented
# as independent expert annotations; a later human double-review may replace them.
GOLD = {
    "E-CN-001-DIBAO": ("B002", {}, ["per_capita_monthly_income", "assets_eligible"]),
    "E-CN-001-EDGE": ("B003", {}, ["per_capita_monthly_income", "assets_eligible"]),
    "E-CN-001-RIGID": ("B004", {}, ["per_capita_annual_income", "assets_eligible", "rigid_expenses_12m"]),
    "E-GZ-002-ASSET": ("B002", {}, ["assets_eligible"]),
    "E-GZ-003-STANDARD": (
        "B002",
        {"income_standard_monthly_per_capita": "1327.00"},
        ["per_capita_monthly_income"],
    ),
    "E-GZ-004-EXPENSE": ("B004", {}, ["per_capita_annual_income"]),
    "E-GD-002-EDGE": (
        "B003",
        {"income_multiplier": "1.5"},
        ["is_local_hukou", "per_capita_monthly_income"],
    ),
    "E-GD-002-RIGID": (
        "B004",
        {"rigid_expense_income_ratio": "0.6"},
        ["is_local_hukou", "per_capita_annual_income", "rigid_expenses_12m"],
    ),
    "E-GZ-005-URGENT": (
        "B005",
        {"urgent_event_days": "31"},
        ["urgent_event", "urgent_event_date"],
    ),
    "E-GZ-005-RESIDENCE": ("B005", {}, ["residence_proof"]),
    "E-GZ-009-ASSET": ("B002", {}, ["assets_eligible"]),
}


def main() -> None:
    evidence = {item["evidence_id"]: item for item in json.loads(EVIDENCE.read_text(encoding="utf-8"))}
    lines = []
    for index, (evidence_id, (benefit_id, parameters, fields)) in enumerate(GOLD.items(), start=1):
        item = evidence[evidence_id]
        lines.append(
            json.dumps(
                {
                    "case_id": f"PCR-R{index:03d}",
                    "dataset_role": "real_official_clause_project_authored_gold",
                    "evidence_id": evidence_id,
                    "source_id": item["source_id"],
                    "source_sha256": item["source_sha256"],
                    "title": item["title"],
                    "text": item["verbatim_quote"],
                    "benefit_hint": benefit_id,
                    "effective_from_input": item.get("effective_from"),
                    "effective_to_input": item.get("effective_to"),
                    "expected": {
                        "benefit_id": benefit_id,
                        "effective_from": item.get("effective_from"),
                        "effective_to": item.get("effective_to"),
                        "parameters": parameters,
                        "condition_fields": fields,
                        "date_error": not bool(item.get("effective_from")),
                    },
                },
                ensure_ascii=False,
            )
        )
    OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"REAL_POLICY_BENCHMARK_OK cases={len(lines)} output={OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
