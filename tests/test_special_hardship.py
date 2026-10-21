from datetime import date
from decimal import Decimal

from app.domain.models import (
    EligibilityStatus,
    HouseholdProfile,
    ParseProfileRequest,
    PolicyCompileRequest,
    TruthValue,
)
from app.services.policy_compiler import compile_policy
from app.services.profile_parser import parse_profile_deterministic
from app.services.rule_engine import evaluate_profile


def _profile(**changes) -> HouseholdProfile:
    values = {
        "query_date": date(2026, 9, 29),
        "city": "广州市",
        "district": "天河区",
        "household_size": 1,
        "is_local_hukou": True,
        "member_scope_confirmed": True,
        "monthly_income_total": Decimal("0"),
        "deductible_monthly_total": Decimal("0"),
        "assets_eligible": True,
        "rigid_expenses_12m": Decimal("0"),
        "urgent_event": False,
        "special_person_category_confirmed": True,
        "no_labor_capacity": True,
        "no_livelihood_source": True,
        "has_capable_legal_supporter": False,
    }
    values.update(changes)
    return HouseholdProfile(**values)


def _special(profile: HouseholdProfile):
    _, results, _ = evaluate_profile(profile)
    return next(item for item in results if item.benefit_id == "B006")


def test_special_hardship_requires_all_statutory_gateway_facts() -> None:
    result = _special(_profile())

    assert result.status == EligibilityStatus.LIKELY
    assert result.plan_role == "primary"
    assert all(condition.state == TruthValue.TRUE for condition in result.conditions)
    assert {item.evidence_id for item in result.evidence} >= {
        "E-CN-001-SPECIAL-HARDSHIP",
        "E-CN-001-SPECIAL-APPLICATION",
        "E-GZ-001-DEADLINE",
    }


def test_special_hardship_keeps_unknown_and_negative_facts_distinct() -> None:
    unknown = _special(_profile(no_livelihood_source=None))
    negative = _special(_profile(has_capable_legal_supporter=True))

    assert unknown.status == EligibilityStatus.INCOMPLETE
    assert any(condition.state == TruthValue.UNKNOWN for condition in unknown.conditions)
    assert negative.status == EligibilityStatus.UNLIKELY
    supporter = next(
        condition for condition in negative.conditions if condition.code == "capable_legal_supporter"
    )
    assert supporter.state == TruthValue.FALSE


def test_special_hardship_before_effective_date_forces_manual_review() -> None:
    result = _special(_profile(query_date=date(2026, 6, 30)))

    assert result.status == EligibilityStatus.MANUAL_REVIEW
    assert result.plan_role == "manual"


def test_policy_compiler_detects_special_hardship_and_extracts_conditions() -> None:
    response = compile_policy(
        PolicyCompileRequest(
            source_id="CN-SPECIAL-TEST",
            title="特困人员救助供养测试条款",
            source_text=(
                "对无劳动能力、无生活来源且无法定赡养、抚养、扶养义务人，"
                "或者其法定义务人无履行义务能力的老年人、未成年人、残疾人等"
                "特困人员，给予特困人员供养。本条款自2026年7月1日起施行。"
            ),
            region="广州市",
            use_llm=False,
        )
    )

    assert response.candidate.benefit_id == "B006"
    fields = {condition.field for condition in response.candidate.conditions}
    assert fields >= {
        "special_person_category_confirmed",
        "no_labor_capacity",
        "no_livelihood_source",
        "has_capable_legal_supporter",
    }
    assert response.publishable is False


def test_profile_parser_does_not_confuse_no_income_with_capable_supporter() -> None:
    result = parse_profile_deterministic(
        ParseProfileRequest(
            text="核对特困人员供养：无劳动能力、没有生活来源；扶养义务人有履行能力。",
            query_date=date(2026, 9, 29),
        )
    )

    assert result.fields["no_livelihood_source"] is True
    assert result.fields["has_capable_legal_supporter"] is True
