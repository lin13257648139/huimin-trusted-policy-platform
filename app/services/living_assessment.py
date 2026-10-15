from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache
from typing import Any, Literal

from app.config import BASE_DIR
from app.domain.models import (
    AssessmentCalculationLine,
    LivingAssessmentRequest,
    LivingAssessmentResponse,
)
from app.services.rule_registry import get_rule_for_date

REGISTRY_PATH = BASE_DIR / "data" / "processed" / "living_assessment_registry.json"
MONEY = Decimal("0.01")
D_VALUE = Decimal("0.01")


@lru_cache(maxsize=1)
def load_assessment_registry() -> dict[str, Any]:
    payload = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    required = {
        "registry_version",
        "document_no",
        "source_ids",
        "effective_from",
        "effective_to",
        "employment_cost_cap_d_per_laborer",
        "member_adjustments_d",
        "active_duty_conscript_adjustment_d",
        "obligor_adjustments_d",
        "housing_adjustment_d",
        "motorcycle_adjustments_d",
        "electric_bicycle_adjustments_d",
        "evidence",
    }
    missing = required - payload.keys()
    if missing:
        raise ValueError(f"综合评估登记表缺少字段：{sorted(missing)}")
    return payload


def assessment_model_governance() -> dict[str, Any]:
    registry = load_assessment_registry()
    return {
        "registry_version": registry["registry_version"],
        "document_no": registry["document_no"],
        "source_ids": registry["source_ids"],
        "effective_from": registry["effective_from"],
        "effective_to": registry["effective_to"],
        "registry_sha256_prefix": hashlib.sha256(REGISTRY_PATH.read_bytes()).hexdigest()[:12],
        "automation_boundary": "计算草稿；核对报告、入户综合评估和人工确认不可自动替代",
    }


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value))


def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY, rounding=ROUND_HALF_UP)


def _d(value: Decimal) -> Decimal:
    return value.quantize(D_VALUE, rounding=ROUND_HALF_UP)


def _base_response(
    request: LivingAssessmentRequest,
    registry: dict[str, Any],
    *,
    calculation_status: Literal["not_available", "incomplete", "calculated"],
    review_state: Literal[
        "manual_review", "needs_information", "calculation_draft", "ready_for_official_review"
    ],
    d_standard: Decimal | None,
    missing_fields: list[str] | None = None,
    warnings: list[str] | None = None,
) -> LivingAssessmentResponse:
    return LivingAssessmentResponse(
        policy_version=registry["registry_version"],
        policy_effective_from=date.fromisoformat(registry["effective_from"]),
        policy_effective_to=date.fromisoformat(registry["effective_to"]),
        query_date=request.query_date,
        calculation_status=calculation_status,
        review_state=review_state,
        d_standard_yuan=d_standard,
        missing_fields=missing_fields or [],
        warnings=warnings or [],
        evidence_ids=list(dict.fromkeys(registry["evidence"].values())),
        formula="max(家庭月收入÷D＋家庭结构D＋生活状况D, 0)÷共同生活人数",
        decision_boundary=(
            "这是对粤民规字〔2025〕5号附件的匿名计算草稿，不是低保审批结论。"
            "核对报告、入户综合评估、调查双方确认及主管部门审核均不可由本工具替代。"
        ),
    )


def _required_missing(request: LivingAssessmentRequest) -> list[str]:
    missing = []
    for field_name in (
        "wage_income_monthly_avg",
        "operating_income_monthly_avg",
        "property_income_monthly_avg",
        "transfer_income_monthly_avg",
        "employment_cost_claimed",
        "laborer_count",
        "counted_motorcycles",
        "counted_electric_bicycles",
    ):
        if getattr(request, field_name) is None:
            missing.append(field_name)
    for field_name in (
        "six_month_average_confirmed",
        "labor_income_assessment_complete",
        "member_nonstack_confirmed",
        "obligor_information_complete",
        "vehicle_exclusions_confirmed",
        "no_usable_owned_housing",
    ):
        if getattr(request, field_name) is not True and field_name != "no_usable_owned_housing":
            missing.append(field_name)
        elif field_name == "no_usable_owned_housing" and getattr(request, field_name) is None:
            missing.append(field_name)
    if (
        request.judicial_support_cases > 0
        and request.judicial_support_included_in_transfer_income is not True
    ):
        missing.append("judicial_support_included_in_transfer_income")
    if (
        request.judicial_support_cases > 0
        and request.judicial_cases_excluded_from_obligor_counts is not True
    ):
        missing.append("judicial_cases_excluded_from_obligor_counts")
    return missing


def _vehicle_adjustment(
    count: int,
    *,
    adjustment_table: dict[str, str],
    motorcycle: bool,
) -> Decimal:
    """按登记表中的非线性数量档位返回家庭总调整值。"""

    if motorcycle:
        bucket = "3_plus" if count >= 3 else "2" if count == 2 else "0_or_1"
    else:
        bucket = "3_plus" if count >= 3 else "0_to_2"
    return _decimal(adjustment_table[bucket])


def calculate_living_assessment(
    request: LivingAssessmentRequest,
) -> LivingAssessmentResponse:
    registry = load_assessment_registry()
    effective_from = date.fromisoformat(registry["effective_from"])
    effective_to = date.fromisoformat(registry["effective_to"])
    if not effective_from <= request.query_date <= effective_to:
        return _base_response(
            request,
            registry,
            calculation_status="not_available",
            review_state="manual_review",
            d_standard=None,
            warnings=[
                "查询日不在第二版综合评估指标有效期内，系统不会跨期套用该模型。"
            ],
        )

    dated_rule = get_rule_for_date("B002", request.query_date)
    standard = dated_rule.parameters.get("income_standard_monthly_per_capita") if dated_rule else None
    if dated_rule is None or dated_rule.manual_review_required or standard is None:
        return _base_response(
            request,
            registry,
            calculation_status="not_available",
            review_state="manual_review",
            d_standard=None,
            warnings=["查询日对应的当地低保标准D尚未完成核验，禁止使用其他年度参数代替。"],
        )
    d_standard = _money(_decimal(standard))

    missing = _required_missing(request)
    if missing:
        return _base_response(
            request,
            registry,
            calculation_status="incomplete",
            review_state="needs_information",
            d_standard=d_standard,
            missing_fields=missing,
            warnings=["缺失字段保持UNKNOWN；补齐并确认后才能执行综合评估计算。"],
        )

    wage = request.wage_income_monthly_avg or Decimal("0")
    operating = request.operating_income_monthly_avg or Decimal("0")
    property_income = request.property_income_monthly_avg or Decimal("0")
    transfer = request.transfer_income_monthly_avg or Decimal("0")
    employment_claimed = request.employment_cost_claimed or Decimal("0")
    laborer_count = request.laborer_count or 0
    employment_cap = d_standard * _decimal(
        registry["employment_cost_cap_d_per_laborer"]
    ) * laborer_count
    employment_applied = min(employment_claimed, employment_cap, wage)
    base_income = max(wage + operating + property_income + transfer - employment_applied, Decimal("0"))

    evidence = registry["evidence"]
    lines: list[AssessmentCalculationLine] = []
    structure_d = Decimal("0")
    member_coefficients = registry["member_adjustments_d"]
    member_labels = {
        "preschool": "学龄前儿童",
        "high_school_or_full_time_college": "高中/中专或全日制高职至本科学生",
        "age_70_79": "70至79周岁老人",
        "age_80_plus": "80周岁以上老人",
        "rare_disease": "罕见病成员",
        "severe_or_disabled": "重病、失能、重度残疾等成员",
        "chronic_or_half_disabled": "慢性病、半失能或其他残疾成员",
        "other_labor_affecting_disease": "影响劳动的其他疾病成员",
    }
    member_counts = request.member_adjustments.model_dump()
    for code, count in member_counts.items():
        coefficient = _decimal(member_coefficients[code])
        subtotal = coefficient * count
        structure_d += subtotal
        if count:
            lines.append(
                AssessmentCalculationLine(
                    code=f"member.{code}",
                    label=member_labels[code],
                    quantity=count,
                    coefficient_d=coefficient,
                    subtotal_d=subtotal,
                    evidence_id=evidence["member_structure"],
                )
            )

    duty_coefficient = _decimal(registry["active_duty_conscript_adjustment_d"])
    duty_subtotal = duty_coefficient * request.active_duty_conscript_count
    structure_d += duty_subtotal
    if request.active_duty_conscript_count:
        lines.append(
            AssessmentCalculationLine(
                code="family.active_duty_conscript",
                label="本人或直系亲属为现役义务兵",
                quantity=request.active_duty_conscript_count,
                coefficient_d=duty_coefficient,
                subtotal_d=duty_subtotal,
                evidence_id=evidence["member_structure"],
            )
        )

    obligor_coefficients = registry["obligor_adjustments_d"]
    obligor_groups = (
        ("strong", "履行能力较强的义务人", request.obligor_strong_count),
        ("general", "履行能力一般的义务人", request.obligor_general_count),
        ("weak", "履行能力较弱的义务人", request.obligor_weak_count),
        ("none", "无履行能力的义务人", request.obligor_none_count),
    )
    for code, label, count in obligor_groups:
        coefficient = _decimal(obligor_coefficients[code])
        subtotal = coefficient * count
        structure_d += subtotal
        if count:
            lines.append(
                AssessmentCalculationLine(
                    code=f"obligor.{code}",
                    label=label,
                    quantity=count,
                    coefficient_d=coefficient,
                    subtotal_d=subtotal,
                    evidence_id=evidence["obligors"],
                )
            )

    unreachable_count = request.obligor_unreachable_with_written_explanation_count
    if unreachable_count:
        coefficient = _decimal(obligor_coefficients["strong"])
        subtotal = coefficient * unreachable_count
        structure_d += subtotal
        lines.append(
            AssessmentCalculationLine(
                code="obligor.unreachable_written_explanation",
                label="确实无法获知且已书面说明的义务人（按较强档）",
                quantity=unreachable_count,
                coefficient_d=coefficient,
                subtotal_d=subtotal,
                evidence_id=evidence["obligors"],
            )
        )

    living_d = Decimal("0")
    if request.no_usable_owned_housing is True:
        coefficient = _decimal(registry["housing_adjustment_d"])
        living_d += coefficient
        lines.append(
            AssessmentCalculationLine(
                code="living.no_usable_owned_housing",
                label="家庭无可居住自有住房",
                quantity=1,
                coefficient_d=coefficient,
                subtotal_d=coefficient,
                evidence_id=evidence["living_assets"],
            )
        )

    motorcycle_count = request.counted_motorcycles or 0
    motorcycle_d = _vehicle_adjustment(
        motorcycle_count,
        adjustment_table=registry["motorcycle_adjustments_d"],
        motorcycle=True,
    )
    living_d += motorcycle_d
    if motorcycle_count:
        lines.append(
            AssessmentCalculationLine(
                code="asset.motorcycle",
                label=f"计入评估的摩托车：{motorcycle_count}辆档",
                quantity=1,
                coefficient_d=motorcycle_d,
                subtotal_d=motorcycle_d,
                evidence_id=evidence["living_assets"],
            )
        )

    ebike_count = request.counted_electric_bicycles or 0
    ebike_d = _vehicle_adjustment(
        ebike_count,
        adjustment_table=registry["electric_bicycle_adjustments_d"],
        motorcycle=False,
    )
    living_d += ebike_d
    if ebike_count:
        lines.append(
            AssessmentCalculationLine(
                code="asset.electric_bicycle",
                label=f"计入评估的电动自行车：{ebike_count}辆档",
                quantity=1,
                coefficient_d=ebike_d,
                subtotal_d=ebike_d,
                evidence_id=evidence["living_assets"],
            )
        )

    adjusted_family_d = max(base_income / d_standard + structure_d + living_d, Decimal("0"))
    assessed_per_capita_d = _d(adjusted_family_d / request.household_member_count)
    assessed_per_capita_yuan = _money(assessed_per_capita_d * d_standard)
    comparison: Literal["below_1d", "at_or_above_1d"] = (
        "below_1d" if assessed_per_capita_d < Decimal("1") else "at_or_above_1d"
    )
    process_fields = (
        request.verification_report_available,
        request.in_home_assessment_completed,
        request.investigator_confirmed,
        request.household_confirmed,
    )
    process_complete = all(value is True for value in process_fields)
    warnings = []
    if employment_claimed > employment_applied:
        warnings.append("就业成本申报额超过政策上限或工资性收入，已按较低值计入。")
    if not process_complete:
        warnings.append("数值已计算，但核对报告、入户评估或双方确认尚未全部完成，只能作为草稿。")
    warnings.append(
        "低于1D只是综合评估指标中的收入比较结果，财产条件及主管部门审核仍须另行完成。"
    )

    return LivingAssessmentResponse(
        policy_version=registry["registry_version"],
        policy_effective_from=effective_from,
        policy_effective_to=effective_to,
        query_date=request.query_date,
        calculation_status="calculated",
        review_state="ready_for_official_review" if process_complete else "calculation_draft",
        d_standard_yuan=d_standard,
        base_monthly_income_yuan=_money(base_income),
        employment_cost_cap_yuan=_money(employment_cap),
        employment_cost_applied_yuan=_money(employment_applied),
        structure_adjustment_d=_d(structure_d),
        living_adjustment_d=_d(living_d),
        adjusted_family_income_d=_d(adjusted_family_d),
        assessed_per_capita_d=assessed_per_capita_d,
        assessed_per_capita_yuan=assessed_per_capita_yuan,
        threshold_comparison=comparison,
        official_process_complete=process_complete,
        calculation_lines=lines,
        warnings=warnings,
        evidence_ids=list(dict.fromkeys(evidence.values())),
        formula="max(家庭月收入÷D＋家庭结构D＋生活状况D, 0)÷共同生活人数",
        decision_boundary=(
            "这是对粤民规字〔2025〕5号附件的匿名计算草稿，不是低保审批结论。"
            "核对报告、入户综合评估、调查双方确认及主管部门审核均不可由本工具替代。"
        ),
    )
