from datetime import date

from app.domain.models import HouseholdProfile
from app.services.rule_engine import evaluate_profile
from app.services.safety_validator import validate_screening_output


def test_screening_output_passes_independent_safety_gate() -> None:
    profile = HouseholdProfile(
        query_date=date(2026, 9, 30),
        district="天河区",
        household_size=3,
        is_local_hukou=True,
        member_scope_confirmed=True,
        monthly_income_total=3000,
        assets_eligible=True,
        urgent_event=False,
    )
    _, results, _ = evaluate_profile(profile)
    report = validate_screening_output(profile, results)
    assert report["safe"] is True
    assert report["blocked"] is False
    assert {item["id"] for item in report["checks"]} >= {
        "temporal_validity",
        "verbatim_evidence",
        "unknown_preservation",
        "decision_boundary",
    }
