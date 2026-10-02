from __future__ import annotations

from decimal import Decimal
from typing import Iterable

from app.config import settings
from app.domain.models import (
    BenefitResult,
    ConditionResult,
    EligibilityStatus,
    HouseholdProfile,
    TruthValue,
)
from app.services.catalog import evidence_for
from app.services.policy_version import (
    PolicySnapshot,
    TEMPORARY_RESCUE_END,
    select_policy_snapshot,
    temporary_policy_warning,
)
from app.services.rule_registry import decimal_parameter, get_rule, get_rule_for_date


DIBAO_STANDARD = decimal_parameter("B002", "income_standard_monthly_per_capita")
EDGE_STANDARD = decimal_parameter("B003", "income_standard_monthly_per_capita")
RIGID_EXPENSE_RATIO = decimal_parameter("B004", "rigid_expense_ratio")
RIGID_INCOME_CEILING = decimal_parameter("B004", "income_ceiling_annual_per_capita")
RIGID_INCOME_REFERENCE_YEAR = int(get_rule("B004").parameters["income_reference_year"])
ENGINE_VERSION = "rule-engine/0.4.1"


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
    threshold = (
        Decimal(str(dated_rule.parameters["income_standard_monthly_per_capita"]))
        if dated_rule is not None
        else DIBAO_STANDARD
    )
    local_evidence_id = (
        "E-GZ-009-LEGACY" if dated_rule is not None and dated_rule.version == "v2023.06" else "E-GZ-002-CURRENT"
    )
    asset_evidence_id = (
        "E-GZ-009-ASSET" if dated_rule is not None and dated_rule.version == "v2023.06" else "E-GZ-002-ASSET"
    )
    conditions = [
        _household_hukou_condition(profile, ("E-CN-001-DIBAO",)),
        _income_condition(
            profile,
            threshold,
            "dibao_income",
            inclusive=False,
            # 共同生活成员范围未确认时，分母不可靠，收入比较只能作为提示。
            hard=profile.member_scope_confirmed is not None,
        ),
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
    exact_boundary_review = income == threshold and all(
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
            "E-GZ-003-STANDARD",
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
    conditions = [
        _household_hukou_condition(profile, ("E-GD-002-EDGE",)),
        _income_condition(profile, EDGE_STANDARD, "edge_income", inclusive=True),
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
    force_manual = not get_rule("B003").is_effective(profile.query_date)
    return _build_result(
        benefit_id="B003",
        name="最低生活保障边缘家庭认定",
        conditions=conditions,
        evidence_ids=(
            "E-CN-001-EDGE",
            "E-GZ-003-STANDARD",
            "E-GZ-004-EXPENSE",
            "E-GZ-001-DEADLINE",
        ),
        materials=["身份类证明", "家庭经济状况核对授权书", "收入和财产情况材料"],
        next_actions=["核对年度收入和财产", "咨询可衔接的医疗、教育、住房等专项救助"],
        deadline="通常34个工作日，以官方受理为准",
        snapshot=snapshot,
        policy_version="穗民规字〔2022〕3号 + 2026年度标准",
        force_manual=force_manual,
    )


def evaluate_rigid_expense(profile: HouseholdProfile, snapshot: PolicySnapshot) -> BenefitResult:
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
    else:
        ratio = Decimal("Infinity") if annual_income == 0 else expense / annual_income
        ratio_ok = ratio >= RIGID_EXPENSE_RATIO
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
            expected=f"达到或超过{RIGID_EXPENSE_RATIO:.0%}",
            evidence_ids=("E-GD-002-RIGID", "E-GZ-004-EXPENSE"),
        )

    per_capita_annual_income = (
        None
        if annual_income is None
        else (annual_income / Decimal(profile.household_size)).quantize(Decimal("0.01"))
    )
    parameter_is_current = profile.query_date.year == RIGID_INCOME_REFERENCE_YEAR + 1
    if not parameter_is_current:
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
        income_ok = per_capita_annual_income < RIGID_INCOME_CEILING
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
            expected=f"低于{RIGID_INCOME_CEILING}元/人/年",
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
            "E-GZ-008-INCOME",
            "E-GZ-001-DEADLINE",
        ),
        materials=["身份类证明", "经济状况核对授权书", "近12个月医疗/教育等支出凭据", "收入和财产材料"],
        next_actions=["整理近12个月有效支出凭据", "请街道核定支出范围与比例"],
        deadline="通常34个工作日，以官方受理为准",
        snapshot=snapshot,
        policy_version="穗民规字〔2022〕3号及省级配套办法",
        force_manual=not get_rule("B004").is_effective(profile.query_date),
        boost=6 if expense and expense > 0 else 0,
    )


def evaluate_temporary(profile: HouseholdProfile, snapshot: PolicySnapshot) -> BenefitResult:
    policy_warning = temporary_policy_warning(profile.query_date)
    event_boundary_review = False
    if not profile.urgent_event:
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
        boost=18 if profile.urgent_event and profile.basic_life_interrupted else 0,
    )


def evaluate_low_income_monitoring(
    profile: HouseholdProfile, snapshot: PolicySnapshot, downstream: list[BenefitResult]
) -> BenefitResult:
    # 临时救助是事件型救助，不能单独证明属于低收入人口。这里只依据三类
    # 家庭经济状况认定事项派生监测结论，避免“任何B004人工复核都令B001通过”。
    candidates = [result for result in downstream if result.benefit_id in {"B002", "B003", "B004"}]
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
        reason = "低保、低保边缘或刚性支出困难认定仍缺少关键信息。"
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


def _apply_combination_plan(results: list[BenefitResult]) -> list[BenefitResult]:
    """把单事项资格线索编排为不重复、可执行的组合导办路径。"""

    by_id = {item.benefit_id: item for item in results}
    dibao_likely = by_id["B002"].status == EligibilityStatus.LIKELY
    for item in results:
        if item.status == EligibilityStatus.UNLIKELY:
            item.plan_role = "not_recommended"
            item.plan_reason = "当前信息存在不满足项，先核对条件，不列入本次主路径。"
        elif item.status == EligibilityStatus.MANUAL_REVIEW:
            item.plan_role = "manual"
            item.plan_reason = "规则涉及复杂比例或仍需人工裁量，携带材料到窗口核验。"
        elif item.status == EligibilityStatus.INCOMPLETE:
            item.plan_role = "alternative"
            item.plan_reason = "关键资料尚未齐全，补充最小缺口后再决定是否进入主路径。"
        elif item.benefit_id == "B005":
            item.plan_role = "primary"
            item.plan_reason = "存在近期急难且基本生活受影响，按快速响应优先级列为首要路径。"
        elif item.benefit_id == "B002":
            item.plan_role = "primary"
            item.plan_reason = "收入、财产和成员范围线索均通过，列为基本生活救助主路径。"
        elif item.benefit_id == "B003" and dibao_likely:
            item.plan_role = "alternative"
            item.plan_reason = "与低保属于分层认定关系；当前先咨询低保，本事项作为衔接备选，避免重复申请。"
        elif item.benefit_id == "B001":
            item.plan_role = "linked"
            item.plan_reason = "作为低收入人口监测和转介入口，与主救助事项联动办理。"
        else:
            item.plan_role = "primary"
            item.plan_reason = "当前线索支持列入优先咨询路径。"

    role_order = {"primary": 0, "linked": 1, "alternative": 2, "manual": 3, "not_recommended": 4}
    return sorted(results, key=lambda item: (role_order[item.plan_role], -item.score))


def evaluate_profile(profile: HouseholdProfile) -> tuple[PolicySnapshot, list[BenefitResult], list[str]]:
    snapshot = select_policy_snapshot(profile.query_date)
    dibao = evaluate_dibao(profile, snapshot)
    edge = evaluate_edge(profile, snapshot)
    rigid = evaluate_rigid_expense(profile, snapshot)
    temporary = evaluate_temporary(profile, snapshot)
    low_income = evaluate_low_income_monitoring(profile, snapshot, [dibao, edge, rigid, temporary])

    results = _apply_combination_plan([temporary, dibao, edge, rigid, low_income])

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

