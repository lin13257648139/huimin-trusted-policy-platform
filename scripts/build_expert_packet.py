from __future__ import annotations

import argparse
import csv
import json
import random
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BENEFIT_IDS = ("B001", "B002", "B003", "B004", "B005")


def _profile_key(profile: dict[str, object]) -> str:
    """Return a stable identity for blind-review sampling."""
    return json.dumps(profile, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _summary(profile: dict[str, object]) -> str:
    urgent = "有急难事件" if profile.get("urgent_event") else "无急难事件"
    return (
        f"{profile.get('district', '地区缺失')}；家庭{profile.get('household_size', '人数缺失')}人；"
        f"月总收入{profile.get('monthly_income_total', '缺失')}元；"
        f"财产条件{profile.get('assets_eligible', '缺失')}；共同生活成员范围"
        f"{profile.get('member_scope_confirmed', '缺失')}；{urgent}；查询日"
        f"{profile.get('query_date', '缺失')}。"
    )


def build_packet(source: Path, output_dir: Path, per_category: int, seed: int) -> None:
    rows = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines() if line]
    unique_rows: list[dict[str, object]] = []
    seen_profiles: set[str] = set()
    for row in rows:
        key = _profile_key(row["profile"])
        if key in seen_profiles:
            continue
        seen_profiles.add(key)
        unique_rows.append(row)
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in unique_rows:
        grouped[str(row["category"])].append(row)
    rng = random.Random(seed)
    selected = []
    for category in sorted(grouped):
        candidates = list(grouped[category])
        rng.shuffle(candidates)
        selected.extend(candidates[: min(per_category, len(candidates))])
    rng.shuffle(selected)

    output_dir.mkdir(parents=True, exist_ok=True)
    base_fields = ["case_id", "case_summary", "profile_json", "gold_policy_snapshot"]
    review_fields = base_fields + [f"label_{item}" for item in BENEFIT_IDS] + ["reviewer_comment"]
    for reviewer in ("A", "B"):
        path = output_dir / f"expert_review_{reviewer}.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=review_fields)
            writer.writeheader()
            for item in selected:
                writer.writerow(
                    {
                        "case_id": item["case_id"],
                        "case_summary": _summary(item["profile"]),
                        "profile_json": json.dumps(item["profile"], ensure_ascii=False),
                        "gold_policy_snapshot": "",
                        **{f"label_{benefit}": "" for benefit in BENEFIT_IDS},
                        "reviewer_comment": "",
                    }
                )
    manifest = {
        "dataset_role": "expert_annotation_packet_unlabeled",
        "source": source.name,
        "seed": seed,
        "category_hidden_from_reviewers": True,
        "source_case_count": len(rows),
        "unique_source_profiles": len(unique_rows),
        "duplicates_removed_before_sampling": len(rows) - len(unique_rows),
        "categories": {key: min(per_category, len(value)) for key, value in sorted(grouped.items())},
        "total_cases": len(selected),
        "unique_profiles": len({_profile_key(item["profile"]) for item in selected}),
        "allowed_labels": ["likely", "unlikely", "incomplete", "manual_review"],
        "warning": "这些案例尚未经过专家标注，不得用于宣称业务准确率。",
    }
    (output_dir / "expert_packet_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="构建双人独立盲评包，不写入系统预测标签。")
    parser.add_argument(
        "--source",
        type=Path,
        default=ROOT / "data" / "processed" / "synthetic_conformance_cases.jsonl",
    )
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data" / "evaluation")
    parser.add_argument("--per-category", type=int, default=15)
    parser.add_argument("--seed", type=int, default=20260930)
    args = parser.parse_args()
    build_packet(args.source, args.output_dir, args.per_category, args.seed)
    print(f"已生成双人盲评包：{args.output_dir}")


if __name__ == "__main__":
    main()
