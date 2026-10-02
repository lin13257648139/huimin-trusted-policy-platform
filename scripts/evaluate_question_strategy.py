from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.domain.models import GuidanceDraft, HouseholdProfile
from app.services.question_engine import QUESTIONS, next_guidance_question
from app.services.rule_engine import evaluate_profile

DATASET = ROOT / "data" / "processed" / "synthetic_conformance_cases.jsonl"
OUTPUT = ROOT / "data" / "evaluation" / "active_question_report.json"
COMPLETE_FORM_FIELDS = 17


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _status_map(profile: HouseholdProfile) -> dict[str, str]:
    _, results, _ = evaluate_profile(profile)
    return {item.benefit_id: item.status.value for item in results}


def main() -> None:
    cases = [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines() if line]
    question_counts: list[int] = []
    fixed_counts: list[int] = []
    mismatches: list[dict[str, object]] = []
    urgent_misses = 0
    for case in cases:
        original = HouseholdProfile.model_validate(case["profile"])
        available = original.model_dump(mode="json")
        draft_data: dict[str, object] = {"query_date": available["query_date"], "city": "广州市"}
        skipped: list[str] = []
        asked: list[str] = []
        for _ in range(len(QUESTIONS) + 1):
            draft_data["skipped_fields"] = skipped
            response = next_guidance_question(GuidanceDraft.model_validate(draft_data))
            if response.next_question is None:
                break
            field = response.next_question.field_id
            asked.append(field)
            value = available.get(field)
            if value is None:
                skipped.append(field)
            else:
                draft_data[field] = value
        question_counts.append(len(asked))
        fixed_counts.append(len(QUESTIONS))
        if original.urgent_event and "urgent_event" not in asked:
            urgent_misses += 1
        reconstructed = HouseholdProfile.model_validate(
            {
                key: value
                for key, value in draft_data.items()
                if key in HouseholdProfile.model_fields
            }
        )
        expected = _status_map(original)
        actual = _status_map(reconstructed)
        if expected != actual:
            mismatches.append({"case_id": case["case_id"], "expected": expected, "actual": actual})

    reduction_vs_complete = 1 - mean(question_counts) / COMPLETE_FORM_FIELDS
    reduction_vs_fixed = 1 - mean(question_counts) / mean(fixed_counts)
    report = {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset": "data/processed/synthetic_conformance_cases.jsonl",
        "dataset_sha256": _sha256(DATASET),
        "dataset_role": "engine_conformance_only; synthetic, not a human trial",
        "cases": len(cases),
        "strategies": {
            "complete_form": {
                "questions_per_case": COMPLETE_FORM_FIELDS,
                "definition": "当前居民端完整表单中可填写的17个业务字段（含条件字段）",
            },
            "fixed_order_relevant": {"questions_per_case": len(QUESTIONS)},
            "information_gain": {
                "mean_questions": round(mean(question_counts), 3),
                "median_questions": median(question_counts),
                "minimum_questions": min(question_counts),
                "maximum_questions": max(question_counts),
            },
        },
        "question_reduction_vs_complete_form": round(reduction_vs_complete, 4),
        "question_reduction_vs_fixed_relevant": round(reduction_vs_fixed, 4),
        "status_consistency": round(1 - len(mismatches) / max(len(cases), 1), 4),
        "urgent_question_miss_rate": round(urgent_misses / max(sum(bool(HouseholdProfile.model_validate(c["profile"]).urgent_event) for c in cases), 1), 4),
        "mismatches": mismatches[:20],
        "limitations": [
            "数据为确定性规则引擎合成一致性案例，不代表真人完成率或真实填写时间。",
            "问题价值采用可消除UNKNOWN事项数、急难优先级、填写成本和敏感度的可解释评分。",
        ],
    }
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        "QUESTION_STRATEGY_OK "
        f"cases={len(cases)} reduction={report['question_reduction_vs_complete_form']:.1%} "
        f"consistency={report['status_consistency']:.1%} urgent_miss={report['urgent_question_miss_rate']:.1%}"
    )


if __name__ == "__main__":
    main()
