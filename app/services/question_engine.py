from __future__ import annotations

from dataclasses import dataclass

from app.domain.models import (
    GuidanceDraft,
    GuidanceQuestion,
    GuidanceResponse,
    QuestionOption,
)


BENEFIT_NAMES = {
    "B001": "低收入人口认定与监测",
    "B002": "最低生活保障",
    "B003": "低保边缘家庭认定",
    "B004": "刚性支出困难家庭认定",
    "B005": "临时救助",
}


@dataclass(frozen=True)
class QuestionSpec:
    field_id: str
    label: str
    plain_language: str
    reason: str
    input_type: str
    affects: tuple[str, ...]
    effort: float
    sensitivity: float
    options: tuple[tuple[str, str], ...] = ()
    unit: str | None = None


QUESTIONS = (
    QuestionSpec(
        "district",
        "所在区",
        "你目前在广州哪个区办理或居住？",
        "用于推荐对应区的办理窗口，不影响你获得通用说明。",
        "select",
        ("B001", "B002", "B003", "B004", "B005"),
        0.5,
        0.1,
        tuple((item, item) for item in ("越秀区", "海珠区", "荔湾区", "天河区", "白云区", "黄埔区", "花都区", "番禺区", "南沙区", "从化区", "增城区")),
    ),
    QuestionSpec(
        "urgent_event",
        "近期是否发生急难事件",
        "最近是否发生突发急病、火灾、事故等，已经影响基本生活？",
        "急难情形可能需要先走临时救助快速通道。",
        "boolean",
        ("B005",),
        0.4,
        0.3,
        (("true", "是"), ("false", "否"), ("", "不清楚")),
    ),
    QuestionSpec(
        "household_size",
        "共同生活人数",
        "通常一起生活、共同承担生活费用的家庭成员有几人？",
        "人数用于计算人均收入；不确定时可以先填大致人数并在窗口核对。",
        "number",
        ("B002", "B003", "B004"),
        0.8,
        0.3,
        unit="人",
    ),
    QuestionSpec(
        "monthly_income_total",
        "家庭月总收入",
        "共同生活家庭成员最近每月收入合计大约是多少？",
        "用于和当年收入标准比较；这里只做预估，最终由主管部门核定。",
        "number",
        ("B002", "B003", "B004"),
        1.0,
        0.8,
        unit="元/月",
    ),
    QuestionSpec(
        "member_scope_confirmed",
        "共同生活成员是否确认",
        "家庭成员范围是否已经基本确认？",
        "成员范围会同时影响人数和收入计算。",
        "boolean",
        ("B002", "B003"),
        0.7,
        0.4,
        (("true", "已确认"), ("false", "可能不完整"), ("", "不清楚")),
    ),
    QuestionSpec(
        "assets_eligible",
        "财产情况是否已核对",
        "目前是否发现房产、车辆、金融资产等可能超过政策条件？",
        "财产情况是多项救助的必要核验项；系统不要求填写账户号码。",
        "boolean",
        ("B002", "B003", "B004"),
        0.9,
        0.9,
        (("true", "未发现超标项"), ("false", "存在可能超标项"), ("", "尚未核对")),
    ),
    QuestionSpec(
        "rigid_expenses_12m",
        "近12个月必要支出",
        "近12个月医疗、教育、康复等必要支出合计大约是多少？",
        "有较大必要支出时，可能需要继续核验刚性支出困难家庭或临时救助。",
        "number",
        ("B004", "B005"),
        1.0,
        0.8,
        unit="元/12个月",
    ),
    QuestionSpec(
        "is_local_hukou",
        "是否广州户籍",
        "家庭中申请人是否具有广州户籍？",
        "临时救助等事项可能还需要结合居住证明判断。",
        "boolean",
        ("B001", "B002", "B003", "B004", "B005"),
        0.6,
        0.5,
        (("true", "是"), ("false", "否"), ("", "不清楚")),
    ),
    QuestionSpec(
        "urgent_event_date",
        "急难事件发生日期",
        "急难事件大约是哪一天发生的？",
        "用于区分近期急难情形和需要进一步核验的支出型情形。",
        "date",
        ("B005",),
        0.5,
        0.4,
    ),
    QuestionSpec(
        "basic_life_interrupted",
        "基本生活是否受影响",
        "事件是否已经导致吃饭、居住或基本生活难以维持？",
        "严重影响基本生活时，应优先提示人工快速通道。",
        "boolean",
        ("B005",),
        0.5,
        0.6,
        (("true", "是"), ("false", "否"), ("", "不清楚")),
    ),
    QuestionSpec(
        "residence_proof",
        "是否有广州居住证明",
        "非广州户籍时，是否有广州居住证或连续居住证明？",
        "用于确定临时救助的办理路径；紧急情形仍应直接联系街道。",
        "boolean",
        ("B005",),
        0.6,
        0.5,
        (("true", "有"), ("false", "没有"), ("", "不清楚")),
    ),
)


def _is_relevant(spec: QuestionSpec, draft: GuidanceDraft) -> bool:
    if spec.field_id in {"urgent_event_date", "basic_life_interrupted"}:
        return draft.urgent_event is True
    if spec.field_id == "residence_proof":
        return draft.urgent_event is True and draft.is_local_hukou is False
    return True


def _is_answered(spec: QuestionSpec, draft: GuidanceDraft) -> bool:
    return getattr(draft, spec.field_id, None) is not None or spec.field_id in draft.skipped_fields


def _candidate_ids(draft: GuidanceDraft) -> list[str]:
    candidates = ["B001", "B002", "B003", "B004"]
    if draft.urgent_event is not False:
        candidates.insert(0, "B005")
    return candidates


def next_guidance_question(draft: GuidanceDraft) -> GuidanceResponse:
    relevant = [spec for spec in QUESTIONS if _is_relevant(spec, draft)]
    unanswered = [spec for spec in relevant if not _is_answered(spec, draft)]
    candidates = _candidate_ids(draft)

    def priority(spec: QuestionSpec) -> float:
        affected = len(set(spec.affects) & set(candidates))
        # 先定位属地，再尽快筛出可能需要人工快速响应的急难情形。
        urgency = 60 if spec.field_id == "urgent_event" else 0
        if draft.urgent_event is True and spec.field_id in {"urgent_event_date", "basic_life_interrupted"}:
            urgency += 24
        prerequisite = 12 if spec.field_id in {"district", "household_size"} else 0
        return round(affected * 12 + urgency + prerequisite - spec.effort * 4 - spec.sensitivity * 3, 2)

    unanswered.sort(key=priority, reverse=True)
    question = None
    if unanswered:
        spec = unanswered[0]
        question = GuidanceQuestion(
            field_id=spec.field_id,
            label=spec.label,
            plain_language=spec.plain_language,
            reason=spec.reason,
            input_type=spec.input_type,  # type: ignore[arg-type]
            options=[QuestionOption(value=value, label=label) for value, label in spec.options],
            unit=spec.unit,
            affects=[BENEFIT_NAMES[item] for item in spec.affects],
            priority_score=priority(spec),
            expected_unknown_reduction=len(set(spec.affects) & set(candidates)),
            sensitivity_level=("high" if spec.sensitivity >= 0.75 else "medium" if spec.sensitivity >= 0.4 else "low"),
            skip_behavior="跳过后相关事项保留“还需确认”，系统不会据此判定不符合。",
        )

    completed = len(relevant) - len(unanswered)
    progress = round(completed / max(len(relevant), 1) * 100)
    urgent_notice = None
    if draft.urgent_event is True and draft.basic_life_interrupted is True:
        urgent_notice = "如果基本生活已经无法维持，请不要等待线上预筛，优先联系所在街道或广州12345。"
    return GuidanceResponse(
        progress=progress,
        completed_fields=completed,
        total_relevant_fields=len(relevant),
        next_question=question,
        candidate_benefits=[BENEFIT_NAMES[item] for item in candidates],
        urgent_notice=urgent_notice,
    )
