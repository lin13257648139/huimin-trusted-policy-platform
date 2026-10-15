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
    assert all(report["enforcement"].values())
    assert {item["id"] for item in report["checks"]} >= {
        "temporal_validity",
        "verbatim_evidence",
        "unknown_preservation",
        "tri_state_preservation",
        "decision_boundary",
        "benefit_relation_consistency",
    }


def test_unknown_boolean_inputs_survive_independent_safety_gate() -> None:
    profile = HouseholdProfile(
        query_date=date(2026, 9, 30),
        district="天河区",
        household_size=3,
        is_local_hukou=True,
        member_scope_confirmed=None,
        monthly_income_total=3000,
        assets_eligible=None,
    )
    assert profile.urgent_event is None
    _, results, _ = evaluate_profile(profile)
    report = validate_screening_output(profile, results)
    check = next(item for item in report["checks"] if item["id"] == "tri_state_preservation")
    assert check["passed"] is True
    assert report["safe"] is True


def test_critical_failure_closes_every_output_gate() -> None:
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
    results[0].summary = "系统声称已经批准该事项"

    report = validate_screening_output(profile, results)

    assert report["safe"] is False
    assert report["blocked"] is True
    assert "decision_boundary" in report["failed_check_ids"]
    assert report["enforcement"] == {
        "api_publish": False,
        "persistence": False,
        "presentation": False,
        "print_export": False,
    }


def test_relation_contradiction_blocks_duplicate_primary_paths() -> None:
    profile = HouseholdProfile(
        query_date=date(2026, 9, 30),
        district="天河区",
        household_size=3,
        is_local_hukou=True,
        member_scope_confirmed=True,
        monthly_income_total=3000,
        assets_eligible=True,
        rigid_expenses_12m=30000,
        urgent_event=False,
    )
    _, results, _ = evaluate_profile(profile)
    next(item for item in results if item.benefit_id == "B004").plan_role = "primary"

    report = validate_screening_output(profile, results)

    assert report["safe"] is False
    assert "benefit_relation_consistency" in report["failed_check_ids"]
