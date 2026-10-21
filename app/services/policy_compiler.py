from __future__ import annotations

import hashlib
import json
import re
from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import uuid4

from app.config import BASE_DIR, settings
from app.domain.models import (
    CompiledRuleCondition,
    PolicyCompileRequest,
    PolicyCompileResponse,
    PolicyImpactResponse,
    PolicyRuleCandidate,
    PolicyValidationIssue,
)
from app.services.ai_runtime import JsonModelResult, ModelRuntimeError, chat_json
from app.services.rule_registry import registered_rules

BENEFITS = {
    "B001": ("低收入人口认定与监测", ("低收入人口", "低收入监测", "社会救助")),
    "B002": ("最低生活保障", ("最低生活保障", "低保")),
    "B003": ("最低生活保障边缘家庭认定", ("低保边缘", "最低生活保障边缘")),
    "B004": ("刚性支出困难家庭认定", ("刚性支出", "支出型困难")),
    "B005": ("临时救助", ("临时救助", "急难型")),
    "B006": ("特困人员救助供养", ("特困人员", "特困供养", "救助供养")),
}

ALLOWED_PARAMETER_NAMES = {
    "income_standard_monthly_per_capita",
    "edge_standard_monthly_per_capita",
    "income_multiplier",
    "urgent_event_days",
    "rigid_expense_income_ratio",
}
ALLOWED_FIELDS = {
    "per_capita_monthly_income",
    "per_capita_annual_income",
    "rigid_expenses_12m",
    "is_local_hukou",
    "assets_eligible",
    "member_scope_confirmed",
    "urgent_event",
    "urgent_event_date",
    "basic_life_interrupted",
    "residence_proof",
    "special_person_category_confirmed",
    "no_labor_capacity",
    "no_livelihood_source",
    "has_capable_legal_supporter",
}
ALLOWED_OPERATORS = {"lt", "lte", "gte", "eq", "within_days", "ratio_gte"}

PARAMETER_ANCHORS: dict[str, re.Pattern[str]] = {
    "income_standard_monthly_per_capita": re.compile(r"最低生活保障|低保标准"),
    "edge_standard_monthly_per_capita": re.compile(r"低保边缘|最低生活保障边缘"),
    "income_multiplier": re.compile(r"倍"),
    "urgent_event_days": re.compile(r"申请日前|日|月"),
    "rigid_expense_income_ratio": re.compile(r"刚性支出|必需支出|家庭年收入"),
}

POLICY_EXTRACTION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["benefit_id", "effective_from", "effective_to", "parameters", "conditions"],
    "properties": {
        "benefit_id": {"type": ["string", "null"], "enum": [*BENEFITS, None]},
        "effective_from": {"type": ["string", "null"]},
        "effective_to": {"type": ["string", "null"]},
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                name: {"type": ["string", "number", "integer", "boolean", "null"]}
                for name in sorted(ALLOWED_PARAMETER_NAMES)
            },
        },
        "conditions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["field", "operator", "value", "source_quote"],
                "properties": {
                    "field": {"type": "string", "enum": sorted(ALLOWED_FIELDS)},
                    "operator": {"type": "string", "enum": sorted(ALLOWED_OPERATORS)},
                    "value": {"type": ["string", "number", "integer", "boolean"]},
                    "unit": {"type": ["string", "null"]},
                    "source_quote": {"type": "string"},
                },
            },
        },
    },
}


def _sentences(text: str) -> list[str]:
    compact = re.sub(r"[\t\r ]+", " ", text).strip()
    return [part.strip() for part in re.split(r"(?<=[。；;！!？?\n])", compact) if part.strip()]


def _quote_for(text: str, *needles: str) -> str:
    for sentence in _sentences(text):
        if all(needle in sentence for needle in needles if needle):
            return sentence[:500]
    return text[:500]


def _parse_chinese_date(year: str, month: str, day: str) -> date | None:
    try:
        return date(int(year), int(month), int(day))
    except ValueError:
        return None


def _extract_dates(text: str) -> tuple[date | None, date | None]:
    start = None
    end = None
    start_patterns = (
        r"自\s*(\d{4})年(\d{1,2})月(\d{1,2})日(?:起)?(?:施行|实施|执行|试行|生效)",
        r"(\d{4})年(\d{1,2})月(\d{1,2})日(?:起)?(?:施行|实施|执行|试行|生效)",
    )
    for pattern in start_patterns:
        match = re.search(pattern, text)
        if match:
            start = _parse_chinese_date(*match.groups())
            break
    end_match = re.search(
        r"(?:有效期至|执行至|施行至|截止(?:至)?)\s*(\d{4})年(\d{1,2})月(\d{1,2})日",
        text,
    )
    if end_match:
        end = _parse_chinese_date(*end_match.groups())
    if start and not end:
        duration = re.search(r"有效期(?:为)?\s*([1-9]\d*)\s*年", text)
        if duration:
            years = int(duration.group(1))
            target_year = start.year + years
            target_day = min(start.day, monthrange(target_year, start.month)[1])
            end = date(target_year, start.month, target_day) - timedelta(days=1)
    return start, end


def _detect_benefit(text: str, hint: str | None, title: str = "") -> str:
    if hint:
        return hint
    if "一件事" in title and any(marker in text for marker in ("哪些救助", "低收入人口")):
        return "B001"
    if "申请家庭生活状况综合评估指标" in title:
        return "B002"
    # Clause-local exact matter names outrank a mixed-document title.  This is
    # essential for documents whose title contains both edge-family and
    # expenditure-difficulty matters.
    if any(marker in text for marker in ("支出型困难", "刚性支出")):
        return "B004"
    if any(marker in text for marker in ("低保边缘", "最低生活保障边缘")):
        return "B003"
    if any(marker in text for marker in ("临时救助", "急难型")):
        return "B005"
    if any(marker in text for marker in ("特困人员", "特困供养", "救助供养")):
        return "B006"
    scores: dict[str, int] = {}
    for benefit_id, (_, keywords) in BENEFITS.items():
        text_score = sum(text.count(keyword) * len(keyword) for keyword in keywords)
        title_score = sum(title.count(keyword) * len(keyword) * 3 for keyword in keywords)
        scores[benefit_id] = text_score + title_score
    # “社会救助”是上位领域词，只能在没有明确具体事项时用于B001；否则它会
    # 把《社会救助法》中低保边缘、刚性支出、临时救助条款全部吞成B001。
    if any(scores[item] > 0 for item in ("B002", "B003", "B004", "B005", "B006")):
        generic = text.count("社会救助") * len("社会救助")
        generic += title.count("社会救助") * len("社会救助") * 3
        scores["B001"] = max(0, scores["B001"] - generic)
    return max(scores, key=lambda benefit_id: scores[benefit_id]) if any(scores.values()) else "unknown"


def _money_value(raw: str) -> str | None:
    try:
        value = Decimal(raw).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None
    return format(value, "f")


def _extract_parameters(text: str, benefit_id: str) -> dict[str, str | int | float | bool]:
    parameters: dict[str, str | int | float | bool] = {}
    dibao = re.search(
        r"(?:最低生活保障|低保)(?:标准)?(?:调整)?(?:为|至|达到)?\s*(\d+(?:\.\d+)?)\s*元(?:/人/月|／人/月|每人每月|每月每人)?",
        text,
    ) or re.search(
        r"(?:最低生活保障|低保)(?:标准)?(?:为|至|达到)?\s*(?:每人每月|每月每人)\s*(\d+(?:\.\d+)?)\s*元",
        text,
    )
    edge = re.search(
        r"(?:低保边缘|最低生活保障边缘).*?(\d+(?:\.\d+)?)\s*元(?:/人/月|／人/月|每人每月|每月每人)?",
        text,
    )
    multiplier = re.search(r"(?:低保|最低生活保障)(?:标准)?的?\s*(\d+(?:\.\d+)?)\s*倍", text)
    urgent_days = re.search(r"申请日前\s*(\d+)\s*日", text)
    urgent_month = re.search(r"申请日前\s*(?:一个|1个?|一)\s*月", text)
    rigid_ratio = re.search(
        r"刚性支出.{0,80}?(?:达到|超过|不低于).{0,30}?(?:家庭年收入|其家庭年收入)(?:的)?\s*(\d+(?:\.\d+)?)\s*%",
        text,
    ) or re.search(
        r"刚性支出.{0,120}?(\d+(?:\.\d+)?)\s*%",
        text,
    )
    if dibao:
        value = _money_value(dibao.group(1))
        if value:
            parameters["income_standard_monthly_per_capita"] = value
    if edge:
        value = _money_value(edge.group(1))
        if value:
            parameters["edge_standard_monthly_per_capita"] = value
    if multiplier:
        parameters["income_multiplier"] = float(multiplier.group(1))
    if urgent_days:
        parameters["urgent_event_days"] = int(urgent_days.group(1))
    elif urgent_month and benefit_id == "B005":
        parameters["urgent_event_days"] = 31
    if rigid_ratio and benefit_id == "B004":
        parameters["rigid_expense_income_ratio"] = round(float(rigid_ratio.group(1)) / 100, 4)
    return parameters


def _extract_conditions(
    text: str,
    benefit_id: str,
    parameters: dict[str, str | int | float | bool],
) -> list[CompiledRuleCondition]:
    conditions: list[CompiledRuleCondition] = []
    threshold_key = (
        "edge_standard_monthly_per_capita"
        if benefit_id == "B003" and "edge_standard_monthly_per_capita" in parameters
        else "income_standard_monthly_per_capita"
    )
    if threshold_key in parameters:
        conditions.append(
            CompiledRuleCondition(
                field="per_capita_monthly_income",
                operator="lte",
                value=parameters[threshold_key],
                unit="元/人/月",
                source_quote=_quote_for(text, "元"),
            )
        )
    elif (
        ("人均收入低于" in text or "人均月收入" in text)
        and ("保障标准" in text or "人均可支配收入" in text)
        and ("低于" in text or "以下" in text)
    ):
        conditions.append(
            CompiledRuleCondition(
                field=(
                    "per_capita_annual_income" if "上年度" in text else "per_capita_monthly_income"
                ),
                operator="lt" if "低于" in text else "lte",
                value=(
                    "previous_year_local_disposable_income"
                    if "上年度" in text
                    else (
                        f"{parameters['income_multiplier']}*local_minimum_living_standard"
                        if "income_multiplier" in parameters
                        else "local_policy_threshold"
                    )
                ),
                source_quote=_quote_for(text, "收入"),
            )
        )
    if "财产" in text:
        conditions.append(
            CompiledRuleCondition(
                field="assets_eligible",
                operator="eq",
                value=True,
                source_quote=_quote_for(text, "财产"),
            )
        )
    if "当地户籍" in text or "具有本市户籍" in text or "具有广州户籍" in text:
        conditions.append(
            CompiledRuleCondition(
                field="is_local_hukou",
                operator="eq",
                value=True,
                source_quote=_quote_for(text, "户籍"),
            )
        )
    if benefit_id == "B004" and "低于上年度" in text and "人均可支配收入" in text:
        conditions.append(
            CompiledRuleCondition(
                field="per_capita_annual_income",
                operator="lt",
                value="previous_year_local_disposable_income",
                unit="元/人/年",
                source_quote=_quote_for(text, "低于上年度", "人均可支配收入"),
            )
        )
    if benefit_id == "B004" and "rigid_expense_income_ratio" in parameters:
        conditions.append(
            CompiledRuleCondition(
                field="rigid_expenses_12m",
                operator="ratio_gte",
                value=parameters["rigid_expense_income_ratio"],
                unit="占家庭年收入比例",
                source_quote=_quote_for(text, "刚性支出"),
            )
        )
    elif benefit_id == "B004" and "必需支出占家庭总收入比例" in text:
        conditions.append(
            CompiledRuleCondition(
                field="rigid_expenses_12m",
                operator="ratio_gte",
                value="local_policy_ratio",
                unit="占家庭年收入比例",
                source_quote=_quote_for(text, "必需支出占家庭总收入比例"),
            )
        )
    if "共同生活" in text:
        conditions.append(
            CompiledRuleCondition(
                field="member_scope_confirmed",
                operator="eq",
                value=True,
                source_quote=_quote_for(text, "共同生活"),
            )
        )
    if benefit_id == "B005" and "急难" in text:
        conditions.append(
            CompiledRuleCondition(
                field="urgent_event",
                operator="eq",
                value=True,
                source_quote=_quote_for(text, "急难"),
            )
        )
        if "urgent_event_days" in parameters:
            conditions.append(
                CompiledRuleCondition(
                    field="urgent_event_date",
                    operator="within_days",
                    value=parameters["urgent_event_days"],
                    unit="日",
                    source_quote=_quote_for(text, "申请日前"),
                )
            )
    if benefit_id == "B006":
        special_conditions = (
            ("无劳动能力", "no_labor_capacity", True),
            ("无生活来源", "no_livelihood_source", True),
        )
        for phrase, field, value in special_conditions:
            if phrase in text:
                conditions.append(
                    CompiledRuleCondition(
                        field=field,  # type: ignore[arg-type]
                        operator="eq",
                        value=value,
                        source_quote=_quote_for(text, phrase),
                    )
                )
        if any(marker in text for marker in ("老年人", "未成年人", "残疾人")):
            conditions.append(
                CompiledRuleCondition(
                    field="special_person_category_confirmed",
                    operator="eq",
                    value=True,
                    source_quote=_quote_for(text, "特困人员"),
                )
            )
        if "无法定赡养、抚养、扶养义务人" in text or "无履行义务能力" in text:
            conditions.append(
                CompiledRuleCondition(
                    field="has_capable_legal_supporter",
                    operator="eq",
                    value=False,
                    source_quote=_quote_for(text, "义务人"),
                )
            )
    if "基本生活" in text and ("困难" in text or "无法维持" in text):
        conditions.append(
            CompiledRuleCondition(
                field="basic_life_interrupted",
                operator="eq",
                value=True,
                source_quote=_quote_for(text, "基本生活"),
            )
        )
    if "居住证" in text or "连续居住" in text:
        conditions.append(
            CompiledRuleCondition(
                field="residence_proof",
                operator="eq",
                value=True,
                source_quote=_quote_for(text, "居住"),
            )
        )
    return conditions


def _ollama_extract(
    request: PolicyCompileRequest,
) -> tuple[dict[str, Any] | None, JsonModelResult | None]:
    if not settings.ollama_enabled:
        return None, None
    system_prompt = (
        "你是政策规则抽取器，不进行资格审批。只输出JSON。不得补写原文没有的信息。"
        "benefit_id只能是B001-B006或null；无法从当前原文确定事项时必须输出null，"
        "禁止默认B001。日期未明说时输出null，parameters未明说时输出空对象，"
        "conditions未明说时输出空数组，不得输出示例值、占位值或常用默认值。"
        "parameters只允许"
        f"{sorted(ALLOWED_PARAMETER_NAMES)}；conditions的field只允许{sorted(ALLOWED_FIELDS)}，"
        f"operator只允许{sorted(ALLOWED_OPERATORS)}。每条condition必须包含原文逐字引用source_quote。"
        "输出字段：benefit_id,effective_from,effective_to,parameters,conditions。"
    )
    try:
        trace = chat_json(
            system_prompt=system_prompt,
            user_prompt=f"标题：{request.title}\n政策原文：{request.source_text}",
            json_schema=POLICY_EXTRACTION_SCHEMA,
            purpose="policy2rule/v2",
        )
        return trace.payload, trace
    except ModelRuntimeError:
        return None, None


def _benefit_has_source_anchor(benefit_id: str, text: str, title: str) -> bool:
    keywords = BENEFITS[benefit_id][1]
    # “社会救助”是上位领域词，不能单独证明B001事项。
    if benefit_id == "B001":
        keywords = tuple(item for item in keywords if item != "社会救助")
    combined = f"{title}\n{text}"
    return any(keyword in combined for keyword in keywords)


def _parameter_has_source_anchor(name: str, value: Any, text: str) -> bool:
    anchor = PARAMETER_ANCHORS.get(name)
    if anchor is None or not anchor.search(text) or value is None or isinstance(value, bool):
        return False
    compact = re.sub(r"[\s,，]", "", text)
    raw = str(value).strip()
    candidates = {raw}
    try:
        numeric = Decimal(raw)
    except InvalidOperation:
        return re.sub(r"\s", "", raw) in compact
    normalized = format(numeric.normalize(), "f")
    candidates.add(normalized)
    if numeric == numeric.to_integral_value():
        candidates.add(str(int(numeric)))
    if name == "rigid_expense_income_ratio":
        candidates.add(f"{format((numeric * 100).normalize(), 'f')}%")
    return any(
        re.search(rf"(?<!\d){re.escape(candidate)}(?!\d)", compact)
        for candidate in candidates
        if candidate
    )


def _validated_llm_result(
    request: PolicyCompileRequest, llm: dict[str, Any] | None
) -> dict[str, Any]:
    """Validate model output without borrowing deterministic predictions.

    This is deliberately separate from fusion so the LLM-only evaluation track
    cannot inherit a benefit, date, parameter or condition from the rules engine.
    """

    result: dict[str, Any] = {
        "benefit_id": "unknown",
        "effective_from": None,
        "effective_to": None,
        "parameters": {},
        "conditions": [],
    }
    if not llm:
        return result
    benefit_id = llm.get("benefit_id")
    if benefit_id in BENEFITS and _benefit_has_source_anchor(
        benefit_id, request.source_text, request.title
    ):
        result["benefit_id"] = benefit_id
    for field in ("effective_from", "effective_to"):
        value = llm.get(field)
        if value:
            try:
                result[field] = date.fromisoformat(str(value))
            except ValueError:
                pass
    raw_parameters = llm.get("parameters")
    if isinstance(raw_parameters, dict):
        result["parameters"] = {
            key: value
            for key, value in raw_parameters.items()
            if key in ALLOWED_PARAMETER_NAMES
            and isinstance(value, (str, int, float, bool))
            and _parameter_has_source_anchor(key, value, request.source_text)
        }
    accepted: list[CompiledRuleCondition] = []
    raw_conditions = llm.get("conditions")
    for raw in raw_conditions if isinstance(raw_conditions, list) else []:
        if not isinstance(raw, dict):
            continue
        quote = str(raw.get("source_quote", "")).strip()
        if (
            raw.get("field") not in ALLOWED_FIELDS
            or raw.get("operator") not in ALLOWED_OPERATORS
            or len(quote) < 2
            or quote not in request.source_text
        ):
            continue
        try:
            accepted.append(CompiledRuleCondition(**raw))
        except ValueError:
            continue
    result["conditions"] = accepted
    return result


def _merge_llm(
    request: PolicyCompileRequest,
    deterministic: dict[str, Any],
    llm: dict[str, Any] | None,
) -> tuple[dict[str, Any], bool]:
    if not llm:
        return deterministic, False
    result = {
        **deterministic,
        "parameters": dict(deterministic["parameters"]),
        "conditions": list(deterministic["conditions"]),
    }
    validated = _validated_llm_result(request, llm)
    benefit_id = validated.get("benefit_id")
    if (
        benefit_id in BENEFITS
        and request.benefit_hint is None
        and deterministic.get("benefit_id") == "unknown"
    ):
        result["benefit_id"] = benefit_id
    for field in ("effective_from", "effective_to"):
        value = validated.get(field)
        if value and not result.get(field):
            result[field] = value
    llm_parameters = validated.get("parameters")
    if isinstance(llm_parameters, dict):
        for key, value in llm_parameters.items():
            if key in ALLOWED_PARAMETER_NAMES and isinstance(value, (str, int, float, bool)):
                result["parameters"].setdefault(key, value)
    accepted = validated["conditions"]
    known = {(item.field, item.operator, str(item.value)) for item in result["conditions"]}
    result["conditions"].extend(
        item for item in accepted if (item.field, item.operator, str(item.value)) not in known
    )
    return result, True


def _version_diff(candidate: PolicyRuleCandidate) -> dict[str, Any]:
    current = next(
        (rule for rule in registered_rules() if rule.benefit_id == candidate.benefit_id), None
    )
    if not current:
        return {"baseline_found": False, "changes": [], "temporal_overlap": False}
    changes = []
    old_parameters = current.parameters
    for key in sorted(set(old_parameters) | set(candidate.parameters)):
        before = old_parameters.get(key)
        after = candidate.parameters.get(key)
        if str(before) != str(after):
            changes.append({"field": f"parameters.{key}", "before": before, "after": after})
    for field in ("effective_from", "effective_to"):
        before = getattr(current, field)
        after = getattr(candidate, field)
        if before != after:
            changes.append(
                {
                    "field": field,
                    "before": before.isoformat() if before else None,
                    "after": after.isoformat() if after else None,
                }
            )
    candidate_end = candidate.effective_to or date.max
    current_end = current.effective_to or date.max
    overlap = bool(
        candidate.effective_from
        and candidate.effective_from <= current_end
        and (current.effective_from or date.min) <= candidate_end
    )
    return {
        "baseline_found": True,
        "baseline_version": current.version,
        "baseline_status": current.status,
        "changes": changes,
        "temporal_overlap": overlap,
    }


def compile_policy(request: PolicyCompileRequest) -> PolicyCompileResponse:
    strategy = request.extraction_strategy or (
        "controlled_fusion" if request.use_llm else "deterministic"
    )
    start, end = _extract_dates(request.source_text)
    benefit_id = _detect_benefit(request.source_text, request.benefit_hint, request.title)
    parameters = _extract_parameters(request.source_text, benefit_id)
    deterministic = {
        "benefit_id": benefit_id,
        "effective_from": request.effective_from or start,
        "effective_to": request.effective_to or end,
        "parameters": parameters,
        "conditions": _extract_conditions(request.source_text, benefit_id, parameters),
    }
    llm_payload: dict[str, Any] | None = None
    llm_trace: JsonModelResult | None = None
    if strategy in {"llm_only", "controlled_fusion"}:
        llm_payload, llm_trace = _ollama_extract(request)
    if strategy == "llm_only":
        merged = _validated_llm_result(request, llm_payload)
        used_llm = llm_trace is not None
    elif strategy == "controlled_fusion":
        merged, used_llm = _merge_llm(request, deterministic, llm_payload)
    else:
        merged, used_llm = deterministic, False
    benefit_id = merged["benefit_id"]
    citations = list(dict.fromkeys(item.source_quote for item in merged["conditions"]))[:8]
    exceptions = [
        sentence[:500]
        for sentence in _sentences(request.source_text)
        if any(marker in sentence for marker in ("不计入", "不得以", "除", "但", "可不"))
    ][:8]
    completeness_parts = [
        benefit_id != "unknown",
        bool(merged["effective_from"]),
        bool(request.region),
        bool(merged["parameters"]),
        bool(merged["conditions"]),
        bool(citations),
    ]
    candidate = PolicyRuleCandidate(
        candidate_id=f"PCR-{uuid4().hex[:10].upper()}",
        benefit_id=benefit_id,
        benefit_name=(BENEFITS[benefit_id][0] if benefit_id in BENEFITS else "未识别事项"),
        region=request.region,
        source_id=request.source_id,
        title=request.title,
        effective_from=merged["effective_from"],
        effective_to=merged["effective_to"],
        parameters=merged["parameters"],
        conditions=merged["conditions"],
        exceptions=exceptions,
        citations=citations,
        provider=(
            f"ollama/{settings.ollama_model}+allowlist-validation/llm-only"
            if strategy == "llm_only" and used_llm
            else f"local-policy-compiler/1.0+ollama/{settings.ollama_model}+allowlist-fusion"
            if strategy == "controlled_fusion" and used_llm
            else "local-policy-compiler/1.0"
        ),
        extraction_completeness=round(sum(completeness_parts) / len(completeness_parts), 3),
        source_sha256=hashlib.sha256(request.source_text.encode("utf-8")).hexdigest(),
        model_id=llm_trace.model_id if used_llm and llm_trace else None,
        prompt_sha256=llm_trace.prompt_sha256 if used_llm and llm_trace else None,
        model_latency_ms=llm_trace.latency_ms if used_llm and llm_trace else None,
    )
    diff = _version_diff(candidate)
    issues: list[PolicyValidationIssue] = []
    if candidate.benefit_id == "unknown":
        issues.append(
            PolicyValidationIssue(
                severity="error",
                code="unknown_benefit",
                message="无法从原文识别受支持事项，禁止默认映射或发布。",
                field="benefit_id",
            )
        )
    if candidate.effective_from is None:
        issues.append(
            PolicyValidationIssue(
                severity="error",
                code="missing_effective_from",
                message="未从原文确定生效日期，必须人工填写并核对。",
                field="effective_from",
            )
        )
    if candidate.effective_from and candidate.effective_to:
        if candidate.effective_to < candidate.effective_from:
            issues.append(
                PolicyValidationIssue(
                    severity="error",
                    code="invalid_effective_range",
                    message="失效日期早于生效日期。",
                    field="effective_to",
                )
            )
    if not candidate.conditions:
        issues.append(
            PolicyValidationIssue(
                severity="error",
                code="no_executable_condition",
                message="未抽取到可执行条件，禁止发布。",
                field="conditions",
            )
        )
    if not candidate.parameters:
        issues.append(
            PolicyValidationIssue(
                severity="warning",
                code="no_parameter",
                message="未发现结构化阈值；如果是程序性条款，应人工确认是否仅进入证据库。",
                field="parameters",
            )
        )
    if diff.get("temporal_overlap"):
        issues.append(
            PolicyValidationIssue(
                severity="warning",
                code="temporal_overlap",
                message="候选规则与现行版本时间范围重叠，发布前必须明确替代或并行关系。",
                field="effective_from",
            )
        )
    if not used_llm and strategy in {"llm_only", "controlled_fusion"}:
        issues.append(
            PolicyValidationIssue(
                severity="info",
                code="llm_not_used",
                message="本地大模型未启用或不可用，本次使用确定性抽取器；结果仍需双人复核。",
            )
        )
    issues.append(
        PolicyValidationIssue(
            severity="info",
            code="dual_review_required",
            message="任何候选规则必须由两名复核人独立确认后才能进入发布流程。",
        )
    )
    blockers = [item.message for item in issues if item.severity == "error"]
    blockers.append("尚未完成双人独立复核和发布签名。")
    return PolicyCompileResponse(
        candidate=candidate,
        validation=issues,
        publishable=False,
        publish_blockers=blockers,
        version_diff=diff,
    )


def _case_threshold(profile: dict[str, Any], threshold: Decimal) -> bool | None:
    income = profile.get("monthly_income_total")
    size = profile.get("household_size")
    if income is None or not size:
        return None
    deductible = Decimal(str(profile.get("deductible_monthly_total") or "0"))
    per_capita = max(Decimal(str(income)) - deductible, Decimal("0")) / Decimal(str(size))
    return per_capita <= threshold


def analyze_policy_impact(candidate: PolicyRuleCandidate) -> PolicyImpactResponse:
    baseline = next(
        (rule for rule in registered_rules() if rule.benefit_id == candidate.benefit_id), None
    )
    case_path = BASE_DIR / "data" / "processed" / "synthetic_conformance_cases.jsonl"
    cases = [json.loads(line) for line in case_path.read_text(encoding="utf-8").splitlines() if line]
    notes = ["影响分析使用合成回归案例，不代表真实群众数量或政策实际覆盖人数。"]
    changes = {"newly_included": 0, "newly_excluded": 0}
    samples: list[str] = []
    comparable = 0
    if baseline is None:
        notes.append("规则登记表中没有同事项基线版本，无法执行参数差异模拟。")
        return PolicyImpactResponse(
            benefit_id=candidate.benefit_id,
            total_cases=len(cases),
            comparable_cases=0,
            changed_cases=0,
            changes_by_direction=changes,
            sample_case_ids=[],
            notes=notes,
        )
    key = (
        "income_standard_monthly_per_capita"
        if candidate.benefit_id == "B002"
        else "edge_standard_monthly_per_capita"
        if candidate.benefit_id == "B003"
        else None
    )
    old_raw = baseline.parameters.get("income_standard_monthly_per_capita") if key else None
    new_raw = candidate.parameters.get(key) if key else None
    if old_raw is None or new_raw is None:
        notes.append("当前只对低保/低保边缘的人均月收入阈值执行逐案例影响模拟。")
    else:
        old_threshold = Decimal(str(old_raw))
        new_threshold = Decimal(str(new_raw))
        notes.append(f"比较阈值：{old_threshold} → {new_threshold} 元/人/月。")
        for item in cases:
            old_result = _case_threshold(item["profile"], old_threshold)
            new_result = _case_threshold(item["profile"], new_threshold)
            if old_result is None or new_result is None:
                continue
            comparable += 1
            if old_result == new_result:
                continue
            direction = "newly_included" if new_result else "newly_excluded"
            changes[direction] += 1
            if len(samples) < 12:
                samples.append(item["case_id"])
    return PolicyImpactResponse(
        benefit_id=candidate.benefit_id,
        baseline_version=baseline.version,
        total_cases=len(cases),
        comparable_cases=comparable,
        changed_cases=sum(changes.values()),
        changes_by_direction=changes,
        sample_case_ids=samples,
        notes=notes,
    )
