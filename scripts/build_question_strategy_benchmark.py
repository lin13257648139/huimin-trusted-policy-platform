from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "data" / "processed" / "synthetic_conformance_cases.jsonl"
OUTPUT = ROOT / "data" / "evaluation" / "active_question_decision_cases.jsonl"


def main() -> None:
    source = [json.loads(line) for line in SOURCE.read_text(encoding="utf-8").splitlines() if line]
    cases = []
    scenarios = ("asset_block", "member_block", "rigid_block", "temporary_block")
    for index in range(120):
        profile = dict(source[index % len(source)]["profile"])
        scenario = scenarios[index % len(scenarios)]
        if scenario == "asset_block":
            profile.update({"assets_eligible": False, "urgent_event": False})
            profile["urgent_event_date"] = None
        elif scenario == "member_block":
            profile.update({"member_scope_confirmed": False, "urgent_event": False})
            profile["urgent_event_date"] = None
        elif scenario == "rigid_block":
            profile.update({"rigid_expenses_12m": 0, "urgent_event": False})
            profile["urgent_event_date"] = None
        else:
            profile.update({"urgent_event": True, "basic_life_interrupted": False})
            profile["urgent_event_date"] = profile.get("urgent_event_date") or "2026-09-20"
        cases.append(
            {
                "case_id": f"AQ-{index + 1:03d}",
                "scenario": scenario,
                "dataset_role": "project-authored synthetic decision-path benchmark",
                "source_case_id": source[index % len(source)]["case_id"],
                "profile": profile,
            }
        )
    OUTPUT.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in cases),
        encoding="utf-8",
    )
    print(f"QUESTION_BENCHMARK_OK cases={len(cases)} output={OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
