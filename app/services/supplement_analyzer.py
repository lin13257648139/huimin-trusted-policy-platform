from __future__ import annotations

import hashlib
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import uuid4

from app.domain.models import (
    BenefitId,
    GuidanceDraft,
    ParseProfileRequest,
    SupplementAnalysisRequest,
    SupplementAnalysisResponse,
    SupplementCandidate,
    SupplementClue,
    SupplementFollowUp,
    SupplementImpactDirection,
    SupplementSafetyAudit,
)
from app.services.observability import increment
from app.services.profile_parser import MODEL_FIELD_ANCHORS, parse_profile
from app.services.question_engine import next_guidance_question

_SENSITIVE_PATTERNS = (
    re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
    re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)"),
    re.compile(r"(?:身份证|银行卡|社保卡)(?:号|号码)?[：:\s]*[A-Za-z0-9-]{8,}"),
    re.compile(r"(?:姓名|名字)[：:]\s*[\u4e00-\u9fff]{2,5}"),
)
_INSTRUCTION_ATTACK = re.compile(
    r"忽略.{0,10}(?:规则|要求|系统|之前)|系统提示词|开发者消息|"
    r"developer\s*message|system\s*prompt|泄露.{0,8}(?:提示词|密钥)|"
    r"编造|伪造|捏造|绕过.{0,8}(?:规则|核验)|不要核验|"
    r"直接.{0,10}(?:通过|符合|有资格)|替我.{0,8}(?:写成|改成|填成)",
    re.IGNORECASE,
)
_DOMAIN_TERMS = re.compile(
    r"家庭|收入|工资|存款|资产|房产|住房|车辆|户籍|户口|居住证|"
    r"失业|工作|住院|医疗|看病|患病|康复|残疾|护理|照护|学费|教育|"
    r"火灾|事故|困难|生活|劳动能力|生活来源|赡养|抚养|扶养|特困|"
    r"成员|父亲|母亲|爷爷|奶奶|孩子|子女|配偶|救助"
)

FIELD_LABELS = {
    "district": "准备咨询地区",
    "household_size": "共同生活人数",
    "is_local_hukou": "广州户籍成员",
    "residence_proof": "有效居住证明",
    "member_scope_confirmed": "共同生活成员范围",
    "monthly_income_total": "家庭月总收入",
    "deductible_monthly_total": "政策允许扣除的月支出",
    "assets_eligible": "家庭财产情况",
    "financial_assets_per_capita": "人均金融资产",
    "rigid_expenses_12m": "近12个月刚性支出",
    "medical_expenses_12m": "近12个月医疗支出",
    "education_expenses_12m": "近12个月教育支出",
    "urgent_event": "近期急难事件",
    "urgent_event_date": "急难事件日期",
    "urgent_event_type": "急难事件类型",
    "basic_life_interrupted": "基本生活受到严重影响",
    "special_person_category_confirmed": "特困供养对象线索",
    "no_labor_capacity": "劳动能力情况",
    "no_livelihood_source": "生活来源情况",
    "has_capable_legal_supporter": "法定赡养抚养扶养支持",
}

FIELD_BENEFITS: dict[str, tuple[str, ...]] = {
    "district": ("低收入人口认定与监测", "临时救助"),
    "household_size": ("最低生活保障", "低保边缘家庭认定", "刚性支出困难家庭认定"),
    "is_local_hukou": ("最低生活保障", "临时救助"),
    "residence_proof": ("临时救助",),
    "member_scope_confirmed": ("最低生活保障", "低保边缘家庭认定"),
    "monthly_income_total": ("最低生活保障", "低保边缘家庭认定", "刚性支出困难家庭认定"),
    "deductible_monthly_total": ("最低生活保障", "低保边缘家庭认定"),
    "assets_eligible": ("最低生活保障", "低保边缘家庭认定", "刚性支出困难家庭认定"),
    "financial_assets_per_capita": ("最低生活保障", "低保边缘家庭认定"),
    "rigid_expenses_12m": ("刚性支出困难家庭认定", "临时救助"),
    "medical_expenses_12m": ("刚性支出困难家庭认定", "临时救助"),
    "education_expenses_12m": ("刚性支出困难家庭认定",),
    "urgent_event": ("临时救助",),
    "urgent_event_date": ("临时救助",),
    "urgent_event_type": ("临时救助",),
    "basic_life_interrupted": ("临时救助",),
    "special_person_category_confirmed": ("特困人员救助供养",),
    "no_labor_capacity": ("特困人员救助供养",),
    "no_livelihood_source": ("特困人员救助供养",),
    "has_capable_legal_supporter": ("特困人员救助供养",),
}

BENEFITS = {
    "B001": "低收入人口认定与监测",
    "B002": "最低生活保障",
    "B003": "低保边缘家庭认定",
    "B004": "刚性支出困难家庭认定",
    "B005": "临时救助",
    "B006": "特困人员救助供养",
}
BENEFIT_IDS = {name: benefit_id for benefit_id, name in BENEFITS.items()}

CLUE_SPECS = (
    (
        "medical",
        "医疗或康复负担",
        re.compile(r"住院|生病|患病|看病|治疗|康复|长期服药"),
        "可能影响刚性支出困难家庭或临时救助核对，但仍需明确发生时间和实际自付金额。",
    ),
    (
        "employment",
        "就业与收入波动",
        re.compile(r"失业|没工作|没有工作|无固定工作|停工|收入不稳定|零工"),
        "可能影响收入核算；不能把‘没有固定工作’直接推断为零收入。",
    ),
    (
        "education",
        "教育支出",
        re.compile(r"上学|读书|学费|教育支出"),
        "可能影响刚性支出核对，需要确认近12个月实际支出。",
    ),
    (
        "caregiving",
        "照护负担",
        re.compile(r"照护|护理|长期照顾|需要照顾|无人赡养|法定义务人|特困供养"),
        "可能影响特困供养或家庭负担核对，但不能直接推断劳动能力和法定义务人情况。",
    ),
    (
        "housing",
        "住房与产权",
        re.compile(r"房子|住房|租房|借住|继承|留下来的房"),
        "住房来源和产权归属可能影响财产核对，需要由用户或窗口确认。",
    ),
    (
        "relationship",
        "家庭成员关系",
        re.compile(r"父亲|母亲|爷爷|奶奶|外公|外婆|孩子|子女|配偶|爱人"),
        "亲属关系不等于共同生活成员，需要确认是否共同生活并共同承担费用。",
    ),
    (
        "emergency",
        "突发急难事件",
        re.compile(r"火灾|交通事故|意外伤害|突发急病|重大疾病|急难事件"),
        "可能需要优先核对临时救助；如基本生活已无法维持，应先联系街道或12345。",
    ),
)


def _contains_sensitive_data(text: str) -> bool:
    return any(pattern.search(text) for pattern in _SENSITIVE_PATTERNS)


def _source_quote(text: str, field: str, value: Any | None = None) -> str | None:
    anchor = MODEL_FIELD_ANCHORS.get(field)
    clauses = [
        item.strip()
        for item in re.findall(r"[^，,。！？；\n]+[，,。！？；]?", text)
        if item.strip()
    ]
    for clause in clauses:
        if field in {"district", "urgent_event_type"} and value is not None:
            if str(value) in clause:
                return clause[:500]
        elif anchor is not None and anchor.search(clause):
            return clause[:500]
    return None


def _clue_quote(text: str, pattern: re.Pattern[str]) -> str:
    clauses = [
        item.strip()
        for item in re.findall(r"[^，,。！？；\n]+[，,。！？；]?", text)
        if item.strip()
    ]
    return next((item[:500] for item in clauses if pattern.search(item)), text[:500])


def _json_scalar(value: Any) -> str | int | float | bool:
    if isinstance(value, (date, Decimal)):
        return str(value)
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _comparable(value: Any) -> tuple[str, str]:
    if isinstance(value, bool):
        return ("bool", str(value).lower())
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        try:
            return ("number", str(Decimal(str(value)).normalize()))
        except InvalidOperation:
            pass
    if isinstance(value, date):
        return ("date", value.isoformat())
    text = str(value).strip()
    try:
        return ("number", str(Decimal(text).normalize()))
    except InvalidOperation:
        return ("text", text)


def _display_value(field: str, value: Any) -> str:
    if value is None:
        return "尚未填写"
    if isinstance(value, bool):
        choices = {
            "is_local_hukou": ("有", "没有"),
            "residence_proof": ("有", "没有"),
            "member_scope_confirmed": ("已确认", "可能有遗漏"),
            "assets_eligible": ("未发现超限", "可能超限"),
            "urgent_event": ("有", "没有"),
            "basic_life_interrupted": ("是", "否"),
            "special_person_category_confirmed": ("存在该类对象线索", "没有该类对象线索"),
            "no_labor_capacity": ("无劳动能力", "有劳动能力"),
            "no_livelihood_source": ("无生活来源", "有生活来源"),
            "has_capable_legal_supporter": ("有且能够履行", "没有或无履行能力"),
        }
        yes, no = choices.get(field, ("是", "否"))
        return yes if value else no
    if field == "household_size":
        return f"{value}人"
    if field in {
        "monthly_income_total", "deductible_monthly_total", "financial_assets_per_capita",
        "rigid_expenses_12m", "medical_expenses_12m", "education_expenses_12m",
    }:
        try:
            return f"{float(value):,.2f}元"
        except (TypeError, ValueError):
            return f"{value}元"
    return str(value)


def _candidate_id(field: str, quote: str) -> str:
    digest = hashlib.sha256(f"{field}\n{quote}".encode()).hexdigest()[:12]
    return f"SC-{digest}"


def _extract_clues(text: str) -> list[SupplementClue]:
    clues: list[SupplementClue] = []
    for category, label, pattern, implication in CLUE_SPECS:
        if not pattern.search(text):
            continue
        quote = _clue_quote(text, pattern)
        clues.append(
            SupplementClue(
                clue_id=f"CL-{category}-{len(clues) + 1}",
                category=category,  # type: ignore[arg-type]
                label=label,
                source_quote=quote,
                implication=implication,
            )
        )
    return clues


def _ambiguities(text: str, clues: list[SupplementClue], candidate_fields: set[str]) -> list[str]:
    items: list[str] = []
    if re.search(r"很多|不少|不高|不多|还可以|比较困难|条件(?:很好|不错)|家庭优越", text):
        items.append("描述中包含无法直接量化的程度词，系统不会把它自动换算为收入、资产或支出。")
    categories = {item.category for item in clues}
    if "relationship" in categories and "member_scope_confirmed" not in candidate_fields:
        items.append("提到了亲属，但尚不能确认其是否属于共同生活家庭成员。")
    if "housing" in categories and "assets_eligible" not in candidate_fields:
        items.append("提到了住房来源或产权，但尚不能判断是否计入家庭财产。")
    if "medical" in categories and "medical_expenses_12m" not in candidate_fields:
        items.append("提到了医疗困难，但缺少近12个月实际自付金额。")
    if "employment" in categories and "monthly_income_total" not in candidate_fields:
        items.append("提到了就业变化，但‘无固定工作’不等于没有收入。")
    return items


def _manual_follow_ups(
    profile: GuidanceDraft,
    clues: list[SupplementClue],
    candidate_fields: set[str],
) -> list[SupplementFollowUp]:
    categories = {item.category for item in clues}
    questions: list[SupplementFollowUp] = []
    if "relationship" in categories and profile.member_scope_confirmed is not True and "member_scope_confirmed" not in candidate_fields:
        questions.append(SupplementFollowUp(
            question_id="SQ-member-scope",
            field_id="member_scope_confirmed",
            question="补充说明中的亲属，是否与你共同生活并共同承担生活费用？",
            reason="亲属关系本身不能确定共同生活成员范围。",
        ))
    if "medical" in categories and profile.medical_expenses_12m is None and "medical_expenses_12m" not in candidate_fields:
        questions.append(SupplementFollowUp(
            question_id="SQ-medical-amount",
            field_id="medical_expenses_12m",
            question="近12个月医疗费用中，实际由家庭承担的金额大约是多少？",
            reason="只有明确金额才能进入支出计算；‘花了很多’不会被模型擅自换算。",
            unit="元/12个月",
        ))
    if "housing" in categories and profile.assets_eligible is None and "assets_eligible" not in candidate_fields:
        questions.append(SupplementFollowUp(
            question_id="SQ-housing-assets",
            field_id="assets_eligible",
            question="这套住房是否属于共同生活家庭成员，并已纳入家庭财产核对？",
            reason="需要区分居住事实、产权归属和政策财产口径。",
        ))
    if "employment" in categories and profile.monthly_income_total is None and "monthly_income_total" not in candidate_fields:
        questions.append(SupplementFollowUp(
            question_id="SQ-income-after-employment",
            field_id="monthly_income_total",
            question="就业变化后，家庭最近每月各类收入合计大约是多少？",
            reason="无固定工作不代表零收入，仍需填写可核对的家庭收入合计。",
            unit="元/月",
        ))
    return questions


def _dynamic_follow_ups(
    request: SupplementAnalysisRequest,
    candidates: list[SupplementCandidate],
    existing: list[SupplementFollowUp],
) -> list[SupplementFollowUp]:
    data = request.profile.model_dump(mode="json")
    for candidate in candidates:
        if candidate.comparison != "conflict":
            data[candidate.field] = candidate.proposed_value
    skipped: set[str] = set(data.get("skipped_fields") or [])
    seen: set[str] = {item.field_id for item in existing if item.field_id}
    questions = list(existing)
    for _ in range(5):
        try:
            draft = GuidanceDraft.model_validate({**data, "skipped_fields": sorted(skipped)})
            result = next_guidance_question(draft)
        except ValueError:
            break
        question = result.next_question
        if question is None:
            break
        skipped.add(question.field_id)
        if question.field_id in seen:
            continue
        questions.append(SupplementFollowUp(
            question_id=f"SQ-{question.field_id}",
            field_id=question.field_id,  # type: ignore[arg-type]
            question=question.plain_language,
            reason=question.reason,
            options=question.options,
            unit=question.unit,
        ))
        seen.add(question.field_id)
        if len(questions) >= 3:
            break
    return questions[:3]


def _impact_directions(
    candidates: list[SupplementCandidate], clues: list[SupplementClue]
) -> list[SupplementImpactDirection]:
    by_name: dict[str, set[str]] = {}
    for candidate in candidates:
        for name in candidate.related_benefits:
            by_name.setdefault(name, set()).add(FIELD_LABELS[candidate.field])
    clue_benefits = {
        "medical": ("刚性支出困难家庭认定", "临时救助"),
        "employment": ("低收入人口认定与监测", "最低生活保障", "低保边缘家庭认定"),
        "education": ("刚性支出困难家庭认定",),
        "caregiving": ("低收入人口认定与监测", "特困人员救助供养"),
        "housing": ("最低生活保障", "低保边缘家庭认定"),
        "relationship": ("最低生活保障", "低保边缘家庭认定"),
        "emergency": ("临时救助",),
    }
    for clue in clues:
        for name in clue_benefits[clue.category]:
            by_name.setdefault(name, set()).add(clue.label)
    result: list[SupplementImpactDirection] = []
    for name, bases in by_name.items():
        benefit_id = BENEFIT_IDS[name]
        result.append(SupplementImpactDirection(
            benefit_id=BenefitId(benefit_id),
            benefit_name=name,
            reason=f"补充说明涉及{'、'.join(sorted(bases))}；只有确认后的事实才会参与该方向的规则计算。",
            basis_fields=sorted(bases),
        ))
    return result


def _blocked_response(
    status: str,
    *,
    warning: str,
    sensitive_ok: bool,
    instruction_ok: bool,
    domain_ok: bool,
) -> SupplementAnalysisResponse:
    increment(f"supplement.status.{status}")
    return SupplementAnalysisResponse(
        analysis_id=f"SA-{uuid4().hex[:12].upper()}",
        status=status,  # type: ignore[arg-type]
        warnings=[warning],
        provider="safety-gate",
        mode="not_called",
        safety=SupplementSafetyAudit(
            sensitive_data_passed=sensitive_ok,
            instruction_gate_passed=instruction_ok,
            domain_gate_passed=domain_ok,
            source_anchor_passed=True,
        ),
    )


def analyze_supplement(request: SupplementAnalysisRequest) -> SupplementAnalysisResponse:
    text = request.text
    if _contains_sensitive_data(text):
        return _blocked_response(
            "blocked_sensitive_data",
            warning="检测到手机号、证件号、卡号或显式姓名；请删除这些信息后再分析。",
            sensitive_ok=False,
            instruction_ok=True,
            domain_ok=True,
        )
    if _INSTRUCTION_ATTACK.search(text):
        return _blocked_response(
            "blocked_instruction",
            warning="检测到要求编造、绕过核验或改写系统规则的内容，本次未调用模型。",
            sensitive_ok=True,
            instruction_ok=False,
            domain_ok=True,
        )

    parsed = parse_profile(ParseProfileRequest(
        text=text,
        query_date=request.profile.query_date,
        district=request.profile.district,
    ))
    profile_values = request.profile.model_dump(mode="json")
    candidates: list[SupplementCandidate] = []
    unsupported_fields: list[str] = []
    for field, raw_value in parsed.fields.items():
        if field not in FIELD_LABELS or raw_value is None:
            continue
        if field == "district" and str(raw_value) not in text:
            # district may be supplied as parser context; context is not a new user statement.
            continue
        if field == "rigid_expenses_12m" and "刚性支出" not in text:
            # 医疗/教育支出的算术合计不是用户逐字陈述的“刚性支出政策口径”。
            continue
        quote = _source_quote(text, field, raw_value)
        if quote is None or quote not in text:
            unsupported_fields.append(field)
            continue
        existing = profile_values.get(field)
        if existing is None:
            comparison = "new"
            reason = "表单中尚未填写；采用前需要你确认。"
        elif _comparable(existing) == _comparable(raw_value):
            comparison = "consistent"
            reason = "与表单中已经确认的信息一致，不会重复改写。"
        else:
            comparison = "conflict"
            reason = "与表单内容不一致；系统不会自动覆盖，必须由你选择。"
        scalar = _json_scalar(raw_value)
        candidates.append(SupplementCandidate(
            candidate_id=_candidate_id(field, quote),
            field=field,  # type: ignore[arg-type]
            label=FIELD_LABELS[field],
            proposed_value=scalar,
            display_value=_display_value(field, raw_value),
            existing_value=_json_scalar(existing) if existing is not None else None,
            existing_display=_display_value(field, existing) if existing is not None else None,
            source_quote=quote,
            comparison=comparison,  # type: ignore[arg-type]
            reason=reason,
            related_benefits=list(FIELD_BENEFITS.get(field, ())),
            requires_confirmation=comparison != "consistent",
            extraction_score=float(parsed.confidence.get(field, 0.5)),
        ))

    clues = _extract_clues(text)
    domain_ok = bool(_DOMAIN_TERMS.search(text) or candidates or clues)
    if not domain_ok:
        return _blocked_response(
            "out_of_scope",
            warning="这段内容与当前社会救助预筛无明显关系，请只补充家庭、收入、支出、居住或急难情况。",
            sensitive_ok=True,
            instruction_ok=True,
            domain_ok=False,
        )

    candidate_fields: set[str] = {item.field for item in candidates}
    ambiguities = _ambiguities(text, clues, candidate_fields)
    manual_questions = _manual_follow_ups(request.profile, clues, candidate_fields)
    follow_ups = _dynamic_follow_ups(request, candidates, manual_questions)
    impacts = _impact_directions(candidates, clues)
    actionable = [item for item in candidates if item.requires_confirmation]
    if actionable:
        status = "ready_for_confirmation"
    elif ambiguities or follow_ups:
        status = "needs_clarification"
    else:
        status = "no_actionable_facts"

    warnings = list(parsed.warnings)
    if unsupported_fields:
        warnings.append(
            f"{len(unsupported_fields)}个候选字段没有找到可展示的原句锚点，已从结果中移除。"
        )
    warnings.append("抽取分数只用于候选排序，不代表政策资格概率。")
    increment(f"supplement.status.{status}")
    increment("supplement.conflict", sum(item.comparison == "conflict" for item in candidates))
    return SupplementAnalysisResponse(
        analysis_id=f"SA-{uuid4().hex[:12].upper()}",
        status=status,  # type: ignore[arg-type]
        candidates=candidates,
        clues=clues,
        ambiguities=ambiguities,
        follow_up_questions=follow_ups,
        impact_directions=impacts,
        warnings=warnings,
        provider=parsed.provider,
        mode=parsed.mode,
        model_id=parsed.model_id,
        latency_ms=parsed.latency_ms,
        safety=SupplementSafetyAudit(
            sensitive_data_passed=True,
            instruction_gate_passed=True,
            domain_gate_passed=True,
            source_anchor_passed=all(item.source_quote in text for item in candidates),
        ),
    )
