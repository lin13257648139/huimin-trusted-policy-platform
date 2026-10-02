from __future__ import annotations

from datetime import date
from typing import Any

from app.domain.models import BenefitResult, HouseholdProfile


FORBIDDEN_DECISION_PHRASES = ("已经批准", "保证通过", "自动审批通过", "确定享受")


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
    boundary_violations = [
        result.benefit_id
        for result in results
        if any(phrase in f"{result.summary}{result.plan_reason}" for phrase in FORBIDDEN_DECISION_PHRASES)
    ]
    add("decision_boundary", not boundary_violations, f"越界措辞：{boundary_violations}" if boundary_violations else "保持申请前导办边界")
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
    return {
        "safe": not failed,
        "blocked": bool(failed),
        "validated_at_query_date": profile.query_date.isoformat(),
        "checks": checks,
        "failed_check_ids": [item["id"] for item in failed],
        "boundary": "安全验证器只阻断或提示，不改变规则引擎结论。",
    }
