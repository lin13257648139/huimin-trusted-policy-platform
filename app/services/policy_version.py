from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.services.rule_registry import get_rule, get_rule_for_date


@dataclass(frozen=True)
class PolicySnapshot:
    snapshot_id: str
    dibao_version: str
    local_rule_available: bool
    query_date: date
    warning: str | None = None


_DIBAO_RULE = get_rule("B002")
_TEMPORARY_RULE = get_rule("B005")
CURRENT_DIBAO_START = _DIBAO_RULE.effective_from
CURRENT_DIBAO_END = _DIBAO_RULE.effective_to or date.max
TEMPORARY_RESCUE_END = _TEMPORARY_RULE.effective_to or date.max


def select_policy_snapshot(query_date: date) -> PolicySnapshot:
    """选择查询日期对应的规则快照。

    按版本化规则注册表选择查询日当时生效的文件。无已核验快照时才安全
    降级为人工核验，不会用现行规则倒推历史结果。
    """

    dated_rule = get_rule_for_date("B002", query_date)
    if dated_rule is not None:
        return PolicySnapshot(
            snapshot_id=f"gz-{query_date.isoformat()}-{dated_rule.version}",
            dibao_version=dated_rule.document_no or dated_rule.version,
            local_rule_available=not dated_rule.manual_review_required,
            query_date=query_date,
        )
    if query_date < CURRENT_DIBAO_START:
        return PolicySnapshot(
            snapshot_id=f"gz-{query_date.isoformat()}-legacy-review",
            dibao_version="历史规则（未在当前已核验库发布）",
            local_rule_available=False,
            query_date=query_date,
            warning="查询日期未命中已核验的低保规则快照，系统不会套用现行规则，请人工核验历史文件。",
        )
    return PolicySnapshot(
        snapshot_id=f"gz-{query_date.isoformat()}-future-review",
        dibao_version="现行试行文件已超出标注有效期",
        local_rule_available=False,
        query_date=query_date,
        warning="查询日期超出当前低保试行文件有效期，请先核验续期或替代文件。",
    )


def temporary_policy_warning(query_date: date) -> str | None:
    if query_date > TEMPORARY_RESCUE_END:
        return "临时救助实施细则已超出当前记录的有效期，不能自动判断。"
    if (TEMPORARY_RESCUE_END - query_date).days <= 30:
        return "临时救助实施细则将在30天内到期，请在办理前复核最新文件。"
    return None

