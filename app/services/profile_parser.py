from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.config import settings
from app.domain.models import GUANGZHOU_DISTRICTS, ParseProfileRequest, ParseProfileResponse
from app.services.ai_runtime import ModelRuntimeError, chat_json
from app.services.intent_classifier import classify_intent

DISTRICTS = sorted(GUANGZHOU_DISTRICTS)

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

# 模型只能补充原文中存在相应语义锚点的字段。Schema 能限制“字段长什么样”，
# 但不能证明字段“来自原文”；这道独立门专门阻断语义联想型幻觉。
MODEL_FIELD_ANCHORS: dict[str, re.Pattern[str]] = {
    "district": re.compile("区"),
    "household_size": re.compile(r"(?:口|个?人)(?:之家|家庭)?"),
    "is_local_hukou": re.compile(r"(?:户籍|户口)"),
    "has_local_family_member": re.compile(r"(?:本市|广州).{0,8}(?:家庭成员|亲属)"),
    "member_scope_confirmed": re.compile(r"共同生活.{0,10}(?:成员|家庭成员)"),
    "residence_proof": re.compile(r"(?:居住证|居住登记|居住凭证|连续居住)"),
    "monthly_income_total": re.compile(r"(?:月|每月).{0,8}收入|收入.{0,8}(?:每月|/月)"),
    "deductible_monthly_total": re.compile(r"(?:扣减|扣除).{0,8}(?:支出|费用|金额)"),
    "assets_eligible": re.compile(r"(?:财产状况|家庭财产)"),
    "financial_assets_per_capita": re.compile(r"(?:金融资产|存款|理财|证券).{0,10}(?:人均|每人)"),
    "rigid_expenses_12m": re.compile(r"(?:刚性支出|医疗|看病|治病|生病|患病|住院|教育|学费)"),
    "medical_expenses_12m": re.compile(r"(?:医疗|看病|治病|生病|患病|住院)"),
    "education_expenses_12m": re.compile(r"(?:教育|学费)"),
    "urgent_event": re.compile(
        r"(?:火灾|交通事故|重大疾病|突发急病|意外伤害|急难事件|"
        r"(?:近期|最近).{0,12}(?:生病|患病|就医|住院))"
    ),
    "urgent_event_date": re.compile(
        r"(?:\d{4}[-/.年]\d{1,2}[-/.月]\d{1,2}(?:日)?|\d{1,2}月\d{1,2}日)"
    ),
    "urgent_event_type": re.compile(r"(?:火灾|交通事故|重大疾病|突发急病|意外伤害|急难事件)"),
    "basic_life_interrupted": re.compile(
        r"(?:基本生活|生活).{0,10}(?:困难|中断|无法维持|陷入困难|受到.{0,4}影响|受.{0,4}影响)"
    ),
    "special_person_category_confirmed": re.compile(
        r"(?:特困人员|特困供养|老年人|未成年人|残疾人)"
    ),
    "no_labor_capacity": re.compile(r"(?:无劳动能力|没有劳动能力|不能劳动|有劳动能力)"),
    "no_livelihood_source": re.compile(
        r"(?:无生活来源|没有生活来源|没有收入来源|有生活来源|有收入来源)"
    ),
    "has_capable_legal_supporter": re.compile(
        r"(?:赡养|抚养|扶养|法定义务人|子女).{0,16}(?:能力|履行|照顾|支持|供养)"
    ),
}

INSTRUCTION_ATTACK_PATTERN = re.compile(
    r"(?:忽略.{0,8}(?:规则|要求|系统)|编造|伪造|捏造|绕过.{0,6}(?:规则|核验)|"
    r"不要核验|直接(?:说|写).{0,8}(?:通过|符合|确认)|替我.{0,8}(?:写成|改成|填成))"
)


def _model_field_has_source_anchor(key: str, value: Any, text: str) -> bool:
    anchor = MODEL_FIELD_ANCHORS.get(key)
    if anchor is None or not anchor.search(text):
        return False
    if key in {"district", "urgent_event_type"}:
        return str(value) in text
    return True


def _contains_instruction_attack(text: str) -> bool:
    return INSTRUCTION_ATTACK_PATTERN.search(text) is not None


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
    special_person_category_confirmed: bool | None = None
    no_labor_capacity: bool | None = None
    no_livelihood_source: bool | None = None
    has_capable_legal_supporter: bool | None = None

    @field_validator("district")
    @classmethod
    def validate_district(cls, value: str | None) -> str | None:
        if value is not None and value not in DISTRICTS:
            raise ValueError("district必须是广州市行政区")
        return value


def _money(value: str, unit: str | None) -> Decimal:
    multiplier = Decimal("10000") if unit == "万" else Decimal("1")
    return (Decimal(value) * multiplier).quantize(Decimal("0.01"))


def _missing_profile_fields(fields: dict[str, Any]) -> list[str]:
    """Return unanswered facts without replacing silence with a negative fact."""

    required = [
        "district",
        "household_size",
        "monthly_income_total",
        "assets_eligible",
        "member_scope_confirmed",
        "is_local_hukou",
        "urgent_event",
        "special_person_category_confirmed",
    ]
    if fields.get("urgent_event") is True:
        required.extend(["urgent_event_date", "basic_life_interrupted"])
    if fields.get("is_local_hukou") is False:
        required.append("residence_proof")
    if fields.get("special_person_category_confirmed") is True:
        required.extend(
            ["no_labor_capacity", "no_livelihood_source", "has_capable_legal_supporter"]
        )
    return [field for field in required if fields.get(field) is None]


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
    if _contains_instruction_attack(text):
        intent_model, intent_predictions = classify_intent(text)
        warnings.append("检测到要求编造或绕过核验的指令，未从该段生成资格关键事实。")
        return ParseProfileResponse(
            fields=fields,
            confidence=confidence,
            missing_fields=_missing_profile_fields(fields),
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

    size_match = re.search(
        r"([1-9]|[一二两三四五六七八九十])\s*(?:口|个?人)(?:之家|家庭)?", text
    )
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
        (
            "medical_expenses_12m",
            r"(?:医疗|看病|治病|生病|患病|住院)(?:支出|花费|费用|花了|花)?(?:约|是|为)?\s*(\d+(?:\.\d+)?)\s*(万)?元?",
        ),
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
    if re.search(
        r"基本生活.{0,10}(困难|中断|无法维持|受到.{0,4}影响|受.{0,4}影响)|生活陷入困难",
        text,
    ):
        fields["basic_life_interrupted"] = True
        confidence["basic_life_interrupted"] = 0.86

    special_explicit = re.search(r"(?:申请|咨询|核对|属于|办理).{0,8}(?:特困人员|特困供养)|特困人员", text)
    special_denied = re.search(r"(?:不属于|不是|不申请|不咨询).{0,6}(?:特困人员|特困供养)", text)
    if special_denied:
        fields["special_person_category_confirmed"] = False
        confidence["special_person_category_confirmed"] = 0.94
    elif special_explicit:
        fields["special_person_category_confirmed"] = True
        confidence["special_person_category_confirmed"] = 0.9
    if re.search(r"(?:无|没有|完全丧失).{0,4}劳动能力|不能劳动", text):
        fields["no_labor_capacity"] = True
        confidence["no_labor_capacity"] = 0.93
    elif re.search(r"(?:仍有|具有|有).{0,4}劳动能力", text):
        fields["no_labor_capacity"] = False
        confidence["no_labor_capacity"] = 0.93
    if re.search(r"(?:无|没有).{0,4}(?:生活来源|收入来源)", text):
        fields["no_livelihood_source"] = True
        confidence["no_livelihood_source"] = 0.92
    elif re.search(r"(?:有|具有).{0,4}(?:生活来源|收入来源)", text):
        fields["no_livelihood_source"] = False
        confidence["no_livelihood_source"] = 0.92
    if re.search(
        r"(?:没有|无)(?:能够履行义务的)?(?:法定)?(?:赡养|抚养|扶养)(?:义务人|人)|"
        r"(?:赡养|抚养|扶养)(?:义务人|人).{0,10}(?:无|没有)(?:履行)?能力|无人赡养",
        text,
    ):
        fields["has_capable_legal_supporter"] = False
        confidence["has_capable_legal_supporter"] = 0.88
    elif re.search(
        r"(?:赡养|抚养|扶养)(?:义务人|人).{0,10}(?:有|具备)(?:履行)?能力|"
        r"有子女.{0,8}(?:赡养|照顾|供养)",
        text,
    ):
        fields["has_capable_legal_supporter"] = True
        confidence["has_capable_legal_supporter"] = 0.88

    missing = _missing_profile_fields(fields)
    if missing:
        warnings.append("自动识别只会预填待确认信息；金额和资格相关内容必须由你逐项确认。")
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
        "urgent_event只有在用户明确说明发生或明确否认发生时才能填写true或false；"
        "用户未提及急难事件时必须为null，严禁把沉默推断为false。"
        "special_person_category_confirmed只有用户明确咨询特困供养或明确否认时才填写；"
        "no_labor_capacity、no_livelihood_source和has_capable_legal_supporter都必须有原文明确表述，"
        "不得根据年龄、残疾或家庭关系自行推断。"
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
    unsupported: list[str] = []
    instruction_attack = _contains_instruction_attack(request.text)
    for key, value in model_fields.items():
        # 原文即使包含字段语义锚点，明确要求编造或跳过核验时也不得
        # 把“指令中的目标值”当成“用户自述事实”。
        if instruction_attack:
            unsupported.append(key)
            continue
        if not _model_field_has_source_anchor(key, value, request.text):
            unsupported.append(key)
            continue
        if key in baseline.fields and str(baseline.fields[key]) != str(value):
            conflicts.append(key)
            continue
        if key not in baseline.fields:
            baseline.fields[key] = value
            # 这不是校准概率，只是给前端排序用的中性占位值；含义由confidence_basis明确。
            baseline.confidence[key] = 0.5
    baseline.missing_fields = _missing_profile_fields(baseline.fields)
    if conflicts:
        baseline.warnings.append(
            f"模型与高精度规则在{len(conflicts)}个字段上冲突，已保留规则结果并要求人工确认。"
        )
    if unsupported:
        baseline.warnings.append(
            f"模型提出的{len(unsupported)}个字段缺少原文语义锚点，已拒绝自动填写。"
        )
    baseline.warnings.append("本地模型只补全待确认信息；全部关键字段仍须你逐项确认。")
    baseline.provider = f"deterministic+{trace.provider}"
    baseline.mode = "llm_assisted"
    baseline.schema_validated = True
    baseline.model_id = trace.model_id
    baseline.latency_ms = trace.latency_ms
    baseline.prompt_sha256 = trace.prompt_sha256
    baseline.confidence_basis = "规则命中强度与模型中性占位值（均未经过概率校准）"
    return baseline

