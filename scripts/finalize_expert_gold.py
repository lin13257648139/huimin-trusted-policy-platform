from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVALUATION_DIR = ROOT / "data" / "evaluation"
REVIEW_A = EVALUATION_DIR / "expert_review_A.csv"
REVIEW_B = EVALUATION_DIR / "expert_review_B.csv"
MASTER = EVALUATION_DIR / "expert_gold_master.csv"
AUDIT = EVALUATION_DIR / "expert_gold_audit.json"
BENEFIT_IDS = ("B001", "B002", "B003", "B004", "B005")
ALLOWED = {"likely", "unlikely", "incomplete", "manual_review"}


def _read(path: Path) -> tuple[list[str], dict[str, dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise SystemExit(f"{path.name}缺少表头。")
        rows = list(reader)
        if len({row["case_id"] for row in rows}) != len(rows):
            raise SystemExit(f"{path.name}存在重复case_id。")
        return list(reader.fieldnames), {row["case_id"]: row for row in rows}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _profile_key(profile_json: str) -> str:
    return json.dumps(
        json.loads(profile_json), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _agreement(
    rows: list[dict[str, str]],
    review_b: dict[str, dict[str, str]],
    benefits: tuple[str, ...] = BENEFIT_IDS,
) -> dict[str, object]:
    pairs = [
        (row[f"label_{benefit}"].strip(), review_b[row["case_id"]][f"label_{benefit}"].strip())
        for row in rows
        for benefit in benefits
    ]
    total = len(pairs)
    agreements = sum(left == right for left, right in pairs)
    left_counts = Counter(left for left, _ in pairs)
    right_counts = Counter(right for _, right in pairs)
    observed = agreements / total
    expected = sum(
        left_counts[label] / total * right_counts[label] / total for label in ALLOWED
    )
    kappa = (observed - expected) / (1 - expected) if expected < 1 else 1.0
    return {
        "decisions": total,
        "agreements": agreements,
        "raw_agreement": round(observed, 4),
        "cohen_kappa": round(kappa, 4),
    }


def finalize() -> dict[str, object]:
    _, review_a = _read(REVIEW_A)
    _, review_b = _read(REVIEW_B)
    fields, master = _read(MASTER)
    if set(review_a) != set(review_b) or set(review_a) != set(master):
        raise SystemExit("A/B评审和金标主表的case_id集合不一致，禁止冻结。")

    adjudication_rows = 0
    adjudication_decisions = 0
    for case_id in sorted(master):
        a = review_a[case_id]
        b = review_b[case_id]
        row = master[case_id]
        for key in ("case_summary", "profile_json", "gold_policy_snapshot"):
            if a.get(key, "") != b.get(key, "") or a.get(key, "") != row.get(key, ""):
                raise SystemExit(f"{case_id}的{key}与原始评审不一致，禁止冻结。")
        if row.get("reviewer_a_comment", "") != a.get("reviewer_comment", ""):
            raise SystemExit(f"{case_id}的专家A评语被修改，禁止冻结。")
        if row.get("reviewer_b_comment", "") != b.get("reviewer_comment", ""):
            raise SystemExit(f"{case_id}的专家B评语被修改，禁止冻结。")

        row_has_disagreement = False
        for benefit in BENEFIT_IDS:
            a_label = a[f"label_{benefit}"].strip()
            b_label = b[f"label_{benefit}"].strip()
            if row[f"reviewer_a_{benefit}"].strip() != a_label:
                raise SystemExit(f"{case_id} {benefit}的专家A标签被修改，禁止冻结。")
            if row[f"reviewer_b_{benefit}"].strip() != b_label:
                raise SystemExit(f"{case_id} {benefit}的专家B标签被修改，禁止冻结。")
            gold = row[f"gold_{benefit}"].strip()
            if gold not in ALLOWED:
                raise SystemExit(f"{case_id} {benefit}金标为空或非法：{gold!r}。")
            if a_label == b_label and gold != a_label:
                raise SystemExit(f"{case_id} {benefit}无分歧项被改写，禁止冻结。")
            if a_label != b_label:
                row_has_disagreement = True
                adjudication_decisions += 1
        if row_has_disagreement:
            adjudication_rows += 1
            if not row.get("adjudicator_comment", "").strip():
                raise SystemExit(f"{case_id}缺少专家C裁决理由。")
        row["needs_adjudication"] = "no"

    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in master.values():
        grouped[_profile_key(row["profile_json"])].append(row)
    for group in grouped.values():
        if len(group) <= 1:
            continue
        for benefit in BENEFIT_IDS:
            labels = {row[f"gold_{benefit}"] for row in group}
            if len(labels) > 1:
                case_ids = ", ".join(row["case_id"] for row in group)
                raise SystemExit(f"重复画像金标冲突：{case_ids} {benefit}。")

    ordered_rows = [master[case_id] for case_id in sorted(master)]
    with MASTER.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(ordered_rows)

    review_a_rows = [review_a[case_id] for case_id in sorted(review_a)]
    unique_review_a_rows: list[dict[str, str]] = []
    seen_profiles: set[str] = set()
    for row in review_a_rows:
        key = _profile_key(row["profile_json"])
        if key in seen_profiles:
            continue
        seen_profiles.add(key)
        unique_review_a_rows.append(row)

    by_benefit_agreement = {
        benefit: _agreement(review_a_rows, review_b, (benefit,))
        for benefit in BENEFIT_IDS
    }

    audit = {
        "status": "frozen_expert_gold",
        "frozen_at": date.today().isoformat(),
        "records": len(ordered_rows),
        "unique_profiles": len(grouped),
        "duplicate_records_excluded_in_evaluation": len(ordered_rows) - len(grouped),
        "adjudication_rows": adjudication_rows,
        "adjudication_decisions": adjudication_decisions,
        "inter_reviewer_agreement": {
            "all_records": _agreement(review_a_rows, review_b),
            "unique_profiles": _agreement(unique_review_a_rows, review_b),
            "by_benefit": by_benefit_agreement,
        },
        "allowed_labels": sorted(ALLOWED),
        "sha256": {
            REVIEW_A.name: _sha256(REVIEW_A),
            REVIEW_B.name: _sha256(REVIEW_B),
            MASTER.name: _sha256(MASTER),
        },
        "validation": {
            "case_ids_match": True,
            "source_fields_unchanged": True,
            "reviewer_labels_unchanged": True,
            "reviewer_comments_unchanged": True,
            "all_gold_labels_complete": True,
            "adjudicator_comments_complete": True,
            "duplicate_profile_gold_consistent": True,
        },
    }
    AUDIT.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    return audit


if __name__ == "__main__":
    result = finalize()
    print(json.dumps(result, ensure_ascii=False, indent=2))
