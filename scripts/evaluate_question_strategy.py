from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean, median

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.domain.models import GuidanceDraft, GuidanceResponse, HouseholdProfile
from app.services.question_engine import (
    QUESTIONS,
    next_fixed_guidance_question,
    next_guidance_question,
)
from app.services.rule_engine import evaluate_profile

DATASET = ROOT / "data" / "evaluation" / "active_question_decision_cases.jsonl"
OUTPUT = ROOT / "data" / "evaluation" / "active_question_report.json"
TRACE_OUTPUT = ROOT / "data" / "evaluation" / "active_question_traces.jsonl"
COMPLETE_FORM_FIELDS = 17


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _status_map(profile: HouseholdProfile) -> dict[str, str]:
    _, results, _ = evaluate_profile(profile)
    return {item.benefit_id: item.status.value for item in results}


def _run_strategy(
    case_id: str,
    original: HouseholdProfile,
    strategy_name: str,
    chooser: Callable[[GuidanceDraft], GuidanceResponse],
) -> tuple[HouseholdProfile, list[dict[str, object]]]:
    available = original.model_dump(mode="json")
    draft_data: dict[str, object] = {
        "query_date": available["query_date"],
        "city": "广州市",
    }
    skipped: list[str] = []
    trace: list[dict[str, object]] = []
    for turn in range(1, len(QUESTIONS) + 2):
        draft_data["skipped_fields"] = list(skipped)
        response = chooser(GuidanceDraft.model_validate(draft_data))
        if response.next_question is None:
            break
        question = response.next_question
        field = question.field_id
        value = available.get(field)
        action = "answered" if value is not None else "skipped_unknown"
        if value is None:
            skipped.append(field)
        else:
            draft_data[field] = value
        after = chooser(GuidanceDraft.model_validate({**draft_data, "skipped_fields": skipped}))
        trace.append(
            {
                "case_id": case_id,
                "strategy": strategy_name,
                "turn": turn,
                "field_id": field,
                "action": action,
                "answer": value,
                "priority_score": question.priority_score,
                "expected_unknown_reduction": question.expected_unknown_reduction,
                "progress_before": response.progress,
                "progress_after": after.progress,
                "candidate_benefits_before": response.candidate_benefits,
            }
        )
    reconstructed = HouseholdProfile.model_validate(
        {key: value for key, value in draft_data.items() if key in HouseholdProfile.model_fields}
    )
    return reconstructed, trace


def _strategy_stats(counts: list[int]) -> dict[str, float | int]:
    return {
        "mean_questions": round(mean(counts), 3),
        "median_questions": median(counts),
        "minimum_questions": min(counts),
        "maximum_questions": max(counts),
    }


def main() -> None:
    cases = [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines() if line]
    dynamic_counts: list[int] = []
    fixed_counts: list[int] = []
    mismatches: dict[str, list[dict[str, object]]] = {
        "information_gain": [],
        "fixed_order": [],
    }
    urgent_misses = 0
    traces: list[dict[str, object]] = []
    for case in cases:
        case_id = case["case_id"]
        original = HouseholdProfile.model_validate(case["profile"])
        expected = _status_map(original)
        dynamic, dynamic_trace = _run_strategy(
            case_id, original, "information_gain", next_guidance_question
        )
        fixed, fixed_trace = _run_strategy(
            case_id, original, "fixed_order", next_fixed_guidance_question
        )
        traces.extend(dynamic_trace)
        traces.extend(fixed_trace)
        dynamic_counts.append(len(dynamic_trace))
        fixed_counts.append(len(fixed_trace))
        if original.urgent_event and not any(
            step["field_id"] == "urgent_event" for step in dynamic_trace
        ):
            urgent_misses += 1
        for name, reconstructed in (("information_gain", dynamic), ("fixed_order", fixed)):
            actual = _status_map(reconstructed)
            if expected != actual:
                mismatches[name].append(
                    {"case_id": case_id, "expected": expected, "actual": actual}
                )

    dynamic_mean = mean(dynamic_counts)
    fixed_mean = mean(fixed_counts)
    report = {
        "schema_version": "2.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset": "data/evaluation/active_question_decision_cases.jsonl",
        "dataset_sha256": _sha256(DATASET),
        "dataset_role": "project-authored synthetic decision-path benchmark; not a human trial",
        "cases": len(cases),
        "execution": "both strategies executed turn-by-turn against each case",
        "trace_file": "data/evaluation/active_question_traces.jsonl",
        "trace_rows": len(traces),
        "strategies": {
            "complete_form": {
                "questions_per_case": COMPLETE_FORM_FIELDS,
                "definition": "居民端完整表单中可填写的17个业务字段（含条件字段）",
            },
            "fixed_order": _strategy_stats(fixed_counts),
            "information_gain": _strategy_stats(dynamic_counts),
        },
        "question_reduction_vs_complete_form": round(
            1 - dynamic_mean / COMPLETE_FORM_FIELDS, 4
        ),
        "question_reduction_vs_executed_fixed_order": round(
            1 - dynamic_mean / fixed_mean, 4
        ),
        "status_consistency": {
            name: round(1 - len(items) / max(len(cases), 1), 4)
            for name, items in mismatches.items()
        },
        "urgent_question_miss_rate": round(
            urgent_misses
            / max(
                sum(
                    bool(HouseholdProfile.model_validate(c["profile"]).urgent_event)
                    for c in cases
                ),
                1,
            ),
            4,
        ),
        "mismatches": {name: items[:20] for name, items in mismatches.items()},
        "limitations": [
            "数据为项目组构造的决策路径案例，不代表真人完成率或真实填写时间。",
            "动态策略与固定策略都实际逐轮运行；轨迹保存了问题、回答/跳过与前后进度。",
            "减题率只描述这120个合成路径；不得外推为真实用户效果。",
        ],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    TRACE_OUTPUT.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in traces),
        encoding="utf-8",
    )
    print(
        "QUESTION_STRATEGY_OK "
        f"cases={len(cases)} dynamic_mean={dynamic_mean:.3f} fixed_mean={fixed_mean:.3f} "
        f"trace_rows={len(traces)} urgent_miss={report['urgent_question_miss_rate']:.1%}"
    )


if __name__ == "__main__":
    main()
