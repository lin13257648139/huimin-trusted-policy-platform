from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "data" / "evaluation" / "dataset_governance_manifest.json"

DATASETS: tuple[dict[str, Any], ...] = (
    {
        "path": "data/processed/synthetic_conformance_cases.jsonl",
        "role": "synthetic_regression",
        "label_origin": "programmatically generated from documented rules",
        "independent": False,
        "contains_personal_data": False,
    },
    {
        "path": "data/ml/intent_dataset.json",
        "role": "synthetic_intent_training_and_frozen_test",
        "label_origin": "programmatically rendered project-authored synthetic utterances",
        "independent": False,
        "contains_personal_data": False,
    },
    {
        "path": "data/evaluation/profile_extraction_benchmark.jsonl",
        "role": "synthetic_profile_extraction_benchmark",
        "label_origin": "project-authored synthetic gold",
        "independent": False,
        "contains_personal_data": False,
    },
    {
        "path": "data/evaluation/special_hardship_profile_benchmark.jsonl",
        "role": "focused_special_hardship_profile_challenge",
        "label_origin": "project-authored synthetic gold",
        "independent": False,
        "contains_personal_data": False,
    },
    {
        "path": "data/evaluation/retrieval_benchmark.json",
        "role": "internal_retrieval_benchmark",
        "label_origin": "project-authored queries and expected evidence",
        "independent": False,
        "contains_personal_data": False,
    },
    {
        "path": "data/evaluation/policy_qa_special_challenge.json",
        "role": "focused_special_hardship_grounding_challenge",
        "label_origin": "project-authored queries and expected evidence",
        "independent": False,
        "contains_personal_data": False,
    },
    {
        "path": "data/evaluation/policy_compiler_real_benchmark.jsonl",
        "role": "official_clause_compiler_benchmark",
        "label_origin": "official verbatim clauses with project-authored gold",
        "independent": False,
        "contains_personal_data": False,
    },
    {
        "path": "data/evaluation/ocr_synthetic/manifest.json",
        "role": "synthetic_ocr_robustness_benchmark",
        "label_origin": "programmatically rendered synthetic documents",
        "independent": False,
        "contains_personal_data": False,
        "related_glob": "data/evaluation/ocr_synthetic/OCR-*.png",
    },
    {
        "path": "data/evaluation/stage2_split_manifest.json",
        "role": "frozen_split_and_leakage_control_manifest",
        "label_origin": "programmatic governance validation",
        "independent": False,
        "contains_personal_data": False,
    },
    {
        "path": "data/evaluation/high_risk_safety_benchmark.jsonl",
        "role": "synthetic_high_risk_safety_regression",
        "label_origin": "project-authored adversarial and boundary guards",
        "independent": False,
        "contains_personal_data": False,
    },
    {
        "path": "data/evaluation/active_question_decision_cases.jsonl",
        "role": "synthetic_active_question_decision_paths",
        "label_origin": "programmatically transformed from synthetic conformance profiles",
        "independent": False,
        "contains_personal_data": False,
    },
)


def count_records(path: Path) -> int | None:
    if path.suffix == ".jsonl":
        return sum(bool(line.strip()) for line in path.read_text(encoding="utf-8").splitlines())
    if path.suffix == ".csv":
        with path.open("r", encoding="utf-8-sig") as stream:
            return max(0, sum(1 for _ in stream) - 1)
    if path.suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(payload, list):
            return len(payload)
        if isinstance(payload, dict):
            for key in ("cases", "records", "items", "documents", "queries", "datasets"):
                if isinstance(payload.get(key), list):
                    return len(payload[key])
            labels = payload.get("labels")
            if isinstance(labels, dict):
                return sum(
                    len(group.get("test", []))
                    for group in labels.values()
                    if isinstance(group, dict)
                )
    return None


def main() -> None:
    assets = []
    missing = []
    for descriptor in DATASETS:
        relative = descriptor["path"]
        path = ROOT / relative
        if not path.is_file():
            missing.append(relative)
            continue
        assets.append(
            {
                **descriptor,
                "bytes": path.stat().st_size,
                "records": count_records(path),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
        related_glob = descriptor.get("related_glob")
        if related_glob:
            related = sorted(ROOT.glob(str(related_glob)))
            digest = hashlib.sha256()
            for related_path in related:
                digest.update(related_path.relative_to(ROOT).as_posix().encode("utf-8"))
                digest.update(b"\0")
                digest.update(hashlib.sha256(related_path.read_bytes()).digest())
            assets[-1]["related_files"] = len(related)
            assets[-1]["related_tree_sha256"] = digest.hexdigest()
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "manifest_version": "1.0",
        "assets": assets,
        "missing": missing,
        "claim_boundary": (
            "当前资产全部为合成数据或项目组标注，只用于回归、消融与可复现工程验证；"
            "项目尚未开展外部专家评测，不得把任何资产表述为独立专家证据，"
            "也不得外推为真实困难群众使用效果。"
        ),
        "privacy": "清单不包含群众姓名、证件号、电话、地址或自由叙述。",
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"DATASET_MANIFEST_OK assets={len(assets)} missing={len(missing)}")
    if missing:
        raise SystemExit(f"DATASET_MANIFEST_MISSING: {missing}")


if __name__ == "__main__":
    main()
