from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
OUTPUT = ROOT / "data" / "evaluation" / "stage2_split_manifest.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line
    ]


def main() -> None:
    from scripts.build_real_policy_benchmark import main as build_policy
    from scripts.build_safety_benchmark import main as build_safety
    from scripts.generate_ai_benchmark import main as build_ai
    from scripts.generate_ocr_benchmark import main as build_ocr

    build_ai()
    build_policy()
    build_safety()
    build_ocr()

    profile_path = ROOT / "data" / "evaluation" / "profile_extraction_benchmark.jsonl"
    retrieval_path = ROOT / "data" / "evaluation" / "retrieval_benchmark.json"
    intent_path = ROOT / "data" / "ml" / "intent_dataset.json"
    policy_path = ROOT / "data" / "evaluation" / "policy_compiler_real_benchmark.jsonl"
    safety_path = ROOT / "data" / "evaluation" / "high_risk_safety_benchmark.jsonl"
    ocr_manifest_path = ROOT / "data" / "evaluation" / "ocr_synthetic" / "manifest.json"

    profiles = _jsonl(profile_path)
    retrieval = json.loads(retrieval_path.read_text(encoding="utf-8"))
    intent = json.loads(intent_path.read_text(encoding="utf-8"))
    policies = _jsonl(policy_path)
    safety = _jsonl(safety_path)
    ocr = json.loads(ocr_manifest_path.read_text(encoding="utf-8"))

    policy_development = {
        row["source_id"] for row in policies if row["split"] == "development"
    }
    policy_final = {
        row["source_id"] for row in policies if row["split"] == "frozen_final_test"
    }
    if policy_development & policy_final:
        raise RuntimeError("Policy2Rule政策文件分组不独立")
    retrieval_split = retrieval["policy_file_isolation"]
    if set(retrieval_split["development_source_ids"]) & set(
        retrieval_split["frozen_final_source_ids"]
    ):
        raise RuntimeError("检索政策文件分组不独立")

    intent_test = sum(len(group["test"]) for group in intent["labels"].values())
    final_retrieval = sum(
        row["split"] == "frozen_final_test" for row in retrieval["queries"]
    )
    final_policy = sum(row["split"] == "frozen_final_test" for row in policies)
    requirements = {
        "retrieval_final_queries": final_retrieval >= 100,
        "intent_final_cases": intent_test >= 200,
        "profile_final_cases": len(profiles) >= 300,
        "ocr_final_images": len(ocr) >= 100,
        "ocr_layouts": len({row["layout"] for row in ocr}) >= 10,
        "policy2rule_final_clauses": final_policy >= 120,
        "safety_final_cases": len(safety) >= 300,
        "policy_file_isolation": not bool(policy_development & policy_final),
        "retrieval_file_isolation": retrieval_split["disjoint"] is True,
    }
    if not all(requirements.values()):
        raise RuntimeError(f"第二阶段冻结集验收失败：{requirements}")

    datasets = []
    for path, count in (
        (profile_path, len(profiles)),
        (retrieval_path, len(retrieval["queries"])),
        (intent_path, intent_test),
        (policy_path, len(policies)),
        (safety_path, len(safety)),
        (ocr_manifest_path, len(ocr)),
    ):
        datasets.append(
            {
                "path": path.relative_to(ROOT).as_posix(),
                "sha256": _sha256(path),
                "records": count,
            }
        )
    report = {
        "schema_version": "stage2-frozen-splits/1.0",
        "frozen_on": "2026-10-16",
        "label_independence": (
            "项目组生成或标注；没有外部专家、真人试点或独立第三方标注"
        ),
        "requirements": requirements,
        "policy_file_isolation": {
            "policy2rule": {
                "development_source_ids": sorted(policy_development),
                "frozen_final_source_ids": sorted(policy_final),
                "overlap": [],
            },
            "retrieval": retrieval_split,
            "rule": "同一政策source_id及其任何条款、切片或改写只能属于一个分组",
        },
        "template_isolation": {
            "intent": intent["freeze"],
            "profile_template_families": sorted(
                {row["template_family"] for row in profiles}
            ),
        },
        "category_counts": {
            "profile": dict(Counter(row["category"] for row in profiles)),
            "safety": dict(Counter(row["category"] for row in safety)),
            "ocr_layout": dict(Counter(row["layout"] for row in ocr)),
            "ocr_material": dict(Counter(row["material_type"] for row in ocr)),
        },
        "datasets": datasets,
        "claim_boundary": (
            "冻结仅证明文件级隔离、规模与哈希稳定；内部合成或项目组标签不能替代外部专家标注。"
        ),
    }
    OUTPUT.write_bytes(
        (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    )
    print(
        "STAGE2_BENCHMARKS_OK "
        f"retrieval_final={final_retrieval} intent={intent_test} profile={len(profiles)} "
        f"ocr={len(ocr)} policy_final={final_policy} safety={len(safety)}"
    )


if __name__ == "__main__":
    main()
