from __future__ import annotations

import json
from pathlib import Path

from scripts.evaluation_stats import rate_metric, wilson_interval

ROOT = Path(__file__).resolve().parents[1]


def _jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_wilson_interval_is_bounded_and_non_degenerate() -> None:
    interval = wilson_interval(80, 100)
    assert 0 < interval["lower"] < 0.8 < interval["upper"] < 1
    assert rate_metric(0, 0)["estimate"] is None


def test_stage2_frozen_sets_meet_scale_and_policy_file_isolation() -> None:
    profiles = _jsonl(ROOT / "data/evaluation/profile_extraction_benchmark.jsonl")
    policies = _jsonl(ROOT / "data/evaluation/policy_compiler_real_benchmark.jsonl")
    safety = _jsonl(ROOT / "data/evaluation/high_risk_safety_benchmark.jsonl")
    retrieval = json.loads(
        (ROOT / "data/evaluation/retrieval_benchmark.json").read_text(encoding="utf-8")
    )
    intent = json.loads((ROOT / "data/ml/intent_dataset.json").read_text(encoding="utf-8"))
    ocr = json.loads(
        (ROOT / "data/evaluation/ocr_synthetic/manifest.json").read_text(encoding="utf-8")
    )

    assert len(profiles) >= 300
    assert len(safety) >= 300
    assert sum(row["split"] == "frozen_final_test" for row in policies) >= 120
    development_sources = {
        row["source_id"] for row in policies if row["split"] == "development"
    }
    final_sources = {
        row["source_id"] for row in policies if row["split"] == "frozen_final_test"
    }
    assert development_sources.isdisjoint(final_sources)
    assert sum(
        row["split"] == "frozen_final_test" for row in retrieval["queries"]
    ) >= 100
    assert retrieval["policy_file_isolation"]["disjoint"] is True
    assert sum(len(group["test"]) for group in intent["labels"].values()) >= 200
    assert len(ocr) >= 100
    assert len({row["layout"] for row in ocr}) >= 10
