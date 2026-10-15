from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from typing import Any, Literal

from app.config import BASE_DIR
from app.domain.models import (
    AppliedBenefitRelation,
    BenefitResult,
    EligibilityStatus,
)
from app.services.catalog import evidence_for

REGISTRY_PATH = BASE_DIR / "data" / "processed" / "benefit_relation_registry.json"


@lru_cache(maxsize=1)
def load_benefit_relation_registry() -> dict[str, Any]:
    payload = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    required = {"registry_version", "title", "region", "reviewed_at", "relationships"}
    missing = required - payload.keys()
    if missing:
        raise ValueError(f"事项关系登记表缺少字段：{sorted(missing)}")
    relation_ids = [item["relation_id"] for item in payload["relationships"]]
    if len(relation_ids) != len(set(relation_ids)):
        raise ValueError("事项关系登记表存在重复relation_id")
    return payload


def benefit_relation_governance() -> dict[str, Any]:
    registry = load_benefit_relation_registry()
    return {
        "registry_version": registry["registry_version"],
        "title": registry["title"],
        "region": registry["region"],
        "reviewed_at": registry["reviewed_at"],
        "relationship_count": len(registry["relationships"]),
        "registry_sha256_prefix": hashlib.sha256(REGISTRY_PATH.read_bytes()).hexdigest()[:12],
        "routing_boundary": "只编排申请前核验顺序；不会把预筛线索改写为行政认定结果",
    }


def _rule(relation_id: str) -> dict[str, Any]:
    registry = load_benefit_relation_registry()
    return next(
        item for item in registry["relationships"] if item["relation_id"] == relation_id
    )


def _append_relation(
    result: BenefitResult,
    *,
    rule: dict[str, Any],
    related_benefit_id: str,
    direction: Literal["outgoing", "incoming", "peer"],
    reason: str,
) -> None:
    result.plan_relations.append(
        AppliedBenefitRelation(
            relation_id=rule["relation_id"],
            relation_type=rule["relation_type"],
            related_benefit_id=related_benefit_id,
            direction=direction,
            reason=reason,
            evidence_ids=rule["evidence_ids"],
        )
    )
    existing = {item.evidence_id for item in result.evidence}
    result.evidence.extend(
        item for item in evidence_for(*rule["evidence_ids"]) if item.evidence_id not in existing
    )


def _set_base_roles(results: list[BenefitResult]) -> None:
    for item in results:
        item.plan_relations = []
        if item.status == EligibilityStatus.UNLIKELY:
            item.plan_role = "not_recommended"
            item.plan_reason = "当前信息存在不满足项，先核对条件，不列入本次主路径。"
        elif item.status == EligibilityStatus.MANUAL_REVIEW:
            item.plan_role = "manual"
            item.plan_reason = "规则边界或年度参数需要人工核验，系统不自动归类。"
        elif item.status == EligibilityStatus.INCOMPLETE:
            item.plan_role = "alternative"
            item.plan_reason = "关键资料尚未齐全，补充最小缺口后再决定是否进入主路径。"
        elif item.benefit_id == "B005":
            item.plan_role = "primary"
            item.plan_reason = "存在近期急难且基本生活受影响，按快速响应优先级列为首要路径。"
        elif item.benefit_id == "B002":
            item.plan_role = "primary"
            item.plan_reason = "低保属于基本生活救助，应先完成该项核验。"
        elif item.benefit_id == "B001":
            item.plan_role = "linked"
            item.plan_reason = "作为低收入人口监测和转介入口，与具体认定事项联动办理。"
        else:
            item.plan_role = "primary"
            item.plan_reason = "当前线索支持列入优先咨询路径。"


def apply_combination_plan(results: list[BenefitResult]) -> list[BenefitResult]:
    """按政策关系编排分层路径，不改变任何单事项资格状态。"""

    _set_base_roles(results)
    by_id = {item.benefit_id: item for item in results}
    dibao = by_id["B002"]
    edge = by_id["B003"]
    rigid = by_id["B004"]

    # 预筛阶段不能声称已经完成互斥认定；只要低保尚未明确排除，就先核验B002，
    # B003/B004保留为“未获低保确认时”的转介，不与B002并列重复申请。
    if dibao.status != EligibilityStatus.UNLIKELY:
        if dibao.status == EligibilityStatus.MANUAL_REVIEW:
            dibao.plan_reason = "低保处于政策或金额边界，须先人工核验，再决定是否转介其他分层对象。"
        elif dibao.status == EligibilityStatus.INCOMPLETE:
            dibao.plan_reason = "低保关键条件尚未齐全，应先补齐并核验，再决定是否转介其他分层对象。"
        for candidate, relation_id in (
            (edge, "REL-B002-B003"),
            (rigid, "REL-B002-B004"),
        ):
            if candidate.status in {EligibilityStatus.LIKELY, EligibilityStatus.INCOMPLETE}:
                candidate.plan_role = "alternative"
                candidate.plan_reason = (
                    "低保尚未明确排除；本事项保留为低保未获正式确认时的分层转介，"
                    "不要与低保重复申请。"
                )
                rule = _rule(relation_id)
                reason = "先核验最低生活保障；未获正式确认时再转入本事项。"
                _append_relation(
                    dibao,
                    rule=rule,
                    related_benefit_id=candidate.benefit_id,
                    direction="outgoing",
                    reason=reason,
                )
                _append_relation(
                    candidate,
                    rule=rule,
                    related_benefit_id="B002",
                    direction="incoming",
                    reason=reason,
                )

    # 低保已明确不符合时，B003和B004按各自条件分别认定；两者同时有线索时
    # 保持并行主路径，由同一窗口复用经济状况材料，而不是二选一。
    if (
        dibao.status == EligibilityStatus.UNLIKELY
        and edge.status == EligibilityStatus.LIKELY
        and rigid.status == EligibilityStatus.LIKELY
    ):
        rule = _rule("REL-B003-B004")
        edge.plan_role = rigid.plan_role = "primary"
        edge.plan_reason = "低保已明确不符合；低保边缘与刚性支出困难可分别认定，建议并行核验。"
        rigid.plan_reason = "低保已明确不符合；刚性支出困难与低保边缘可分别认定，建议并行核验。"
        _append_relation(
            edge,
            rule=rule,
            related_benefit_id="B004",
            direction="peer",
            reason="两类对象分别认定，可并行核验并复用家庭经济状况材料。",
        )
        _append_relation(
            rigid,
            rule=rule,
            related_benefit_id="B003",
            direction="peer",
            reason="两类对象分别认定，可并行核验并复用家庭经济状况材料。",
        )

    plausible = [
        item
        for item in (dibao, edge, rigid)
        if item.status != EligibilityStatus.UNLIKELY
    ]
    low_income = by_id["B001"]
    if low_income.status != EligibilityStatus.UNLIKELY and plausible:
        rule = _rule("REL-B001-CLASSIFIED")
        for candidate in plausible:
            _append_relation(
                low_income,
                rule=rule,
                related_benefit_id=candidate.benefit_id,
                direction="outgoing",
                reason="低收入人口监测作为认定后的联动入口，不替代具体事项审核。",
            )

    role_order = {
        "primary": 0,
        "manual": 1,
        "alternative": 2,
        "linked": 3,
        "not_recommended": 4,
    }
    return sorted(results, key=lambda item: (role_order[item.plan_role], -item.score))
