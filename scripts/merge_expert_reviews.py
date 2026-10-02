from __future__ import annotations

import argparse
import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BENEFIT_IDS = ("B001", "B002", "B003", "B004", "B005")
ALLOWED = {"likely", "unlikely", "incomplete", "manual_review"}


def _read(path: Path) -> dict[str, dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return {row["case_id"]: row for row in csv.DictReader(handle)}


def merge(review_a: Path, review_b: Path, output: Path) -> None:
    left = _read(review_a)
    right = _read(review_b)
    if set(left) != set(right):
        raise SystemExit("两份评审文件的case_id不一致，禁止合并。")
    base_fields = ["case_id", "case_summary", "profile_json", "gold_policy_snapshot"]
    fields = list(base_fields)
    fields.extend(["reviewer_a_comment", "reviewer_b_comment"])
    for benefit in BENEFIT_IDS:
        fields.extend([f"reviewer_a_{benefit}", f"reviewer_b_{benefit}", f"gold_{benefit}"])
    fields.extend(["agreement_count", "needs_adjudication", "adjudicator_comment"])
    merged_rows = []
    for case_id in sorted(left):
        a = left[case_id]
        b = right[case_id]
        for key in ("case_summary", "profile_json", "gold_policy_snapshot"):
            if a.get(key, "") != b.get(key, ""):
                raise SystemExit(f"{case_id} 的{key}在A/B文件中不一致，禁止合并。")
        row = {key: a.get(key, "") for key in base_fields}
        row["reviewer_a_comment"] = a.get("reviewer_comment", "")
        row["reviewer_b_comment"] = b.get("reviewer_comment", "")
        agreements = 0
        needs_adjudication = False
        for benefit in BENEFIT_IDS:
            a_label = a.get(f"label_{benefit}", "").strip()
            b_label = b.get(f"label_{benefit}", "").strip()
            if a_label not in ALLOWED or b_label not in ALLOWED:
                raise SystemExit(
                    f"{case_id} {benefit}存在空值或非法标签；未生成主表，请先完成两份盲评。"
                )
            same = a_label == b_label
            agreements += int(same)
            needs_adjudication = needs_adjudication or not same
            row[f"reviewer_a_{benefit}"] = a_label
            row[f"reviewer_b_{benefit}"] = b_label
            row[f"gold_{benefit}"] = a_label if same else ""
        row["agreement_count"] = agreements
        row["needs_adjudication"] = "yes" if needs_adjudication else "no"
        row["adjudicator_comment"] = ""
        merged_rows.append(row)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(merged_rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="合并双人盲评结果并标记分歧。")
    evaluation = ROOT / "data" / "evaluation"
    parser.add_argument("--review-a", type=Path, default=evaluation / "expert_review_A.csv")
    parser.add_argument("--review-b", type=Path, default=evaluation / "expert_review_B.csv")
    parser.add_argument("--output", type=Path, default=evaluation / "expert_gold_master.csv")
    args = parser.parse_args()
    merge(args.review_a, args.review_b, args.output)
    print(f"已生成待裁决主表：{args.output}")


if __name__ == "__main__":
    main()
