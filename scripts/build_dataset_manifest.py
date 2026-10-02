from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
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
        "path": "data/evaluation/profile_extraction_benchmark.jsonl",
        "role": "synthetic_profile_extraction_benchmark",
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
        "path": "data/evaluation/policy_compiler_real_benchmark.jsonl",
        "role": "official_clause_compiler_benchmark",
        "label_origin": "official verbatim clauses with project-authored gold",
        "independent": False,
        "contains_personal_data": False,
    },
    {
        "path": "data/evaluation/expert_gold_master.csv",
        "role": "external_expert_adjudicated_evaluation",
        "label_origin": "expert A/B review and expert C adjudication",
        "independent": True,
        "contains_personal_data": False,
        "release_note": "去标识化标签集；原始评审表不随源码发布。",
    },
    {
        "path": "data/evaluation/ocr_synthetic/manifest.json",
        "role": "synthetic_ocr_robustness_benchmark",
        "label_origin": "programmatically rendered synthetic documents",
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
            for key in ("cases", "records", "items", "documents"):
                if isinstance(payload.get(key), list):
                    return len(payload[key])
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
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "manifest_version": "1.0",
        "assets": assets,
        "missing": missing,
        "claim_boundary": (
            "合成集和项目自编gold只用于回归、消融与可复现工程验证；"
            "仅external_expert_adjudicated_evaluation可作为外部标注证据，"
            "仍不得外推为真实困难群众使用效果。"
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
