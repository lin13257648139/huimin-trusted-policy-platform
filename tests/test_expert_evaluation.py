import csv
import json
from pathlib import Path

import pytest

from app.domain.models import HouseholdProfile
from app.services.rule_engine import evaluate_profile
from scripts.build_expert_packet import BENEFIT_IDS, build_packet
from scripts.evaluate_expert_gold import evaluate


def _profile() -> dict[str, object]:
    return {
        "query_date": "2026-09-30",
        "city": "广州市",
        "district": "天河区",
        "household_size": 3,
        "is_local_hukou": True,
        "member_scope_confirmed": True,
        "monthly_income_total": "3200",
        "deductible_monthly_total": "0",
        "assets_eligible": True,
        "rigid_expenses_12m": "30000",
        "urgent_event": False,
        "basic_life_interrupted": False,
        "residence_proof": True,
    }


def test_packet_hides_category_and_removes_duplicate_profiles(tmp_path: Path) -> None:
    source = tmp_path / "cases.jsonl"
    profile = _profile()
    records = [
        {"case_id": "A", "category": "one", "profile": profile},
        {"case_id": "B", "category": "two", "profile": profile},
        {
            "case_id": "C",
            "category": "two",
            "profile": profile | {"monthly_income_total": "9000"},
        },
    ]
    source.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in records), encoding="utf-8"
    )

    output = tmp_path / "packet"
    build_packet(source, output, per_category=10, seed=1)

    with (output / "expert_review_A.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
        assert "category" not in rows[0]
    assert len(rows) == 2
    manifest = json.loads((output / "expert_packet_manifest.json").read_text(encoding="utf-8"))
    assert manifest["duplicates_removed_before_sampling"] == 1
    assert manifest["unique_profiles"] == 2


def _gold_row(case_id: str, profile: dict[str, object]) -> dict[str, str]:
    _, results, _ = evaluate_profile(HouseholdProfile.model_validate(profile))
    predicted = {item.benefit_id: item.status.value for item in results}
    return {
        "case_id": case_id,
        "profile_json": json.dumps(profile, ensure_ascii=False),
        "gold_policy_snapshot": "",
        **{f"gold_{benefit}": predicted[benefit] for benefit in BENEFIT_IDS},
    }


def _write_gold(path: Path, rows: list[dict[str, str]]) -> None:
    fields = ["case_id", "profile_json", "gold_policy_snapshot"] + [
        f"gold_{benefit}" for benefit in BENEFIT_IDS
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def test_evaluation_deduplicates_identical_profiles(tmp_path: Path) -> None:
    profile = _profile()
    gold = tmp_path / "gold.csv"
    _write_gold(gold, [_gold_row("A", profile), _gold_row("B", profile)])

    report = evaluate(gold)

    assert report["original_record_count"] == 2
    assert report["unique_case_count"] == 1
    assert report["duplicate_records_excluded"] == 1
    assert report["overall"]["strict_exact_accuracy"] == 1.0


def test_evaluation_rejects_conflicting_duplicate_gold(tmp_path: Path) -> None:
    profile = _profile()
    first = _gold_row("A", profile)
    second = _gold_row("B", profile)
    second["gold_B002"] = "unlikely" if first["gold_B002"] != "unlikely" else "likely"
    gold = tmp_path / "gold.csv"
    _write_gold(gold, [first, second])

    with pytest.raises(SystemExit, match="金标冲突"):
        evaluate(gold)
