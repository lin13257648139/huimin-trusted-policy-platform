import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.domain.models import LivingAssessmentRequest
from app.services.living_assessment import calculate_living_assessment

ROOT = Path(__file__).resolve().parents[1]


def complete_request(**changes) -> LivingAssessmentRequest:
    payload = {
        "query_date": date(2026, 9, 30),
        "household_member_count": 1,
        "wage_income_monthly_avg": 1327,
        "operating_income_monthly_avg": 0,
        "property_income_monthly_avg": 0,
        "transfer_income_monthly_avg": 0,
        "employment_cost_claimed": 0,
        "laborer_count": 1,
        "six_month_average_confirmed": True,
        "labor_income_assessment_complete": True,
        "member_adjustments": {},
        "member_nonstack_confirmed": True,
        "active_duty_conscript_count": 0,
        "obligor_information_complete": True,
        "no_usable_owned_housing": False,
        "counted_motorcycles": 0,
        "counted_electric_bicycles": 0,
        "vehicle_exclusions_confirmed": True,
        "verification_report_available": True,
        "in_home_assessment_completed": True,
        "investigator_confirmed": True,
        "household_confirmed": True,
    }
    payload.update(changes)
    return LivingAssessmentRequest(**payload)


def test_equal_to_one_d_is_not_below_threshold() -> None:
    result = calculate_living_assessment(complete_request())
    assert result.calculation_status == "calculated"
    assert result.d_standard_yuan == Decimal("1327.00")
    assert result.assessed_per_capita_d == Decimal("1.00")
    assert result.threshold_comparison == "at_or_above_1d"
    assert result.review_state == "ready_for_official_review"


def test_employment_cost_is_capped_by_half_d_per_laborer() -> None:
    result = calculate_living_assessment(
        complete_request(
            wage_income_monthly_avg=3000,
            employment_cost_claimed=1000,
        )
    )
    assert result.employment_cost_cap_yuan == Decimal("663.50")
    assert result.employment_cost_applied_yuan == Decimal("663.50")
    assert result.base_monthly_income_yuan == Decimal("2336.50")
    assert any("政策上限" in warning for warning in result.warnings)


@pytest.mark.parametrize(
    ("motorcycles", "electric_bicycles", "expected_d"),
    [(1, 2, "0.00"), (2, 2, "1.00"), (3, 3, "3.00")],
)
def test_vehicle_quantity_buckets_follow_registry(
    motorcycles: int, electric_bicycles: int, expected_d: str
) -> None:
    result = calculate_living_assessment(
        complete_request(
            counted_motorcycles=motorcycles,
            counted_electric_bicycles=electric_bicycles,
        )
    )
    assert result.living_adjustment_d == Decimal(expected_d)


def test_negative_adjustments_floor_assessed_income_at_zero() -> None:
    result = calculate_living_assessment(
        complete_request(
            wage_income_monthly_avg=0,
            laborer_count=0,
            household_member_count=2,
            member_adjustments={"rare_disease": 1, "preschool": 1},
            no_usable_owned_housing=True,
        )
    )
    assert result.structure_adjustment_d == Decimal("-3.50")
    assert result.living_adjustment_d == Decimal("-1.00")
    assert result.adjusted_family_income_d == Decimal("0.00")
    assert result.assessed_per_capita_d == Decimal("0.00")


def test_member_categories_cannot_double_count_more_people_than_household() -> None:
    with pytest.raises(ValidationError, match="不得重复计分"):
        complete_request(
            household_member_count=1,
            member_adjustments={"preschool": 1, "rare_disease": 1},
        )


def test_missing_facts_stay_incomplete() -> None:
    request = complete_request(
        six_month_average_confirmed=None,
        counted_motorcycles=None,
        no_usable_owned_housing=None,
        vehicle_exclusions_confirmed=None,
    )
    result = calculate_living_assessment(request)
    assert result.calculation_status == "incomplete"
    assert result.review_state == "needs_information"
    assert set(result.missing_fields) >= {
        "six_month_average_confirmed",
        "counted_motorcycles",
        "no_usable_owned_housing",
        "vehicle_exclusions_confirmed",
    }
    assert result.assessed_per_capita_d is None


def test_2025_case_does_not_reuse_2026_model_or_standard() -> None:
    result = calculate_living_assessment(complete_request(query_date=date(2025, 12, 31)))
    assert result.calculation_status == "not_available"
    assert result.review_state == "manual_review"
    assert result.d_standard_yuan is None
    assert "不在第二版" in result.warnings[0]
    assert "1327" not in "".join(result.warnings)


def test_query_after_model_expiry_requires_manual_review() -> None:
    result = calculate_living_assessment(complete_request(query_date=date(2031, 1, 1)))
    assert result.calculation_status == "not_available"
    assert result.review_state == "manual_review"
    assert result.d_standard_yuan is None


def test_unreachable_obligor_with_written_explanation_uses_strong_bucket() -> None:
    result = calculate_living_assessment(
        complete_request(obligor_unreachable_with_written_explanation_count=1)
    )
    assert result.structure_adjustment_d == Decimal("2.00")
    assert any(
        line.code == "obligor.unreachable_written_explanation"
        and line.subtotal_d == Decimal("2")
        for line in result.calculation_lines
    )


def test_process_gates_keep_numerical_result_as_draft() -> None:
    result = calculate_living_assessment(
        complete_request(in_home_assessment_completed=False, household_confirmed=None)
    )
    assert result.calculation_status == "calculated"
    assert result.official_process_complete is False
    assert result.review_state == "calculation_draft"
    assert "只能作为草稿" in "".join(result.warnings)


def test_judicial_support_requires_income_and_nonduplication_confirmation() -> None:
    result = calculate_living_assessment(complete_request(judicial_support_cases=1))
    assert result.calculation_status == "incomplete"
    assert set(result.missing_fields) >= {
        "judicial_support_included_in_transfer_income",
        "judicial_cases_excluded_from_obligor_counts",
    }


def test_assessment_registry_only_references_verified_evidence() -> None:
    registry = json.loads(
        (ROOT / "data" / "processed" / "living_assessment_registry.json").read_text(
            encoding="utf-8"
        )
    )
    evidence = json.loads((ROOT / "app" / "data" / "evidence.json").read_text(encoding="utf-8"))
    evidence_by_id = {item["evidence_id"]: item for item in evidence}
    for evidence_id in registry["evidence"].values():
        assert evidence_by_id[evidence_id]["quote_verified"] is True
        assert evidence_by_id[evidence_id]["source_id"] == "GD-004-A"
