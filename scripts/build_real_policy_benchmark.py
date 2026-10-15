from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "app" / "data" / "evidence.json"
OUTPUT = ROOT / "data" / "evaluation" / "policy_compiler_real_benchmark.jsonl"


# These labels are project-authored from official clauses.  They are not presented
# as independent expert annotations; a later human double-review may replace them.
GOLD = {
    "E-GZ-001-SCOPE": ("B001", {}, []),
    "E-GZ-001-MATERIALS": ("B001", {}, []),
    "E-GZ-001-DEADLINE": ("B001", {}, []),
    "E-CN-001-DIBAO": ("B002", {}, ["per_capita_monthly_income", "assets_eligible"]),
    "E-CN-001-EDGE": ("B003", {}, ["per_capita_monthly_income", "assets_eligible"]),
    "E-CN-001-RIGID": ("B004", {}, ["per_capita_annual_income", "assets_eligible", "rigid_expenses_12m"]),
    "E-CN-001-PRIVACY": ("B001", {}, []),
    "E-GZ-002-CURRENT": ("B002", {}, []),
    "E-GZ-002-ASSET": ("B002", {}, ["assets_eligible"]),
    "E-GZ-003-STANDARD": (
        "B002",
        {
            "income_standard_monthly_per_capita": "1327.00",
            "edge_standard_monthly_per_capita": "1990.50",
            "income_multiplier": "1.5",
        },
        ["per_capita_monthly_income"],
    ),
    "E-GZ-004-EXPENSE": ("B004", {}, ["per_capita_annual_income"]),
    "E-GD-002-EDGE": (
        "B003",
        {"income_multiplier": "1.5"},
        ["is_local_hukou", "per_capita_monthly_income", "member_scope_confirmed"],
    ),
    "E-GD-002-RIGID": (
        "B004",
        {"rigid_expense_income_ratio": "0.6"},
        [
            "is_local_hukou",
            "per_capita_annual_income",
            "rigid_expenses_12m",
            "member_scope_confirmed",
        ],
    ),
    "E-GZ-005-URGENT": (
        "B005",
        {"urgent_event_days": "31"},
        ["urgent_event", "urgent_event_date"],
    ),
    "E-GZ-005-RESIDENCE": ("B005", {}, ["residence_proof"]),
    "E-GZ-008-INCOME": ("B004", {}, []),
    "E-GZ-009-LEGACY": ("B002", {}, []),
    "E-GZ-009-ASSET": ("B002", {}, ["assets_eligible"]),
    "E-GD-004-A-DUAL-ASSESSMENT": ("B002", {}, []),
    "E-GD-004-A-THRESHOLD": ("B002", {}, ["per_capita_monthly_income"]),
    "E-GD-004-A-INCOME": ("B002", {}, []),
    "E-GD-004-A-NONSTACK": ("B002", {}, []),
    "E-GD-004-A-INCOME-DETAIL": ("B002", {}, []),
    "E-GD-004-A-STRUCTURE": ("B002", {}, []),
    "E-GD-004-A-OBLIGORS": ("B002", {}, []),
    "E-GD-004-A-LIVING": ("B002", {}, []),
    "E-GD-004-A-VEHICLE-EXCLUSION": ("B002", {}, []),
    "E-GD-004-A-FORMULA": ("B002", {}, []),
    "E-GD-002-SEPARATE-RECOGNITION": (
        "B003",
        {},
        ["member_scope_confirmed", "assets_eligible"],
    ),
    "E-GD-002-DIBAO-EXCLUSION": ("B002", {}, []),
}


def _subclause_gold(
    text: str,
    benefit_id: str,
) -> tuple[dict[str, str], list[str]]:
    """Apply the documented project annotation guide to an exact subclause."""

    parameters: dict[str, str] = {}
    fields: list[str] = []
    if "1327元" in text and "最低生活保障" in text:
        parameters["income_standard_monthly_per_capita"] = "1327.00"
    if "1.5倍" in text:
        parameters["income_multiplier"] = "1.5"
    if "1990.5元" in text and "最低生活保障边缘" in text:
        parameters["edge_standard_monthly_per_capita"] = "1990.50"
    if "60%" in text and benefit_id == "B004":
        parameters["rigid_expense_income_ratio"] = "0.6"
    if "申请日前1个月" in text and benefit_id == "B005":
        parameters["urgent_event_days"] = "31"
    if "人均" in text and "收入" in text and ("低于" in text or "以下" in text):
        fields.append(
            "per_capita_annual_income" if "年收入" in text else "per_capita_monthly_income"
        )
    if "财产" in text:
        fields.append("assets_eligible")
    if "户籍" in text:
        fields.append("is_local_hukou")
    if benefit_id == "B004" and ("刚性支出" in text or "必需支出" in text):
        fields.append("rigid_expenses_12m")
    if "共同生活" in text:
        fields.append("member_scope_confirmed")
    if benefit_id == "B005" and ("急难" in text or "突发急病" in text):
        fields.append("urgent_event")
    if benefit_id == "B005" and "申请日前1个月" in text:
        fields.append("urgent_event_date")
    if benefit_id == "B005" and ("居住证" in text or "连续居住" in text):
        fields.append("residence_proof")
    return parameters, list(dict.fromkeys(fields))


def _subclause_benefit(text: str, parent_benefit: str) -> str:
    if any(marker in text for marker in ("支出型困难", "刚性支出")):
        return "B004"
    if any(marker in text for marker in ("低保边缘", "最低生活保障边缘")):
        return "B003"
    if any(marker in text for marker in ("临时救助", "急难型")):
        return "B005"
    if "最低生活保障" in text or "低保" in text:
        return "B002"
    if "低收入人口" in text or "低收入监测" in text:
        return "B001"
    return parent_benefit


def _benefit_evaluable_without_hint(title: str, text: str, benefit_id: str) -> bool:
    """Whether title + fragment contains enough information to label the matter.

    A fragment from a mixed policy document or a statistics bulletin may be useful
    compile context, but its intended target matter cannot be inferred without the
    document ingestion metadata. Such rows remain in the assisted track and are
    excluded only from the unassisted matter-classification denominator.
    """

    specific_hits = {
        "B002": any(marker in text for marker in ("最低生活保障家庭", "最低生活保障标准", "低保")),
        "B003": any(marker in text for marker in ("低保边缘", "最低生活保障边缘")),
        "B004": any(marker in text for marker in ("刚性支出", "支出型困难")),
        "B005": any(marker in text for marker in ("临时救助", "急难型")),
    }
    if benefit_id == "B001":
        return any(marker in text + title for marker in ("低收入人口", "低收入监测", "一件事"))
    if benefit_id == "B002":
        if "申请家庭生活状况综合评估指标" in title:
            return True
        return specific_hits["B002"] and sum(specific_hits.values()) == 1
    if benefit_id == "B003":
        return specific_hits["B003"] and not specific_hits["B004"]
    if benefit_id == "B004":
        return specific_hits["B004"]
    if benefit_id == "B005":
        return specific_hits["B005"]
    return False


def main() -> None:
    evidence = {item["evidence_id"]: item for item in json.loads(EVIDENCE.read_text(encoding="utf-8"))}
    cases = []
    for evidence_id, (benefit_id, parameters, fields) in GOLD.items():
        item = evidence[evidence_id]
        cases.append((item, item["verbatim_quote"], benefit_id, parameters, fields, "full_fragment"))
        subclauses = [
            part.strip()
            for part in re.split(r"(?<=[；。])", item["verbatim_quote"])
            if len(part.strip()) >= 20
        ]
        # Add only proper subclauses, never duplicate the complete evidence fragment.
        if len(subclauses) > 1:
            for text in subclauses[1:]:
                sub_benefit = _subclause_benefit(text, benefit_id)
                sub_parameters, sub_fields = _subclause_gold(text, sub_benefit)
                cases.append((item, text, sub_benefit, sub_parameters, sub_fields, "exact_subclause"))

    if len(cases) < 50:
        raise RuntimeError(f"真实政策条款基准不足50例：{len(cases)}")
    lines = []
    for index, (item, text, benefit_id, parameters, fields, granularity) in enumerate(
        cases, start=1
    ):
        lines.append(
            json.dumps(
                {
                    "case_id": f"PCR-R{index:03d}",
                    "dataset_role": "real_official_clause_project_authored_gold",
                    "annotation_method": "project_annotation_guide_v2",
                    "granularity": granularity,
                    "unassisted_benefit_evaluable": _benefit_evaluable_without_hint(
                        item["title"], text, benefit_id
                    ),
                    "evidence_id": item["evidence_id"],
                    "source_id": item["source_id"],
                    "source_sha256": item["source_sha256"],
                    "title": item["title"],
                    "text": text,
                    "assisted_input": {
                        "benefit_hint": benefit_id,
                        "effective_from": item.get("effective_from"),
                        "effective_to": item.get("effective_to"),
                    },
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
