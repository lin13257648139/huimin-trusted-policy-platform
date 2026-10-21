from datetime import date
from decimal import Decimal

from app.domain.models import EligibilityStatus, HouseholdProfile, TruthValue
from app.services.rule_engine import evaluate_profile


def current_profile(**changes) -> HouseholdProfile:
    base = {
        "query_date": date(2026, 9, 29),
        "city": "广州市",
        "district": "天河区",
        "household_size": 3,
        "is_local_hukou": True,
        "member_scope_confirmed": True,
        "monthly_income_total": Decimal("3200"),
        "deductible_monthly_total": Decimal("0"),
        "assets_eligible": True,
        "rigid_expenses_12m": Decimal("30000"),
        "urgent_event": True,
        "urgent_event_date": date(2026, 9, 15),
        "urgent_event_type": "突发急病",
        "basic_life_interrupted": True,
        "residence_proof": True,
        "special_person_category_confirmed": False,
    }
    base.update(changes)
    return HouseholdProfile(**base)


def by_id(results, benefit_id):
    return next(result for result in results if result.benefit_id == benefit_id)


def test_current_low_income_case_is_traceable() -> None:
    snapshot, results, warnings = evaluate_profile(current_profile())
    dibao = by_id(results, "B002")
    assert snapshot.local_rule_available is True
    assert dibao.status == EligibilityStatus.LIKELY
    assert dibao.policy_version == "穗民规字〔2026〕3号"
    assert any(item.source_id == "GZ-003" for item in dibao.evidence)
    assert any("行政审批" in warning for warning in warnings)
    assert dibao.plan_role == "primary"
    assert by_id(results, "B003").plan_role == "alternative"
    assert by_id(results, "B004").plan_role == "alternative"
    assert by_id(results, "B001").plan_role == "linked"
    assert {
        relation.related_benefit_id for relation in dibao.plan_relations
    } >= {"B003", "B004"}
    assert any(
        item.evidence_id == "E-GD-002-DIBAO-EXCLUSION"
        for item in dibao.evidence
    )


def test_edge_and_rigid_are_parallel_only_after_dibao_is_ruled_out() -> None:
    _, results, _ = evaluate_profile(
        current_profile(
            monthly_income_total=Decimal("4500"),
            rigid_expenses_12m=Decimal("40000"),
            urgent_event=False,
            urgent_event_date=None,
            urgent_event_type=None,
            basic_life_interrupted=None,
        )
    )
    dibao = by_id(results, "B002")
    edge = by_id(results, "B003")
    rigid = by_id(results, "B004")
    assert dibao.status == EligibilityStatus.UNLIKELY
    assert edge.status == EligibilityStatus.LIKELY
    assert rigid.status == EligibilityStatus.LIKELY
    assert edge.plan_role == rigid.plan_role == "primary"
    assert any(
        relation.relation_type == "parallel_assessment"
        and relation.related_benefit_id == "B004"
        for relation in edge.plan_relations
    )
    assert any(
        relation.relation_type == "parallel_assessment"
        and relation.related_benefit_id == "B003"
        for relation in rigid.plan_relations
    )


def test_dibao_manual_boundary_gates_edge_and_rigid_as_fallbacks() -> None:
    _, results, _ = evaluate_profile(
        current_profile(
            monthly_income_total=Decimal("3981"),
            rigid_expenses_12m=Decimal("36000"),
            urgent_event=False,
            urgent_event_date=None,
            urgent_event_type=None,
            basic_life_interrupted=None,
        )
    )
    assert by_id(results, "B002").status == EligibilityStatus.MANUAL_REVIEW
    assert by_id(results, "B002").plan_role == "manual"
    assert by_id(results, "B003").plan_role == "alternative"
    assert by_id(results, "B004").plan_role == "alternative"
    assert results[0].benefit_id == "B002"


def test_edge_standard_applies_from_start_of_2026() -> None:
    _, results, _ = evaluate_profile(
        current_profile(
            query_date=date(2026, 1, 1),
            monthly_income_total=Decimal("4500"),
            rigid_expenses_12m=Decimal("0"),
            urgent_event=False,
            urgent_event_date=None,
            urgent_event_type=None,
            basic_life_interrupted=None,
        )
    )
    assert by_id(results, "B003").status == EligibilityStatus.LIKELY


def test_high_income_does_not_become_likely() -> None:
    _, results, _ = evaluate_profile(current_profile(monthly_income_total=Decimal("12000")))
    dibao = by_id(results, "B002")
    assert dibao.status == EligibilityStatus.UNLIKELY
    income = next(item for item in dibao.conditions if item.code == "dibao_income")
    assert income.state == TruthValue.FALSE


def test_dibao_equal_boundary_is_not_likely_but_edge_is_inclusive() -> None:
    _, results, _ = evaluate_profile(
        current_profile(monthly_income_total=Decimal("3981"), rigid_expenses_12m=Decimal("0"))
    )
    assert by_id(results, "B002").status == EligibilityStatus.MANUAL_REVIEW

    _, edge_results, _ = evaluate_profile(
        current_profile(monthly_income_total=Decimal("5971.5"), rigid_expenses_12m=Decimal("0"))
    )
    assert by_id(edge_results, "B003").status == EligibilityStatus.LIKELY


def test_rigid_expense_uses_published_ratio_and_income_ceiling() -> None:
    _, below_results, _ = evaluate_profile(
        current_profile(monthly_income_total=Decimal("5000"), rigid_expenses_12m=Decimal("35999"))
    )
    assert by_id(below_results, "B004").status == EligibilityStatus.UNLIKELY

    _, boundary_results, _ = evaluate_profile(
        current_profile(monthly_income_total=Decimal("5000"), rigid_expenses_12m=Decimal("36000"))
    )
    assert by_id(boundary_results, "B004").status == EligibilityStatus.LIKELY


def test_temporary_rescue_alone_does_not_make_low_income_monitoring_likely() -> None:
    _, results, _ = evaluate_profile(
        current_profile(monthly_income_total=Decimal("30000"), rigid_expenses_12m=Decimal("0"))
    )
    assert by_id(results, "B005").status == EligibilityStatus.LIKELY
    assert by_id(results, "B001").status == EligibilityStatus.UNLIKELY


def test_missing_assets_returns_incomplete() -> None:
    _, results, _ = evaluate_profile(current_profile(assets_eligible=None))
    dibao = by_id(results, "B002")
    assert dibao.status == EligibilityStatus.INCOMPLETE
    assert any("财产" in item for item in dibao.missing_items)


def test_2026_transition_query_uses_2026_amount_with_legacy_local_rule() -> None:
    _, results, warnings = evaluate_profile(current_profile(query_date=date(2026, 7, 31)))
    dibao = by_id(results, "B002")
    assert dibao.status == EligibilityStatus.LIKELY
    assert dibao.policy_version == "穗民规字〔2023〕3号"
    assert any(item.source_id == "GZ-009" for item in dibao.evidence)
    assert all(item.source_id != "GZ-002" for item in dibao.evidence)
    assert all("未命中已核验" not in warning for warning in warnings)


def test_2025_query_never_exposes_2026_annual_parameters() -> None:
    snapshot, results, warnings = evaluate_profile(
        current_profile(
            query_date=date(2025, 12, 31),
            urgent_event=False,
            urgent_event_date=None,
            urgent_event_type=None,
            basic_life_interrupted=None,
        )
    )
    assert snapshot.local_rule_available is False
    assert any("不会套用2026年标准" in warning for warning in warnings)

    dibao = by_id(results, "B002")
    edge = by_id(results, "B003")
    rigid = by_id(results, "B004")
    assert dibao.status == EligibilityStatus.MANUAL_REVIEW
    assert edge.status == EligibilityStatus.MANUAL_REVIEW
    assert rigid.status == EligibilityStatus.MANUAL_REVIEW

    dibao_income = next(item for item in dibao.conditions if item.code == "dibao_income")
    edge_income = next(item for item in edge.conditions if item.code == "edge_income")
    rigid_ceiling = next(item for item in rigid.conditions if item.code == "rigid_income_ceiling")
    assert dibao_income.state == TruthValue.UNKNOWN
    assert edge_income.state == TruthValue.UNKNOWN
    assert rigid_ceiling.state == TruthValue.UNKNOWN
    assert "1327" not in f"{dibao_income.reason}{dibao_income.expected}"
    assert "1990.5" not in f"{edge_income.reason}{edge_income.expected}"
    assert "86069" not in f"{rigid_ceiling.reason}{rigid_ceiling.expected}"
    assert all(item.source_id != "GZ-003" for item in dibao.evidence + edge.evidence)
    assert all(item.source_id != "GZ-008" for item in rigid.evidence)


def test_unknown_member_scope_prevents_income_from_becoming_terminal_rejection() -> None:
    _, results, _ = evaluate_profile(
        current_profile(member_scope_confirmed=None, monthly_income_total=Decimal("12000"))
    )
    assert by_id(results, "B002").status == EligibilityStatus.INCOMPLETE


def test_independent_asset_failure_still_rejects_when_member_scope_is_unknown() -> None:
    _, results, _ = evaluate_profile(
        current_profile(
            member_scope_confirmed=None,
            monthly_income_total=Decimal("12000"),
            assets_eligible=False,
        )
    )
    assert by_id(results, "B002").status == EligibilityStatus.UNLIKELY


def test_recent_urgent_event_is_prioritized() -> None:
    _, results, _ = evaluate_profile(current_profile())
    temporary = by_id(results, "B005")
    assert temporary.status == EligibilityStatus.LIKELY
    assert results[0].benefit_id == "B005"


def test_omitted_urgent_event_remains_unknown() -> None:
    profile = current_profile(
        urgent_event=None,
        urgent_event_date=None,
        urgent_event_type=None,
        basic_life_interrupted=None,
    )
    assert profile.urgent_event is None

    _, results, _ = evaluate_profile(profile)
    temporary = by_id(results, "B005")
    event = next(item for item in temporary.conditions if item.code == "urgent_event")
    assert event.state == TruthValue.UNKNOWN
    assert event.input_field == "urgent_event"
    assert temporary.status == EligibilityStatus.INCOMPLETE
    assert "不会将未填写视为没有发生" in event.reason


def test_explicit_no_urgent_event_is_false_not_unknown() -> None:
    _, results, _ = evaluate_profile(
        current_profile(
            urgent_event=False,
            urgent_event_date=None,
            urgent_event_type=None,
            basic_life_interrupted=None,
        )
    )
    temporary = by_id(results, "B005")
    event = next(item for item in temporary.conditions if item.code == "urgent_event")
    assert event.state == TruthValue.FALSE
    assert temporary.status == EligibilityStatus.UNLIKELY


def test_temporary_rescue_month_boundary_routes_to_manual_review() -> None:
    _, inside_results, _ = evaluate_profile(
        current_profile(urgent_event_date=date(2026, 8, 31))
    )
    _, boundary_results, _ = evaluate_profile(
        current_profile(urgent_event_date=date(2026, 8, 30))
    )
    _, outside_results, _ = evaluate_profile(
        current_profile(urgent_event_date=date(2026, 8, 28))
    )
    assert by_id(inside_results, "B005").status == EligibilityStatus.LIKELY
    assert by_id(boundary_results, "B005").status == EligibilityStatus.MANUAL_REVIEW
    assert by_id(outside_results, "B005").status == EligibilityStatus.UNLIKELY


def test_out_of_region_stops_local_decision() -> None:
    _, results, warnings = evaluate_profile(current_profile(city="佛山市", district="禅城区"))
    assert all(result.status != EligibilityStatus.LIKELY for result in results)
    assert any("仅维护广州市" in warning for warning in warnings)

