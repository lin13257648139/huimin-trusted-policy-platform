from __future__ import annotations

import json
import random
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.domain.models import HouseholdProfile  # noqa: E402
from app.services.rule_engine import DIBAO_STANDARD, EDGE_STANDARD, evaluate_profile  # noqa: E402

OUTPUT = ROOT / "data" / "processed" / "synthetic_conformance_cases.jsonl"
SEED = 20260929


def make_profile(index: int, randomizer: random.Random) -> tuple[str, HouseholdProfile]:
    household_size = randomizer.randint(1, 6)
    category = index % 8
    query_date = date(2026, 9, 29)
    assets: bool | None = True
    member_scope: bool | None = True
    urgent = False
    event_date = None
    interrupted = None
    rigid = Decimal("0")

    if category == 0:
        category_name = "dibao_boundary_below"
        per_capita = DIBAO_STANDARD - Decimal("0.01")
    elif category == 1:
        category_name = "dibao_boundary_equal"
        per_capita = DIBAO_STANDARD
    elif category == 2:
        category_name = "dibao_boundary_above"
        per_capita = DIBAO_STANDARD + Decimal("0.01")
    elif category == 3:
        category_name = "edge_boundary"
        per_capita = EDGE_STANDARD + randomizer.choice([Decimal("-0.01"), Decimal("0"), Decimal("0.01")])
    elif category == 4:
        category_name = "missing_assets"
        per_capita = Decimal(randomizer.randint(700, 1500))
        assets = None
    elif category == 5:
        category_name = "historical_version"
        per_capita = Decimal(randomizer.randint(700, 1600))
        query_date = date(2026, 7, 31)
    elif category == 6:
        category_name = "recent_urgent_event"
        per_capita = Decimal(randomizer.randint(900, 2400))
        urgent = True
        event_date = query_date - timedelta(days=randomizer.randint(0, 30))
        interrupted = True
        rigid = Decimal(randomizer.randint(5000, 60000))
    else:
        category_name = "incomplete_membership"
        per_capita = Decimal(randomizer.randint(700, 1800))
        member_scope = None

    profile = HouseholdProfile(
        query_date=query_date,
        city="广州市",
        district=randomizer.choice(["天河区", "越秀区", "番禺区", "白云区"]),
        household_size=household_size,
        is_local_hukou=True,
        member_scope_confirmed=member_scope,
        monthly_income_total=(per_capita * household_size).quantize(Decimal("0.01")),
        deductible_monthly_total=Decimal("0"),
        assets_eligible=assets,
        rigid_expenses_12m=rigid,
        urgent_event=urgent,
        urgent_event_date=event_date,
        urgent_event_type="突发急病" if urgent else None,
        basic_life_interrupted=interrupted,
        residence_proof=True,
    )
    return category_name, profile


def main() -> None:
    randomizer = random.Random(SEED)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8") as handle:
        for index in range(240):
            category, profile = make_profile(index, randomizer)
            snapshot, results, _ = evaluate_profile(profile)
            record = {
                "case_id": f"SYN-{index + 1:04d}",
                "dataset_role": "engine_conformance_only",
                "category": category,
                "profile": profile.model_dump(mode="json"),
                "expected_policy_snapshot": snapshot.snapshot_id,
                "expected_status": {item.benefit_id: item.status.value for item in results},
            }
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"SYNTHETIC_CASES_CREATED=240 seed={SEED}")


if __name__ == "__main__":
    main()

