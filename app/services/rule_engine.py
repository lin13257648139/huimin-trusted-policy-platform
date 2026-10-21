from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal

from app.domain.models import (
    BenefitResult,
    ConditionInputField,
    ConditionResult,
    EligibilityStatus,
    HouseholdProfile,
    TruthValue,
)
from app.services.benefit_relations import apply_combination_plan
from app.services.catalog import evidence_for
from app.services.policy_version import (
    TEMPORARY_RESCUE_END,
    PolicySnapshot,
    select_policy_snapshot,
    temporary_policy_warning,
)
from app.services.rule_registry import decimal_parameter, get_rule_for_date

# 仅供健康检查接口展示当前年度参数；历史评估必须从查询日对应规则读取，
# 禁止使用这两个常量作为历史回退值。
DIBAO_STANDARD = decimal_parameter("B002", "income_standard_monthly_per_capita")
EDGE_STANDARD = decimal_parameter("B003", "income_standard_monthly_per_capita")
ENGINE_VERSION = "rule-engine/0.6.0"

CONDITION_INPUT_FIELDS: dict[str, ConditionInputField] = {
    "region": "district",
    "hukou": "is_local_hukou",
    "residence": "residence_proof",
    "member_scope": "member_scope_confirmed",
    "dibao_income": "monthly_income_total",
    "edge_income": "monthly_income_total",
    "assets": "assets_eligible",
    "rigid_expense": "rigid_expenses_12m",
    "rigid_expense_ratio": "rigid_expenses_12m",
    "rigid_income_ceiling": "monthly_income_total",
    "urgent_event": "urgent_event",
    "basic_life": "basic_life_interrupted",
    "special_category": "special_person_category_confirmed",
    "no_labor_capacity": "no_labor_capacity",
    "no_livelihood_source": "no_livelihood_source",
    "capable_legal_supporter": "has_capable_legal_supporter",
}


def _condition(
    *,
    code: str,
    label: str,
    state: TruthValue,
    reason: str,
    actual: str | int | float | None = None,
    expected: str | None = None,
    evidence_ids: Iterable[str] = (),
    hard: bool = True,
    actionable: bool = False,
    action_hint: str | None = None,
) -> ConditionResult:
    return ConditionResult(
        code=code,
        label=label,
        state=state,
        reason=reason,
        actual=actual,
        expected=expected,
        evidence_ids=list(evidence_ids),
        hard=hard,
        actionable=actionable,
        action_hint=action_hint,
        input_field=CONDITION_INPUT_FIELDS.get(code) if actionable else None,
    )


def _known_boolean(
    value: bool | None,
    *,
    code: str,
    label: str,
    true_reason: str,
    false_reason: str,
    unknown_reason: str,
    evidence_ids: Iterable[str],
    action_hint: str,
    hard: bool = True,
) -> ConditionResult:
    if value is True:
        return _condition(
            code=code,
            label=label,
            state=TruthValue.TRUE,
            reason=true_reason,
            evidence_ids=evidence_ids,
            hard=hard,
        )
    if value is False:
        return _condition(
            code=code,
            label=label,
            state=TruthValue.FALSE,
            reason=false_reason,
            evidence_ids=evidence_ids,
            hard=hard,
        )
    return _condition(
        code=code,
        label=label,
        state=TruthValue.UNKNOWN,
        reason=unknown_reason,
        evidence_ids=evidence_ids,
        hard=hard,
        actionable=True,
        action_hint=action_hint,
    )


def _income_condition(
    profile: HouseholdProfile,
    threshold: Decimal,
    code: str,
    *,
    inclusive: bool,
    hard: bool = True,
) -> ConditionResult:
    income = profile.per_capita_monthly_income
    if income is None:
        return _condition(
            code=code,
            label="家庭人均月收入",
            state=TruthValue.UNKNOWN,
            reason="尚未提供家庭月收入，无法计算人均收入。",
            expected=f"需与{threshold}元/人/月标准比较",
            evidence_ids=("E-CN-001-DIBAO", "E-GZ-003-STANDARD"),
            actionable=True,
            action_hint="补充共同生活家庭成员数和近6个月家庭收入。",
            hard=hard,
        )
    meets_threshold = income <= threshold if inclusive else income < threshold
    state = TruthValue.TRUE if meets_threshold else TruthValue.FALSE
    comparator_text = "不高于" if inclusive else "低于"
    return _condition(
        code=code,
        label="家庭人均月收入",
        state=state,
        reason=(
            f"预估人均月收入{comparator_text}当前年度标准。"
            if state == TruthValue.TRUE
            else "预估人均月收入高于当前年度标准。"
        ),
        actual=f"{income}元/人/月",
        expected=f"{comparator_text}{threshold}元/人/月",
        evidence_ids=("E-CN-001-DIBAO", "E-GZ-003-STANDARD"),
        actionable=state == TruthValue.FALSE,
        action_hint="核对收入周期、共同生活成员范围和政策允许扣减项目。"
        if state == TruthValue.FALSE
        else None,
        hard=hard,
    )


def _household_hukou_condition(
    profile: HouseholdProfile, evidence_ids: tuple[str, ...]
) -> ConditionResult:
    """本地户籍条件与地区覆盖是两个独立概念，不能只凭district放行。"""

    if profile.city != "广州市":
        return _condition(
            code="region",
            label="适用地区",
            state=TruthValue.FALSE,
            reason="当前规则库只覆盖广州市。",
            actual=profile.city,
            expected="广州市",
            actionable=True,
            action_hint="切换到当地官方社会救助渠道咨询。",
        )
    if profile.is_local_hukou is True or profile.has_local_family_member is True:
        return _condition(
            code="hukou",
            label="本地户籍家庭成员",
            state=TruthValue.TRUE,
            reason="已确认申请人或共同生活家庭成员具有广州户籍。",
            evidence_ids=evidence_ids,
        )
    if profile.is_local_hukou is False and profile.has_local_family_member is False:
        return _condition(
            code="hukou",
            label="本地户籍家庭成员",
            state=TruthValue.FALSE,
            reason="当前信息显示申请人及共同生活家庭成员均无广州户籍。",
            evidence_ids=evidence_ids,
            actionable=True,
            action_hint="核对共同生活家庭成员中是否有人具有广州户籍。",
        )
    return _condition(
        code="hukou",
        label="本地户籍家庭成员",
        state=TruthValue.UNKNOWN,
        reason="尚未确认申请人或共同生活家庭成员是否具有广州户籍。",
        evidence_ids=evidence_ids,
        actionable=True,
        action_hint="补充申请人及共同生活家庭成员的户籍情况。",
    )


def _residency_condition(profile: HouseholdProfile, *, temporary: bool = False) -> ConditionResult:
    if profile.city != "广州市":
        return _condition(
            code="region",
            label="适用地区",
            state=TruthValue.FALSE,
            reason="当前规则库只覆盖广州市。",
            actual=profile.city,
            expected="广州市",
            actionable=True,
            action_hint="切换到当地官方社会救助渠道咨询。",
        )
    if temporary:
        if profile.is_local_hukou is True or profile.residence_proof is True:
            return _condition(
                code="residence",
                label="户籍或居住条件",
                state=TruthValue.TRUE,
                reason="已确认广州户籍或有效居住证明之一。",
                evidence_ids=("E-GZ-005-RESIDENCE",),
            )
        if profile.is_local_hukou is False and profile.residence_proof is False:
            return _condition(
                code="residence",
                label="户籍或居住条件",
                state=TruthValue.FALSE,
                reason="异地申请但未提供广州有效居住证明。",
                evidence_ids=("E-GZ-005-RESIDENCE",),
                actionable=True,
                action_hint="核对是否有广州居住证或连续居住证明；紧急情形请直接联系街道。",
            )
        return _condition(
            code="residence",
            label="户籍或居住条件",
            state=TruthValue.UNKNOWN,
            reason="尚未确认广州户籍或居住证明。",
            evidence_ids=("E-GZ-005-RESIDENCE",),
            actionable=True,
            action_hint="补充户籍情况；非广州户籍请确认居住证明。",
        )
    return _condition(
        code="region",
        label="适用地区",
        state=TruthValue.TRUE,
        reason="当前查询地区在广州市规则覆盖范围内。",
        actual=profile.district,
        expected="广州市辖区",
        evidence_ids=("E-GZ-001-SCOPE",),
    )


def _aggregate_status(
    conditions: list[ConditionResult], *, force_manual: bool = False
) -> EligibilityStatus:
    if force_manual:
        return EligibilityStatus.MANUAL_REVIEW
    hard = [condition for condition in conditions if condition.hard]
    if any(condition.state == TruthValue.FALSE for condition in hard):
        return EligibilityStatus.UNLIKELY
    if any(condition.state == TruthValue.UNKNOWN for condition in hard):
        return EligibilityStatus.INCOMPLETE
    return EligibilityStatus.LIKELY


def _score(conditions: list[ConditionResult], status: EligibilityStatus, boost: float = 0) -> float:
    weights = {TruthValue.TRUE: 1.0, TruthValue.UNKNOWN: 0.45, TruthValue.FALSE: 0.0}
    hard = [condition for condition in conditions if condition.hard]
    base = sum(weights[c.state] for c in hard) / max(len(hard), 1) * 82
    if status == EligibilityStatus.LIKELY:
        base += 12
    elif status == EligibilityStatus.MANUAL_REVIEW:
        base = min(base, 58)
    elif status == EligibilityStatus.UNLIKELY:
        base = min(base, 35)
    return round(max(0, min(100, base + boost)), 1)


def _missing(conditions: list[ConditionResult]) -> list[str]:
    return [
        condition.action_hint or condition.label
        for condition in conditions
        if condition.state == TruthValue.UNKNOWN and condition.actionable
    ]


def _minimum_completion_plan(conditions: list[ConditionResult]) -> list[str]:
    """返回继续判断所需的最小补充集合，不把失败阈值包装成改变建议。"""

    hard_unknown = [
        condition.action_hint or condition.label
        for condition in conditions
        if condition.hard
        and condition.state == TruthValue.UNKNOWN
        and condition.actionable
    ]
    # 同一条补证建议可能被多个规则条件引用，保持原始优先顺序并去重。
    return list(dict.fromkeys(hard_unknown))


def _summary(status: EligibilityStatus, name: str) -> str:
    return {
        EligibilityStatus.LIKELY: f"现有信息支持将{name}列为优先咨询事项。",
        EligibilityStatus.UNLIKELY: f"现有信息存在不满足{name}预筛条件的项目，请核对详情。",
        EligibilityStatus.INCOMPLETE: f"{name}仍缺少关键资料，补充后才能继续判断。",
        EligibilityStatus.MANUAL_REVIEW: f"{name}涉及政策版本或复杂比例，建议携带材料人工核验。",
    }[status]


def _build_result(
    *,
    benefit_id: str,
    name: str,
    conditions: list[ConditionResult],
    evidence_ids: tuple[str, ...],
    materials: list[str],
    next_actions: list[str],
    deadline: str,
    snapshot: PolicySnapshot,
    policy_version: str,
    force_manual: bool = False,
    boost: float = 0,
) -> BenefitResult:
    status = _aggregate_status(conditions, force_manual=force_manual)
    evidence = [
        item
        for item in evidence_for(*evidence_ids)
        if (item.effective_from is None or item.effective_from <= snapshot.query_date)
        and (item.effective_to is None or snapshot.query_date <= item.effective_to)
    ]
    return BenefitResult(
        benefit_id=benefit_id,
        name=name,
        status=status,
        score=_score(conditions, status, boost=boost),
        summary=_summary(status, name),
        conditions=conditions,
        evidence=evidence,
        missing_items=_missing(conditions),
        next_actions=next_actions,
        materials=materials,
        deadline=deadline,
        policy_version=policy_version,
        policy_snapshot=snapshot.snapshot_id,
        official_only=False,
        minimal_required_inputs=_minimum_completion_plan(conditions),
    )


def evaluate_dibao(profile: HouseholdProfile, snapshot: PolicySnapshot) -> BenefitResult:
    dated_rule = get_rule_for_date("B002", profile.query_date)
    threshold_value = (
        dated_rule.parameters.get("income_standard_monthly_per_capita")
        if dated_rule is not None
        else None
    )
    threshold = Decimal(str(threshold_value)) if threshold_value is not None else None
    local_evidence_id = (
        "E-GZ-009-LEGACY"
        if dated_rule is not None and dated_rule.version in {"v2023.06", "v2026.01"}
        else "E-GZ-002-CURRENT"
    )
    asset_evidence_id = (
        "E-GZ-009-ASSET"
        if dated_rule is not None and dated_rule.version in {"v2023.06", "v2026.01"}
        else "E-GZ-002-ASSET"
    )
    if threshold is None:
        income = profile.per_capita_monthly_income
        income_condition = _condition(
            code="dibao_income",
            label="家庭人均月收入",
            state=TruthValue.UNKNOWN,
            reason=(
                "查询年度的低保金额标准尚未登记，系统未套用2026年标准。"
                if dated_rule is not None
                else "查询日期未命中已核验的低保规则与年度金额标准。"
            ),
            actual=f"{income}元/人/月" if income is not None else None,
            expected="人工核验查询年度有效的低保金额标准",
            evidence_ids=(local_evidence_id,),
            actionable=True,
            action_hint="请向街镇社会救助窗口核验查询年度适用的低保金额标准。",
            hard=True,
        )
    else:
        income_condition = _income_condition(
            profile,
            threshold,
            "dibao_income",
            inclusive=False,
            # 共同生活成员范围未确认时，分母不可靠，收入比较只能作为提示。
            hard=profile.member_scope_confirmed is not None,
        )
    conditions = [
        _household_hukou_condition(profile, ("E-CN-001-DIBAO",)),
        income_condition,
        _known_boolean(
            profile.assets_eligible,
            code="assets",
            label="家庭财产状况",
            true_reason="申报信息显示财产状况未发现超标项。",
            false_reason="申报信息显示存在财产条件不满足项。",
            unknown_reason="尚未确认房产、车辆、金融资产等财产状况。",
            evidence_ids=("E-CN-001-DIBAO", asset_evidence_id),
            action_hint="补充家庭财产信息：房产、车辆、金融资产和经营投资情况。",
        ),
        _known_boolean(
            profile.member_scope_confirmed,
            code="member_scope",
            label="共同生活成员范围",
            true_reason="已确认共同生活家庭成员范围。",
            false_reason="共同生活成员范围可能不完整。",
            unknown_reason="尚未确认共同生活成员范围。",
            evidence_ids=("E-CN-001-DIBAO",),
            action_hint="确认共同生活家庭成员及赡养、抚养关系。",
        ),
    ]
    income = profile.per_capita_monthly_income
    other_hard_conditions = [condition for condition in conditions if condition.code != "dibao_income"]
    exact_boundary_review = threshold is not None and income == threshold and all(
        condition.state == TruthValue.TRUE for condition in other_hard_conditions
    )
    force_manual = (
        not snapshot.local_rule_available
        or dated_rule is None
        or dated_rule.manual_review_required
        or exact_boundary_review
    )
    return _build_result(
        benefit_id="B002",
        name="最低生活保障",
        conditions=conditions,
        evidence_ids=(
            "E-CN-001-DIBAO",
            local_evidence_id,
            asset_evidence_id,
            *(("E-GZ-003-STANDARD",) if threshold is not None else ()),
            "E-GZ-001-DEADLINE",
        ),
        materials=["身份类证明", "家庭经济状况核对授权书", "收入与财产相关证明"],
        next_actions=["核对共同生活家庭成员", "准备家庭经济状况核对授权", "通过官方渠道提交申请"],
        deadline="通常34个工作日，以官方受理为准",
        snapshot=snapshot,
        policy_version=snapshot.dibao_version,
        force_manual=force_manual,
    )


def evaluate_edge(profile: HouseholdProfile, snapshot: PolicySnapshot) -> BenefitResult:
    dated_rule = get_rule_for_date("B003", profile.query_date)
    threshold_value = (
        dated_rule.parameters.get("income_standard_monthly_per_capita")
        if dated_rule is not None
        else None
    )
    threshold = Decimal(str(threshold_value)) if threshold_value is not None else None
    income_condition = (
        _income_condition(profile, threshold, "edge_income", inclusive=True)
        if threshold is not None
        else _condition(
            code="edge_income",
            label="家庭人均月收入",
            state=TruthValue.UNKNOWN,
            reason="查询年度的低保边缘家庭金额标准尚未登记，系统未套用2026年标准。",
            actual=(
                f"{profile.per_capita_monthly_income}元/人/月"
                if profile.per_capita_monthly_income is not None
                else None
            ),
            expected="人工核验查询年度有效的低保边缘家庭金额标准",
            evidence_ids=("E-GD-002-EDGE",),
            actionable=True,
            action_hint="请向街镇社会救助窗口核验查询年度适用的低保边缘家庭标准。",
        )
    )
    conditions = [
        _household_hukou_condition(profile, ("E-GD-002-EDGE",)),
        income_condition,
        _known_boolean(
            profile.assets_eligible,
            code="assets",
            label="家庭财产状况",
            true_reason="申报信息显示财产状况未发现超标项。",
            false_reason="申报信息显示存在财产条件不满足项。",
            unknown_reason="尚未确认家庭财产状况。",
            evidence_ids=("E-CN-001-EDGE", "E-GZ-002-ASSET"),
            action_hint="补充家庭财产信息：房产、车辆、金融资产和经营投资情况。",
        ),
        _known_boolean(
            profile.member_scope_confirmed,
            code="member_scope",
            label="共同生活成员范围",
            true_reason="已确认共同生活家庭成员范围。",
            false_reason="共同生活成员范围可能不完整。",
            unknown_reason="尚未确认共同生活成员范围。",
            evidence_ids=("E-CN-001-EDGE",),
            action_hint="确认共同生活家庭成员。",
        ),
    ]
    force_manual = (
        dated_rule is None
        or dated_rule.manual_review_required
        or threshold is None
    )
    return _build_result(
        benefit_id="B003",
        name="最低生活保障边缘家庭认定",
        conditions=conditions,
        evidence_ids=(
            "E-CN-001-EDGE",
            *(("E-GZ-003-STANDARD",) if threshold is not None else ()),
            "E-GZ-004-EXPENSE",
            "E-GZ-001-DEADLINE",
        ),
        materials=["身份类证明", "家庭经济状况核对授权书", "收入和财产情况材料"],
        next_actions=["核对年度收入和财产", "咨询可衔接的医疗、教育、住房等专项救助"],
        deadline="通常34个工作日，以官方受理为准",
        snapshot=snapshot,
        policy_version=(
            "穗民规字〔2022〕3号 + 2026年度标准"
            if threshold is not None
            else "历史/未来年度金额参数未登记"
        ),
        force_manual=force_manual,
    )


def evaluate_rigid_expense(profile: HouseholdProfile, snapshot: PolicySnapshot) -> BenefitResult:
    dated_rule = get_rule_for_date("B004", profile.query_date)
    parameters = dated_rule.parameters if dated_rule is not None else {}
    ratio_value = parameters.get("rigid_expense_ratio")
    ceiling_value = parameters.get("income_ceiling_annual_per_capita")
    reference_year_value = parameters.get("income_reference_year")
    ratio_threshold = Decimal(str(ratio_value)) if ratio_value is not None else None
    income_ceiling = Decimal(str(ceiling_value)) if ceiling_value is not None else None
    income_reference_year = (
        int(reference_year_value) if reference_year_value is not None else None
    )
    parameter_is_current = (
        dated_rule is not None
        and not dated_rule.manual_review_required
        and income_ceiling is not None
        and income_reference_year is not None
        and profile.query_date.year == income_reference_year + 1
    )
    annual_income = (
        profile.adjusted_monthly_income * Decimal("12")
        if profile.adjusted_monthly_income is not None
        else None
    )
    expense = profile.rigid_expenses_12m
    if expense is None:
        expense_condition = _condition(
            code="rigid_expense",
            label="近12个月刚性支出",
            state=TruthValue.UNKNOWN,
            reason="未提供医疗、教育等必需支出。",
            evidence_ids=("E-CN-001-RIGID", "E-GZ-004-EXPENSE"),
            actionable=True,
            action_hint="补充近12个月医疗、教育、康复等必要支出凭据。",
        )
    elif expense <= 0:
        expense_condition = _condition(
            code="rigid_expense",
            label="近12个月刚性支出",
            state=TruthValue.FALSE,
            reason="当前未申报医疗、教育等刚性支出。",
            actual="0元",
            evidence_ids=("E-CN-001-RIGID",),
        )
    elif annual_income is None:
        expense_condition = _condition(
            code="rigid_expense",
            label="近12个月刚性支出",
            state=TruthValue.UNKNOWN,
            reason="已申报刚性支出，但缺少家庭收入，无法计算支出比例。",
            actual=f"{expense}元",
            evidence_ids=("E-GD-002-RIGID", "E-GZ-004-EXPENSE"),
            actionable=True,
            action_hint="补充家庭月收入，用于计算近12个月刚性支出比例。",
        )
    elif ratio_threshold is None:
        expense_condition = _condition(
            code="rigid_expense_ratio",
            label="近12个月刚性支出比例",
            state=TruthValue.UNKNOWN,
            reason="查询日期未命中已核验的刚性支出比例参数。",
            actual=f"{expense}元",
            expected="人工核验查询年度有效的刚性支出比例",
            evidence_ids=("E-GD-002-RIGID", "E-GZ-004-EXPENSE"),
            actionable=True,
            action_hint="请工作人员核验查询年度适用的刚性支出比例。",
        )
    else:
        ratio = Decimal("Infinity") if annual_income == 0 else expense / annual_income
        ratio_ok = ratio >= ratio_threshold
        expense_condition = _condition(
            code="rigid_expense_ratio",
            label="近12个月刚性支出比例",
            state=TruthValue.TRUE if ratio_ok else TruthValue.FALSE,
            reason=(
                "申报刚性支出达到家庭年收入的60%，可进入材料核验。"
                if ratio_ok
                else "申报刚性支出未达到家庭年收入的60%。"
            ),
            actual=(
                f"{expense}元，家庭年收入为0元"
                if ratio.is_infinite()
                else f"{expense}元，约占家庭年收入{ratio:.1%}"
            ),
            expected=f"达到或超过{ratio_threshold:.0%}",
            evidence_ids=("E-GD-002-RIGID", "E-GZ-004-EXPENSE"),
        )

    per_capita_annual_income = (
        None
        if annual_income is None
        else (annual_income / Decimal(profile.household_size)).quantize(Decimal("0.01"))
    )
    if not parameter_is_current or income_ceiling is None:
        income_ceiling_condition = _condition(
            code="rigid_income_ceiling",
            label="家庭人均年收入上限",
            state=TruthValue.UNKNOWN,
            reason="当前只发布了2026年预筛使用的2025年度收入参数。",
            evidence_ids=("E-GZ-008-INCOME", "E-GD-002-RIGID"),
            actionable=True,
            action_hint="请工作人员核验查询年度对应的上年度居民人均可支配收入。",
        )
    elif per_capita_annual_income is None:
        income_ceiling_condition = _condition(
            code="rigid_income_ceiling",
            label="家庭人均年收入上限",
            state=TruthValue.UNKNOWN,
            reason="缺少家庭收入，无法与上年度居民人均可支配收入比较。",
            evidence_ids=("E-GZ-008-INCOME", "E-GD-002-RIGID"),
            actionable=True,
            action_hint="补充家庭收入。",
        )
    else:
        income_ok = per_capita_annual_income < income_ceiling
        income_ceiling_condition = _condition(
            code="rigid_income_ceiling",
            label="家庭人均年收入上限",
            state=TruthValue.TRUE if income_ok else TruthValue.FALSE,
            reason=(
                "家庭人均年收入低于2025年广州市城镇居民人均可支配收入。"
                if income_ok
                else "家庭人均年收入未低于2025年广州市城镇居民人均可支配收入。"
            ),
            actual=f"{per_capita_annual_income}元/人/年",
            expected=f"低于{income_ceiling}元/人/年",
            evidence_ids=("E-GZ-008-INCOME", "E-GD-002-RIGID"),
        )
    conditions = [
        _household_hukou_condition(profile, ("E-GD-002-RIGID",)),
        expense_condition,
        income_ceiling_condition,
        _known_boolean(
            profile.assets_eligible,
            code="assets",
            label="家庭财产状况",
            true_reason="申报信息显示财产状况未发现超标项。",
            false_reason="申报信息显示存在财产条件不满足项。",
            unknown_reason="尚未确认家庭财产状况。",
            evidence_ids=("E-CN-001-RIGID",),
            action_hint="补充财产状况并由官方核对。",
        ),
        _known_boolean(
            profile.member_scope_confirmed,
            code="member_scope",
            label="共同生活成员范围",
            true_reason="已确认共同生活家庭成员范围。",
            false_reason="共同生活成员范围可能不完整。",
            unknown_reason="尚未确认共同生活成员范围。",
            evidence_ids=("E-GD-002-RIGID",),
            action_hint="确认共同生活家庭成员及赡养、抚养关系。",
        ),
    ]
    return _build_result(
        benefit_id="B004",
        name="刚性支出困难家庭认定",
        conditions=conditions,
        evidence_ids=(
            "E-CN-001-RIGID",
            "E-GD-002-RIGID",
            "E-GZ-004-EXPENSE",
            *(("E-GZ-008-INCOME",) if parameter_is_current else ()),
            "E-GZ-001-DEADLINE",
        ),
        materials=["身份类证明", "经济状况核对授权书", "近12个月医疗/教育等支出凭据", "收入和财产材料"],
        next_actions=["整理近12个月有效支出凭据", "请街道核定支出范围与比例"],
        deadline="通常34个工作日，以官方受理为准",
        snapshot=snapshot,
        policy_version=(
            "穗民规字〔2022〕3号及省级配套办法（2026参数）"
            if parameter_is_current
            else "穗民规字〔2022〕3号（年度收入上限参数待核验）"
        ),
        force_manual=(
            dated_rule is None
            or dated_rule.manual_review_required
            or not parameter_is_current
        ),
        boost=6 if expense and expense > 0 else 0,
    )


def evaluate_temporary(profile: HouseholdProfile, snapshot: PolicySnapshot) -> BenefitResult:
    policy_warning = temporary_policy_warning(profile.query_date)
    event_boundary_review = False
    if profile.urgent_event is None:
        event_condition = _condition(
            code="urgent_event",
            label="急难或突发事件",
            state=TruthValue.UNKNOWN,
            reason="尚未说明近期是否发生急难或突发事件，系统不会将未填写视为没有发生。",
            evidence_ids=("E-GZ-005-URGENT",),
            actionable=True,
            action_hint="请确认近期是否发生突发事件、重大疾病或其他临时困难。",
        )
    elif profile.urgent_event is False:
        event_condition = _condition(
            code="urgent_event",
            label="急难或突发事件",
            state=TruthValue.FALSE,
            reason="当前未申报突发事件、重大疾病或其他临时困难。",
            evidence_ids=("E-GZ-005-URGENT",),
        )
    elif profile.urgent_event_date is None:
        event_condition = _condition(
            code="urgent_event",
            label="急难或突发事件",
            state=TruthValue.UNKNOWN,
            reason="已申报急难事件，但缺少发生日期。",
            evidence_ids=("E-GZ-005-URGENT",),
            actionable=True,
            action_hint="补充事件发生日期和基本生活受影响情况。",
        )
    else:
        days = (profile.query_date - profile.urgent_event_date).days
        # “申请日前一个月内”存在自然月与30/31日两种口径；临界值不自动放行。
        recent = 0 <= days < 30
        event_boundary_review = days in {30, 31}
        event_condition = _condition(
            code="urgent_event",
            label="急难或突发事件",
            state=TruthValue.TRUE if recent else TruthValue.FALSE,
            reason=(
                "事件发生在查询日前一个月内，可优先咨询急难型临时救助。"
                if recent
                else (
                    "事件处于‘申请日前一个月内’的30/31日口径边界，需要人工核验。"
                    if event_boundary_review
                    else "事件已超过一个月；可进一步核对是否属于支出型临时救助。"
                )
            ),
            actual=f"距查询日{days}天",
            expected="急难型事由通常在申请日前1个月内",
            evidence_ids=("E-GZ-005-URGENT",),
            actionable=not recent,
            action_hint=(
                "请街道结合申请日和自然月口径人工核验。"
                if event_boundary_review
                else "携带近12个月支出凭据，咨询支出型临时救助。"
            )
            if not recent
            else None,
        )
    life_condition = _known_boolean(
        profile.basic_life_interrupted,
        code="basic_life",
        label="基本生活受影响",
        true_reason="申报信息显示基本生活暂时受到严重影响。",
        false_reason="申报信息显示基本生活尚未受到严重影响。",
        unknown_reason="尚未说明事件是否导致基本生活暂时陷入困难。",
        evidence_ids=("E-GZ-005-URGENT",),
        action_hint="说明事件对基本生活造成的具体影响。",
    )
    conditions = [
        _residency_condition(profile, temporary=True),
        event_condition,
        life_condition,
    ]
    boundary_review = event_boundary_review and all(
        condition.state == TruthValue.TRUE
        for condition in conditions
        if condition.code != "urgent_event"
    )
    return _build_result(
        benefit_id="B005",
        name="临时救助",
        conditions=conditions,
        evidence_ids=("E-GZ-005-URGENT", "E-GZ-005-RESIDENCE", "E-GZ-001-DEADLINE"),
        materials=["身份类证明", "事件或诊断材料", "相关支出凭据", "居住证明（异地申请时）"],
        next_actions=["紧急情况优先联系所在街道或12345", "准备事件和支出凭据"],
        deadline="急难型按政策快速办理；一般事项以官方告知为准",
        snapshot=snapshot,
        policy_version="穗府办规〔2021〕19号",
        force_manual=(
            (policy_warning is not None and profile.query_date > TEMPORARY_RESCUE_END)
            or boundary_review
        ),
        boost=18
        if profile.urgent_event is True and profile.basic_life_interrupted is True
        else 0,
    )


def evaluate_special_hardship(
    profile: HouseholdProfile, snapshot: PolicySnapshot
) -> BenefitResult:
    """Evaluate only the statutory gateway facts for special hardship support.

    The four inputs are self-reported consultation clues.  The authority must
    still investigate labor capacity, livelihood and the legal obligor's
    ability; this function never treats a self-report as an official finding.
    """

    evidence_ids = ("E-CN-001-SPECIAL-HARDSHIP",)
    category = _known_boolean(
        profile.special_person_category_confirmed,
        code="special_category",
        label="特困人员适用对象线索",
        true_reason="已申报申请人属于老年人、未成年人、残疾人等需要进一步核验的对象。",
        false_reason="当前申报未发现特困人员适用对象线索。",
        unknown_reason="尚未确认申请人是否属于老年人、未成年人、残疾人等适用对象。",
        evidence_ids=evidence_ids,
        action_hint="确认申请人是否属于老年人、未成年人、残疾人等需要核验的对象。",
    )
    labor = _known_boolean(
        profile.no_labor_capacity,
        code="no_labor_capacity",
        label="劳动能力",
        true_reason="已申报无劳动能力；仍需主管部门按认定办法核实。",
        false_reason="当前申报显示仍有劳动能力。",
        unknown_reason="尚未说明劳动能力情况。",
        evidence_ids=evidence_ids,
        action_hint="说明申请人的劳动能力情况，并准备相应证明材料供窗口核验。",
    )
    livelihood = _known_boolean(
        profile.no_livelihood_source,
        code="no_livelihood_source",
        label="生活来源",
        true_reason="已申报无生活来源；仍需主管部门核实收入和供给情况。",
        false_reason="当前申报显示存在生活来源。",
        unknown_reason="尚未说明是否具有生活来源。",
        evidence_ids=evidence_ids,
        action_hint="说明工资、经营、养老金、赡养费等生活来源情况。",
    )
    supporter_value = profile.has_capable_legal_supporter
    if supporter_value is None:
        supporter = _condition(
            code="capable_legal_supporter",
            label="法定赡养抚养扶养支持",
            state=TruthValue.UNKNOWN,
            reason="尚未确认是否存在有履行能力的法定赡养、抚养或扶养义务人。",
            evidence_ids=evidence_ids,
            actionable=True,
            action_hint="确认是否有法定义务人，以及义务人是否具有履行义务能力。",
        )
    elif supporter_value is False:
        supporter = _condition(
            code="capable_legal_supporter",
            label="法定赡养抚养扶养支持",
            state=TruthValue.TRUE,
            reason="已申报无法定义务人，或法定义务人无履行能力；仍需主管部门核实。",
            evidence_ids=evidence_ids,
        )
    else:
        supporter = _condition(
            code="capable_legal_supporter",
            label="法定赡养抚养扶养支持",
            state=TruthValue.FALSE,
            reason="当前申报显示存在有履行能力的法定赡养、抚养或扶养义务人。",
            evidence_ids=evidence_ids,
            actionable=True,
            action_hint="如义务人实际无法履行，请携带相关情况说明由窗口核验。",
        )
    dated_rule = get_rule_for_date("B006", profile.query_date)
    conditions = [
        _household_hukou_condition(profile, ("E-CN-001-SPECIAL-APPLICATION",)),
        category,
        labor,
        livelihood,
        supporter,
    ]
    return _build_result(
        benefit_id="B006",
        name="特困人员救助供养",
        conditions=conditions,
        evidence_ids=(
            "E-CN-001-SPECIAL-HARDSHIP",
            "E-CN-001-SPECIAL-APPLICATION",
            "E-GZ-001-DEADLINE",
        ),
        materials=[
            "身份类证明",
            "劳动能力、生活来源和法定赡养抚养扶养情况材料（以窗口告知为准）",
        ],
        next_actions=[
            "向户籍所在地街镇社会救助窗口说明个人情况",
            "由主管部门核验劳动能力、生活来源和法定义务人履行能力",
        ],
        deadline="通常34个工作日，以官方受理为准",
        snapshot=snapshot,
        policy_version="中华人民共和国社会救助法（2026）第十六条",
        force_manual=dated_rule is None or dated_rule.manual_review_required,
        boost=10
        if all(
            value is True
            for value in (
                profile.special_person_category_confirmed,
                profile.no_labor_capacity,
                profile.no_livelihood_source,
            )
        )
        and profile.has_capable_legal_supporter is False
        else 0,
    )


def evaluate_low_income_monitoring(
    profile: HouseholdProfile, snapshot: PolicySnapshot, downstream: list[BenefitResult]
) -> BenefitResult:
    # 临时救助是事件型救助，不能单独证明属于低收入人口。这里只依据三类
    # 家庭经济状况认定事项派生监测结论，避免“任何B004人工复核都令B001通过”。
    candidates = [
        result
        for result in downstream
        if result.benefit_id in {"B002", "B003", "B004", "B006"}
    ]
    likely = [result for result in candidates if result.status == EligibilityStatus.LIKELY]
    incomplete = [result for result in candidates if result.status == EligibilityStatus.INCOMPLETE]
    manual = [result for result in candidates if result.status == EligibilityStatus.MANUAL_REVIEW]
    if likely:
        state = TruthValue.TRUE
        reason = f"已发现{len(likely)}项符合预筛条件的低收入人口认定线索。"
        actionable = False
        action_hint = None
    elif incomplete:
        state = TruthValue.UNKNOWN
        reason = "特困供养或家庭经济状况认定仍缺少关键信息。"
        actionable = True
        action_hint = "先补充相关事项列出的最小信息缺口。"
    elif manual:
        state = TruthValue.UNKNOWN
        reason = "相关认定事项涉及历史版本或未发布参数，需要人工核验。"
        actionable = True
        action_hint = "携带家庭经济和支出材料到街镇社会救助窗口核验。"
    else:
        state = TruthValue.FALSE
        reason = "当前输入在系统已覆盖的低收入人口类别中未发现符合线索。"
        actionable = False
        action_hint = None
    condition = _condition(
        code="related_candidates",
        label="困难情形线索",
        state=state,
        reason=reason,
        actual=len(likely),
        evidence_ids=("E-GZ-001-SCOPE",),
        actionable=actionable,
        action_hint=action_hint,
    )
    conditions = [_residency_condition(profile), condition]
    return _build_result(
        benefit_id="B001",
        name="低收入人口认定与监测",
        conditions=conditions,
        evidence_ids=("E-GZ-001-SCOPE", "E-GZ-001-MATERIALS", "E-GZ-001-DEADLINE"),
        materials=["身份类证明", "家庭经济状况核对授权书", "具体事项要求材料"],
        next_actions=["向户籍地或常住地街镇社会救助窗口咨询", "核对系统列出的候选事项"],
        deadline="通常34个工作日，以官方受理为准",
        snapshot=snapshot,
        policy_version="广州市社会救助“一件事”办事指南（2026）",
        force_manual=bool(manual and not likely and not incomplete),
        boost=4 if likely else 0,
    )


def evaluate_profile(profile: HouseholdProfile) -> tuple[PolicySnapshot, list[BenefitResult], list[str]]:
    snapshot = select_policy_snapshot(profile.query_date)
    dibao = evaluate_dibao(profile, snapshot)
    edge = evaluate_edge(profile, snapshot)
    rigid = evaluate_rigid_expense(profile, snapshot)
    temporary = evaluate_temporary(profile, snapshot)
    special = evaluate_special_hardship(profile, snapshot)
    low_income = evaluate_low_income_monitoring(
        profile, snapshot, [dibao, edge, rigid, temporary, special]
    )

    results = apply_combination_plan([temporary, special, dibao, edge, rigid, low_income])

    warnings = [
        "系统输出仅用于申请前预筛和导办，不具有行政审批效力。",
        "金额、收入与财产范围最终以主管部门核查为准。",
    ]
    if snapshot.warning:
        warnings.append(snapshot.warning)
    temp_warning = temporary_policy_warning(profile.query_date)
    if temp_warning:
        warnings.append(temp_warning)
    if profile.city != "广州市":
        warnings.append("当前仅维护广州市规则，已停止本地资格判断。")
    return snapshot, results, warnings

