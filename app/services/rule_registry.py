from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from functools import lru_cache
from typing import Any

from app.config import BASE_DIR, settings


@dataclass(frozen=True)
class RegisteredRule:
    benefit_id: str
    name: str
    version: str
    document_no: str | None
    effective_from: date
    effective_to: date | None
    status: str
    source_ids: tuple[str, ...]
    parameters: dict[str, Any]
    manual_review_required: bool

    def is_effective(self, query_date: date) -> bool:
        return self.effective_from <= query_date and (
            self.effective_to is None or query_date <= self.effective_to
        )


@lru_cache(maxsize=1)
def load_rule_registry() -> dict[str, Any]:
    with settings.rule_registry_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    required = {"registry_version", "region", "reviewed_at", "rules", "release_controls"}
    missing = required - payload.keys()
    if missing:
        raise ValueError(f"规则登记表缺少字段：{', '.join(sorted(missing))}")
    return payload


def registered_rules() -> list[RegisteredRule]:
    result = []
    for item in load_rule_registry()["rules"]:
        result.append(
            RegisteredRule(
                benefit_id=item["benefit_id"],
                name=item["name"],
                version=item["version"],
                document_no=item.get("document_no"),
                effective_from=date.fromisoformat(item["effective_from"]),
                effective_to=(
                    date.fromisoformat(item["effective_to"]) if item.get("effective_to") else None
                ),
                status=item["status"],
                source_ids=tuple(item["source_ids"]),
                parameters=item.get("parameters", {}),
                manual_review_required=bool(item.get("manual_review_required", False)),
            )
        )
    return result


def rules_for_benefit(benefit_id: str) -> list[RegisteredRule]:
    return [rule for rule in registered_rules() if rule.benefit_id == benefit_id]


def get_rule(benefit_id: str) -> RegisteredRule:
    """返回该事项最新的登记规则，供现行参数和管理页使用。"""

    rules = rules_for_benefit(benefit_id)
    if rules:
        return max(rules, key=lambda rule: rule.effective_from)
    raise KeyError(f"未登记规则：{benefit_id}")


def get_rule_for_date(benefit_id: str, query_date: date) -> RegisteredRule | None:
    """返回查询日唯一生效的规则；重叠版本视为注册表错误。"""

    matches = [rule for rule in rules_for_benefit(benefit_id) if rule.is_effective(query_date)]
    if len(matches) > 1:
        versions = ", ".join(sorted(rule.version for rule in matches))
        raise ValueError(f"规则{benefit_id}在{query_date.isoformat()}存在重叠版本：{versions}")
    return matches[0] if matches else None


def decimal_parameter(benefit_id: str, name: str) -> Decimal:
    value = get_rule(benefit_id).parameters.get(name)
    if value is None:
        raise KeyError(f"规则{benefit_id}缺少参数{name}")
    return Decimal(str(value))


def registry_governance() -> dict[str, Any]:
    payload = load_rule_registry()
    controls = payload["release_controls"]
    enabled = sum(1 for value in controls.values() if value)
    raw_files = sorted((BASE_DIR / "data" / "raw_official").glob("*"))
    source_fingerprints = []
    for path in raw_files:
        if not path.is_file():
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
        source_fingerprints.append({"file": path.name, "sha256_prefix": digest})
    registry_digest = hashlib.sha256(settings.rule_registry_path.read_bytes()).hexdigest()[:12]
    return {
        "registry_version": payload["registry_version"],
        "reviewed_at": payload["reviewed_at"],
        "release_status": payload["release_status"],
        "rules": [
            {
                "benefit_id": rule.benefit_id,
                "name": rule.name,
                "version": rule.version,
                "document_no": rule.document_no,
                "status": rule.status,
                "effective_from": rule.effective_from.isoformat(),
                "effective_to": rule.effective_to.isoformat() if rule.effective_to else None,
                "manual_review_required": rule.manual_review_required,
            }
            for rule in registered_rules()
        ],
        "controls": controls,
        "control_summary": {"enabled": enabled, "total": len(controls)},
        "registry_sha256_prefix": registry_digest,
        "source_fingerprints": source_fingerprints,
    }
