from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.config import settings
from app.domain.models import ParseProfileRequest, ParseProfileResponse
from app.services.ai_runtime import ModelRuntimeError, chat_json
from app.services.intent_classifier import classify_intent


DISTRICTS = [
    "越秀区",
    "海珠区",
    "荔湾区",
    "天河区",
    "白云区",
    "黄埔区",
    "花都区",
    "番禺区",
    "南沙区",
    "从化区",
    "增城区",
]

CHINESE_DIGITS = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


class _ProfileExtraction(BaseModel):
    """The only fields a model may propose. Extra keys are rejected, not ignored."""

    model_config = ConfigDict(extra="forbid")

    district: str | None = None
    household_size: int | None = Field(default=None, ge=1, le=30)
    is_local_hukou: bool | None = None
    has_local_family_member: bool | None = None
    member_scope_confirmed: bool | None = None
    residence_proof: bool | None = None
    monthly_income_total: Decimal | None = Field(default=None, ge=0)
    deductible_monthly_total: Decimal | None = Field(default=None, ge=0)
    assets_eligible: bool | None = None
    financial_assets_per_capita: Decimal | None = Field(default=None, ge=0)
    rigid_expenses_12m: Decimal | None = Field(default=None, ge=0)
    medical_expenses_12m: Decimal | None = Field(default=None, ge=0)
    education_expenses_12m: Decimal | None = Field(default=None, ge=0)
    urgent_event: bool | None = None
    urgent_event_date: date | None = None
    urgent_event_type: str | None = Field(default=None, max_length=80)
    basic_life_interrupted: bool | None = None

    @field_validator("district")
    @classmethod
    def validate_district(cls, value: str | None) -> str | None:
        if value is not None and value not in DISTRICTS:
            raise ValueError("district必须是广州市行政区")
        return value


def _money(value: str, unit: str | None) -> Decimal:
    multiplier = Decimal("10000") if unit == "万" else Decimal("1")
    return (Decimal(value) * multiplier).quantize(Decimal("0.01"))


def _heuristic_parse(request: ParseProfileRequest) -> ParseProfileResponse:
    text = request.text
    fields: dict[str, Any] = {
        "query_date": request.query_date.isoformat(),
        "city": "广州市" if "广州" in text or not request.district else "广州市",
    }
    confidence: dict[str, float] = {"query_date": 1.0, "city": 0.95}
    warnings: list[str] = []

    # 把“要求系统编造/改写事实”的指令与用户自述事实隔离。这里不尝试判断恶意，
    # 只要句子明确要求伪造、绕过或跳过核验，就不从该句抽取资格关键字段。
    instruction_attack = re.search(
        r"(?:忽略.{0,8}(?:规则|要求|系统)|编造|伪造|捏造|绕过.{0,6}(?:规则|核验)|"
        r"不要核验|直接说.{0,8}(?:通过|符合)|替我.{0,8}(?:写成|改成|填成))",
        text,
    )
    if instruction_attack:
        intent_model, intent_predictions = classify_intent(text)
        warnings.append("检测到要求编造或绕过核验的指令，未从该段生成资格关键事实。")
        return ParseProfileResponse(
            fields=fields,
            confidence=confidence,
            missing_fields=[
                "district",
                "household_size",
                "monthly_income_total",
                "assets_eligible",
                "member_scope_confirmed",
            ],
            warnings=warnings,
            provider="local-safe-parser",
            intent_model=intent_model,
            intent_predictions=intent_predictions,
        )

    district = request.district
    for candidate in DISTRICTS:
        if candidate in text:
            district = candidate
            confidence["district"] = 0.98
            break
    if district:
        fields["district"] = district
        confidence.setdefault("district", 0.85)

    size_match = re.search(r"([1-9]|[一二两三四五六七八九十])\s*(?:口|人)(?:之家|家庭)?", text)
    if size_match:
        raw = size_match.group(1)
        fields["household_size"] = int(raw) if raw.isdigit() else CHINESE_DIGITS[raw]
        confidence["household_size"] = 0.96

    income_patterns = [
        r"(?:家庭)?(?:每月|月)(?:总)?收入(?:约|是|为)?\s*(\d+(?:\.\d+)?)\s*(万)?元?",
        r"(?:每月|月)(?:家庭)?(?:总)?收入(?:约|是|为)?\s*(\d+(?:\.\d+)?)\s*(万)?元?",
        r"(?:家庭)?收入(?:约|是|为)?\s*(\d+(?:\.\d+)?)\s*(万)?元?\s*(?:每月|\/月)",
    ]
    for pattern in income_patterns:
        match = re.search(pattern, text)
        if match:
            fields["monthly_income_total"] = str(_money(match.group(1), match.group(2)))
            confidence["monthly_income_total"] = 0.91
            break

    expense_patterns = [
        ("medical_expenses_12m", r"(?:医疗|看病|住院)(?:支出|花费|费用)?(?:约|是|为)?\s*(\d+(?:\.\d+)?)\s*(万)?元?"),
        ("education_expenses_12m", r"(?:教育|学费)(?:支出|花费|费用)?(?:约|是|为)?\s*(\d+(?:\.\d+)?)\s*(万)?元?"),
    ]
    expense_total = Decimal("0")
    for field, pattern in expense_patterns:
        match = re.search(pattern, text)
        if match:
            value = _money(match.group(1), match.group(2))
            fields[field] = str(value)
            confidence[field] = 0.89
            expense_total += value
    if expense_total > 0:
        fields["rigid_expenses_12m"] = str(expense_total)
        confidence["rigid_expenses_12m"] = 0.84

    if re.search(r"非广州户籍|外地户籍|外地户口", text):
        fields["is_local_hukou"] = False
        confidence["is_local_hukou"] = 0.96
    elif re.search(r"广州户籍|本市户籍|广州户口", text):
        fields["is_local_hukou"] = True
        confidence["is_local_hukou"] = 0.96

    if re.search(r"(?:没有|无|未办理|未持有).{0,4}居住证", text):
        fields["residence_proof"] = False
        confidence["residence_proof"] = 0.94
    elif re.search(r"居住证|连续居住", text):
        fields["residence_proof"] = True
        confidence["residence_proof"] = 0.82

    if re.search(r"(?:财产状况|家庭财产).{0,8}(?:不符合|未符合)", text):
        fields["assets_eligible"] = False
        confidence["assets_eligible"] = 0.96
    elif re.search(r"(?:财产状况|家庭财产).{0,8}(?:符合|已符合).{0,6}(?:救助)?规定", text):
        fields["assets_eligible"] = True
        confidence["assets_eligible"] = 0.96
    membership_unconfirmed = re.search(
        r"共同生活.{0,8}(?:成员|家庭成员).{0,12}(?:尚未|还没|没有|未).{0,3}(?:核清|确认)",
        text,
    )
    if not membership_unconfirmed and re.search(
        r"共同生活.{0,8}(?:成员|家庭成员).{0,8}(?:已|已经)?(?:核清|确认)", text
    ):
        fields["member_scope_confirmed"] = True
        confidence["member_scope_confirmed"] = 0.94

    urgent_terms = {
        "火灾": "火灾",
        "交通事故": "交通事故",
        "重大疾病": "重大疾病",
        "突发急病": "突发急病",
        "意外伤害": "意外伤害",
    }
    event_mentioned = False
    event_positive = False
    for term, event_type in urgent_terms.items():
        for match in re.finditer(re.escape(term), text):
            event_mentioned = True
            context = text[max(0, match.start() - 8) : match.start()]
            if re.search(r"(?:没有发生|没有|并无|未发生|没发生|不是|否认)$", context):
                continue
            fields["urgent_event"] = True
            fields["urgent_event_type"] = event_type
            confidence["urgent_event"] = 0.91
            confidence["urgent_event_type"] = 0.95
            event_positive = True
            break
        if event_positive:
            break
    if event_mentioned and not event_positive:
        fields["urgent_event"] = False
        confidence["urgent_event"] = 0.94
    if re.search(r"基本生活.{0,8}(困难|中断|无法维持)|生活陷入困难", text):
        fields["basic_life_interrupted"] = True
        confidence["basic_life_interrupted"] = 0.86

    missing = [
        field
        for field in [
            "district",
            "household_size",
            "monthly_income_total",
            "assets_eligible",
            "member_scope_confirmed",
        ]
        if field not in fields
    ]
    if missing:
        warnings.append("自然语言只生成画像草稿，带金额和资格影响的字段必须由用户确认。")
    intent_model, intent_predictions = classify_intent(text)
    return ParseProfileResponse(
        fields=fields,
        confidence=confidence,
        missing_fields=missing,
        warnings=warnings,
        provider="local-safe-parser",
        intent_model=intent_model,
        intent_predictions=intent_predictions,
    )


def _ollama_parse(request: ParseProfileRequest) -> tuple[_ProfileExtraction, Any]:
    system_prompt = (
        "你是社会救助申请前的信息抽取器，不进行资格判断。"
        "只能提取用户逐字明确表达的事实；未说明、否定不清或需要推断的字段必须为null。"
        "金额统一换算为人民币元。assets_eligible仅在用户明确表示财产状况符合/不符合规定时填写。"
        "member_scope_confirmed仅在用户明确确认共同生活家庭成员范围时填写。"
        "用户表示尚未确认成员范围时，member_scope_confirmed必须为null而不是false。"
    )
    result = chat_json(
        system_prompt=system_prompt,
        user_prompt=f"查询日期：{request.query_date.isoformat()}\n用户原话：{request.text}",
        json_schema=_ProfileExtraction.model_json_schema(),
        purpose="profile-extraction/v2",
    )
    return _ProfileExtraction.model_validate(result.payload), result


def parse_profile_deterministic(request: ParseProfileRequest) -> ParseProfileResponse:
    """Stable baseline exposed for ablation experiments."""

    return _heuristic_parse(request)


def parse_profile(request: ParseProfileRequest) -> ParseProfileResponse:
    baseline = _heuristic_parse(request)
    if not settings.ollama_enabled:
        return baseline
    try:
        candidate, trace = _ollama_parse(request)
    except (ModelRuntimeError, ValidationError) as exc:
        baseline.fallback_used = True
        baseline.fallback_reason = str(exc)
        baseline.warnings.append("本地模型不可用或输出未通过模式校验，已安全降级为规则抽取。")
        return baseline

    model_fields = candidate.model_dump(mode="json", exclude_none=True)
    conflicts: list[str] = []
    for key, value in model_fields.items():
        if key in baseline.fields and str(baseline.fields[key]) != str(value):
            conflicts.append(key)
            continue
        if key not in baseline.fields:
            baseline.fields[key] = value
            # 这不是校准概率，只是给前端排序用的中性占位值；含义由confidence_basis明确。
            baseline.confidence[key] = 0.5
    baseline.missing_fields = [
        field
        for field in [
            "district",
            "household_size",
            "monthly_income_total",
            "assets_eligible",
            "member_scope_confirmed",
        ]
        if baseline.fields.get(field) is None
    ]
    if conflicts:
        baseline.warnings.append(
            f"模型与高精度规则在{len(conflicts)}个字段上冲突，已保留规则结果并要求人工确认。"
        )
    baseline.warnings.append("本地模型只补全画像草稿；全部关键字段仍须用户逐项确认。")
    baseline.provider = f"deterministic+{trace.provider}"
    baseline.mode = "llm_assisted"
    baseline.schema_validated = True
    baseline.model_id = trace.model_id
    baseline.latency_ms = trace.latency_ms
    baseline.prompt_sha256 = trace.prompt_sha256
    baseline.confidence_basis = "规则命中强度与模型中性占位值（均未经过概率校准）"
    return baseline

