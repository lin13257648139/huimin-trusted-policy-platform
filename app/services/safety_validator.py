from __future__ import annotations

from typing import Any

from app.domain.models import BenefitResult, HouseholdProfile

FORBIDDEN_DECISION_PHRASES = ("已经批准", "保证通过", "自动审批通过", "确定享受")


def safety_gate_passed(validation: dict[str, Any]) -> bool:
    """Return whether a screening may leave the trusted-computing boundary."""

    if validation.get("safe") is not True or validation.get("blocked") is not False:
        return False
    enforcement = validation.get("enforcement")
    if enforcement is None:
        # 兼容升级前已经保存、且验证器明确判定安全的本地记录。
        return True
    required = ("api_publish", "persistence", "presentation", "print_export")
    return all(enforcement.get(item) is True for item in required)


def validate_screening_output(
    profile: HouseholdProfile,
    results: list[BenefitResult],
    *,
    model_used: bool = False,
    degraded: bool = False,
) -> dict[str, Any]:
    """Validate evidence, time, uncertainty and product-boundary invariants.

    This is deliberately independent from ranking.  It cannot turn an uncertain
    result into an eligible result; it can only report or block unsafe output.
    """

    checks: list[dict[str, Any]] = []

    def add(identifier: str, passed: bool, detail: str, critical: bool = True) -> None:
        checks.append(
            {
                "id": identifier,
                "passed": passed,
                "critical": critical,
                "detail": detail,
            }
        )

    all_evidence = [item for result in results for item in result.evidence]
    add("policy_exists", bool(all_evidence), f"输出绑定 {len(all_evidence)} 条政策证据")
    wrong_region = profile.city != "广州市" and any(
        result.status.value in {"likely", "unlikely"} for result in results
    )
    add("region_scope", not wrong_region, "当前规则仅覆盖广州市")
    inactive = [
        item.evidence_id
        for item in all_evidence
        if (item.effective_from and profile.query_date < item.effective_from)
        or (item.effective_to and profile.query_date > item.effective_to)
    ]
    add("temporal_validity", not inactive, f"查询日不适用证据：{inactive}" if inactive else "证据均适用于查询日")
    unverified = [
        item.evidence_id
        for item in all_evidence
        if not item.quote_verified or not item.verbatim_quote or not item.source_sha256
    ]
    add("verbatim_evidence", not unverified, f"未完成逐字核验：{unverified}" if unverified else "引用具备逐字原文和原件指纹")
    unsafe_likely = []
    for result in results:
        if result.status.value != "likely":
            continue
        unknown_hard = [
            condition.code
            for condition in result.conditions
            if condition.hard and condition.state.value == "unknown"
        ]
        if unknown_hard:
            unsafe_likely.append({"benefit_id": result.benefit_id, "conditions": unknown_hard})
    add("unknown_preservation", not unsafe_likely, f"likely仍含未知硬条件：{unsafe_likely}" if unsafe_likely else "未知硬条件未被强制转为符合")
    # 对直接影响结论的可空布尔值做第二道独立核验。输入为 None 时，
    # 规则条件必须仍为 UNKNOWN，不能在任一中间层被静默转换为 false/true。
    all_conditions = [condition for result in results for condition in result.conditions]
    unknown_contracts = [
        ("assets_eligible", profile.assets_eligible, "assets"),
        ("member_scope_confirmed", profile.member_scope_confirmed, "member_scope"),
        ("urgent_event", profile.urgent_event, "urgent_event"),
        ("basic_life_interrupted", profile.basic_life_interrupted, "basic_life"),
    ]
    tri_state_violations: list[str] = []
    for field_name, value, condition_code in unknown_contracts:
        matched = [item for item in all_conditions if item.code == condition_code]
        if value is None and any(item.state.value != "unknown" for item in matched):
            tri_state_violations.append(field_name)
    add(
        "tri_state_preservation",
        not tri_state_violations,
        f"空值被错误转换：{tri_state_violations}"
        if tri_state_violations
        else "可空布尔事实保持TRUE/FALSE/UNKNOWN三值语义",
    )
    boundary_violations = [
        result.benefit_id
        for result in results
        if any(phrase in f"{result.summary}{result.plan_reason}" for phrase in FORBIDDEN_DECISION_PHRASES)
    ]
    add("decision_boundary", not boundary_violations, f"越界措辞：{boundary_violations}" if boundary_violations else "保持申请前导办边界")
    relation_violations: list[str] = []
    results_by_id = {result.benefit_id: result for result in results}
    dibao = results_by_id.get("B002")
    edge = results_by_id.get("B003")
    rigid = results_by_id.get("B004")
    if dibao and edge and rigid:
        if dibao.plan_role == "primary":
            duplicate_primary = [
                item.benefit_id for item in (edge, rigid) if item.plan_role == "primary"
            ]
            if duplicate_primary:
                relation_violations.append(
                    f"B002为主路径时仍存在重复主路径:{duplicate_primary}"
                )
        has_parallel = any(
            relation.relation_type == "parallel_assessment"
            for item in (edge, rigid)
            for relation in item.plan_relations
        )
        if has_parallel and dibao.status.value != "unlikely":
            relation_violations.append("B002尚未明确排除时错误启用B003/B004并行关系")
    for result in results:
        evidence_ids = {item.evidence_id for item in result.evidence}
        for relation in result.plan_relations:
            missing_relation_evidence = set(relation.evidence_ids) - evidence_ids
            if missing_relation_evidence:
                relation_violations.append(
                    f"{result.benefit_id}/{relation.relation_id}缺少关系证据:{sorted(missing_relation_evidence)}"
                )
    add(
        "benefit_relation_consistency",
        not relation_violations,
        "；".join(relation_violations)
        if relation_violations
        else "B002优先、B003/B004转介或并行关系一致且证据完整",
    )
    contradictions = []
    if profile.urgent_event is False and profile.urgent_event_date is not None:
        contradictions.append("urgent_event=false但存在事件日期")
    if profile.monthly_income_total is not None and profile.deductible_monthly_total > profile.monthly_income_total * 3:
        contradictions.append("扣减额异常高于月收入三倍")
    add("input_consistency", not contradictions, "；".join(contradictions) if contradictions else "未发现关键输入矛盾")
    add(
        "runtime_disclosure",
        True,
        f"model_used={str(model_used).lower()}, degraded={str(degraded).lower()}",
        critical=False,
    )
    failed = [item for item in checks if item["critical"] and not item["passed"]]
    allowed = not failed
    return {
        "safe": allowed,
        "blocked": not allowed,
        "validated_at_query_date": profile.query_date.isoformat(),
        "checks": checks,
        "failed_check_ids": [item["id"] for item in failed],
        "enforcement": {
            "api_publish": allowed,
            "persistence": allowed,
            "presentation": allowed,
            "print_export": allowed,
        },
        "boundary": "任一关键检查失败时，结果不得发布、落库、展示或打印导出。",
    }
