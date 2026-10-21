from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

GUANGZHOU_DISTRICTS = frozenset(
    {
        "越秀区", "海珠区", "荔湾区", "天河区", "白云区", "黄埔区",
        "花都区", "番禺区", "南沙区", "从化区", "增城区",
    }
)


class TruthValue(StrEnum):
    TRUE = "true"
    FALSE = "false"
    UNKNOWN = "unknown"


class EligibilityStatus(StrEnum):
    LIKELY = "likely"
    UNLIKELY = "unlikely"
    INCOMPLETE = "incomplete"
    MANUAL_REVIEW = "manual_review"


class BenefitId(StrEnum):
    LOW_INCOME_MONITORING = "B001"
    MINIMUM_LIVING = "B002"
    EDGE_FAMILY = "B003"
    RIGID_EXPENSE = "B004"
    TEMPORARY_RESCUE = "B005"
    SPECIAL_HARDSHIP = "B006"


class MaterialType(StrEnum):
    AUTO = "auto"
    IDENTITY = "identity"
    HOUSEHOLD_REGISTER = "household_register"
    INCOME = "income"
    MEDICAL_EXPENSE = "medical_expense"
    MEDICAL_DIAGNOSIS = "medical_diagnosis"
    EDUCATION_EXPENSE = "education_expense"
    RESIDENCE = "residence"
    VERIFICATION_AUTHORIZATION = "verification_authorization"


class HouseholdProfile(BaseModel):
    """资格预筛所需的最小家庭画像，不包含姓名、身份证和银行卡。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    query_date: date = Field(default_factory=date.today)
    city: str = "广州市"
    district: str = "天河区"
    household_size: int = Field(ge=1, le=30)
    is_local_hukou: bool | None = None
    has_local_family_member: bool | None = None
    member_scope_confirmed: bool | None = None

    monthly_income_total: Decimal | None = Field(default=None, ge=0)
    deductible_monthly_total: Decimal = Field(default=Decimal("0"), ge=0)
    assets_eligible: bool | None = None
    financial_assets_per_capita: Decimal | None = Field(default=None, ge=0)

    rigid_expenses_12m: Decimal | None = Field(default=None, ge=0)
    medical_expenses_12m: Decimal | None = Field(default=None, ge=0)
    education_expenses_12m: Decimal | None = Field(default=None, ge=0)

    # 未填写不是“否”。缺失值必须以 None/UNKNOWN 贯穿解析、规则和展示链路。
    urgent_event: bool | None = None
    urgent_event_date: date | None = None
    urgent_event_type: str | None = None
    basic_life_interrupted: bool | None = None
    residence_proof: bool | None = None

    # 特困人员救助供养以个人为认定对象。这里只采集申请前导办所需的四个
    # 最小事实，不能替代主管部门对劳动能力、生活来源和法定义务人的调查。
    special_person_category_confirmed: bool | None = None
    no_labor_capacity: bool | None = None
    no_livelihood_source: bool | None = None
    has_capable_legal_supporter: bool | None = None

    user_statement: str | None = Field(default=None, max_length=2000)
    confirmed_supplement_fields: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("confirmed_supplement_fields")
    @classmethod
    def validate_confirmed_supplement_fields(cls, value: list[str]) -> list[str]:
        allowed = {
            "district", "household_size", "is_local_hukou", "residence_proof",
            "member_scope_confirmed", "monthly_income_total",
            "deductible_monthly_total", "assets_eligible",
            "financial_assets_per_capita", "rigid_expenses_12m",
            "medical_expenses_12m", "education_expenses_12m", "urgent_event",
            "urgent_event_date", "urgent_event_type", "basic_life_interrupted",
            "special_person_category_confirmed", "no_labor_capacity",
            "no_livelihood_source", "has_capable_legal_supporter",
        }
        unknown = set(value) - allowed
        if unknown:
            raise ValueError(f"未知AI确认字段：{sorted(unknown)}")
        return list(dict.fromkeys(value))

    @field_validator("city")
    @classmethod
    def normalize_city(cls, value: str) -> str:
        if value in {"广州", "广州市"}:
            return "广州市"
        return value

    @model_validator(mode="after")
    def validate_event(self) -> HouseholdProfile:
        if self.city == "广州市" and self.district not in GUANGZHOU_DISTRICTS:
            raise ValueError("广州市画像的district必须是广州市行政区")
        if self.urgent_event_date and self.urgent_event is not True:
            raise ValueError("填写急难事件日期时，urgent_event必须为true")
        if self.deductible_monthly_total and self.monthly_income_total is not None:
            upper_bound = self.monthly_income_total * Decimal("3")
            if self.deductible_monthly_total > upper_bound:
                raise ValueError("月扣减额异常，请核对输入")
        return self

    @property
    def adjusted_monthly_income(self) -> Decimal | None:
        if self.monthly_income_total is None:
            return None
        return max(self.monthly_income_total - self.deductible_monthly_total, Decimal("0"))

    @property
    def per_capita_monthly_income(self) -> Decimal | None:
        if self.adjusted_monthly_income is None:
            return None
        return (self.adjusted_monthly_income / Decimal(self.household_size)).quantize(
            Decimal("0.01")
        )


class GuidanceDraft(BaseModel):
    """主动补问使用的最小草稿，允许字段尚未填写。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    query_date: date = Field(default_factory=date.today)
    city: str = "广州市"
    district: str | None = None
    household_size: int | None = Field(default=None, ge=1, le=30)
    is_local_hukou: bool | None = None
    member_scope_confirmed: bool | None = None
    monthly_income_total: Decimal | None = Field(default=None, ge=0)
    deductible_monthly_total: Decimal | None = Field(default=None, ge=0)
    assets_eligible: bool | None = None
    financial_assets_per_capita: Decimal | None = Field(default=None, ge=0)
    rigid_expenses_12m: Decimal | None = Field(default=None, ge=0)
    medical_expenses_12m: Decimal | None = Field(default=None, ge=0)
    education_expenses_12m: Decimal | None = Field(default=None, ge=0)
    urgent_event: bool | None = None
    urgent_event_date: date | None = None
    urgent_event_type: str | None = None
    basic_life_interrupted: bool | None = None
    residence_proof: bool | None = None
    special_person_category_confirmed: bool | None = None
    no_labor_capacity: bool | None = None
    no_livelihood_source: bool | None = None
    has_capable_legal_supporter: bool | None = None
    skipped_fields: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_region(self) -> GuidanceDraft:
        if (
            self.city in {"广州", "广州市"}
            and self.district is not None
            and self.district not in GUANGZHOU_DISTRICTS
        ):
            raise ValueError("广州市草稿的district必须是广州市行政区")
        return self

    @field_validator("skipped_fields")
    @classmethod
    def validate_skipped_fields(cls, value: list[str]) -> list[str]:
        allowed = {
            "district", "urgent_event", "household_size", "monthly_income_total",
            "member_scope_confirmed", "assets_eligible", "rigid_expenses_12m",
            "is_local_hukou", "urgent_event_date", "basic_life_interrupted",
            "residence_proof",
            "special_person_category_confirmed", "no_labor_capacity",
            "no_livelihood_source", "has_capable_legal_supporter",
        }
        unknown = set(value) - allowed
        if unknown:
            raise ValueError(f"未知跳过字段：{sorted(unknown)}")
        return list(dict.fromkeys(value))


class QuestionOption(BaseModel):
    value: str
    label: str


class GuidanceQuestion(BaseModel):
    field_id: str
    label: str
    plain_language: str
    reason: str
    input_type: Literal["select", "number", "date", "boolean"]
    options: list[QuestionOption] = Field(default_factory=list)
    unit: str | None = None
    affects: list[str] = Field(default_factory=list)
    priority_score: float
    expected_unknown_reduction: int = Field(default=0, ge=0)
    sensitivity_level: Literal["low", "medium", "high"] = "medium"
    skip_behavior: str = "跳过后保留UNKNOWN，不自动判为不符合。"


class GuidanceResponse(BaseModel):
    progress: int = Field(ge=0, le=100)
    completed_fields: int
    total_relevant_fields: int
    next_question: GuidanceQuestion | None
    candidate_benefits: list[str]
    urgent_notice: str | None = None


class ParseProfileRequest(BaseModel):
    text: str = Field(min_length=2, max_length=2000)
    query_date: date = Field(default_factory=date.today)
    district: str | None = None

    @field_validator("district")
    @classmethod
    def validate_district(cls, value: str | None) -> str | None:
        if value is not None and value not in GUANGZHOU_DISTRICTS:
            raise ValueError("district必须是广州市行政区")
        return value


class ParseProfileResponse(BaseModel):
    fields: dict[str, Any]
    confidence: dict[str, float]
    missing_fields: list[str]
    warnings: list[str]
    provider: str
    mode: Literal["deterministic", "llm_assisted"] = "deterministic"
    schema_validated: bool = True
    fallback_used: bool = False
    fallback_reason: str | None = None
    model_id: str | None = None
    latency_ms: int | None = Field(default=None, ge=0)
    prompt_sha256: str | None = None
    confidence_basis: str = "规则命中强度（未经过概率校准）"
    intent_model: str | None = None
    intent_predictions: list[dict[str, Any]] = Field(default_factory=list)


SupplementField = Literal[
    "district",
    "household_size",
    "is_local_hukou",
    "residence_proof",
    "member_scope_confirmed",
    "monthly_income_total",
    "deductible_monthly_total",
    "assets_eligible",
    "financial_assets_per_capita",
    "rigid_expenses_12m",
    "medical_expenses_12m",
    "education_expenses_12m",
    "urgent_event",
    "urgent_event_date",
    "urgent_event_type",
    "basic_life_interrupted",
    "special_person_category_confirmed",
    "no_labor_capacity",
    "no_livelihood_source",
    "has_capable_legal_supporter",
]


class SupplementAnalysisRequest(BaseModel):
    """用户完成结构化表单后，自愿补充的特殊情况。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    text: str = Field(min_length=2, max_length=2000)
    profile: GuidanceDraft


class SupplementCandidate(BaseModel):
    candidate_id: str
    field: SupplementField
    label: str
    proposed_value: str | int | float | bool
    display_value: str
    existing_value: str | int | float | bool | None = None
    existing_display: str | None = None
    source_quote: str = Field(min_length=1, max_length=500)
    comparison: Literal["new", "consistent", "conflict"]
    reason: str
    related_benefits: list[str] = Field(default_factory=list)
    requires_confirmation: bool = True
    extraction_score: float = Field(ge=0, le=1)


class SupplementClue(BaseModel):
    clue_id: str
    category: Literal[
        "medical",
        "employment",
        "education",
        "caregiving",
        "housing",
        "relationship",
        "emergency",
    ]
    label: str
    source_quote: str = Field(min_length=1, max_length=500)
    implication: str


class SupplementFollowUp(BaseModel):
    question_id: str
    field_id: SupplementField | None = None
    question: str
    reason: str
    options: list[QuestionOption] = Field(default_factory=list)
    unit: str | None = None


class SupplementImpactDirection(BaseModel):
    benefit_id: BenefitId
    benefit_name: str
    reason: str
    basis_fields: list[str] = Field(default_factory=list)


class SupplementSafetyAudit(BaseModel):
    sensitive_data_passed: bool
    instruction_gate_passed: bool
    domain_gate_passed: bool
    source_anchor_passed: bool
    raw_text_persisted: bool = False


class SupplementAnalysisResponse(BaseModel):
    analysis_id: str
    status: Literal[
        "ready_for_confirmation",
        "needs_clarification",
        "no_actionable_facts",
        "out_of_scope",
        "blocked_sensitive_data",
        "blocked_instruction",
    ]
    candidates: list[SupplementCandidate] = Field(default_factory=list)
    clues: list[SupplementClue] = Field(default_factory=list)
    ambiguities: list[str] = Field(default_factory=list)
    follow_up_questions: list[SupplementFollowUp] = Field(default_factory=list)
    impact_directions: list[SupplementImpactDirection] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    provider: str
    mode: Literal["deterministic", "llm_assisted", "not_called"] = "not_called"
    model_id: str | None = None
    latency_ms: int | None = Field(default=None, ge=0)
    confidence_basis: str = "抽取排序分数，不代表资格概率"
    safety: SupplementSafetyAudit
    disclaimer: str = (
        "AI只提出待确认事实和追问，不直接判定资格；只有用户确认后的字段才进入规则引擎。"
    )


class Evidence(BaseModel):
    evidence_id: str
    source_id: str
    title: str
    document_no: str | None = None
    article: str | None = None
    excerpt: str
    verbatim_quote: str | None = None
    plain_language_explanation: str | None = None
    locator: str | None = None
    local_file: str | None = None
    source_sha256: str | None = None
    quote_verified: bool = False
    verification_method: Literal["normalized_text_match", "visual_pdf_review", "ocr_text_match"] | None = None
    reviewed_at: date | None = None
    source_url: str
    effective_from: date | None = None
    effective_to: date | None = None
    status: str = "verified"


class PolicyQuestionRequest(BaseModel):
    """面向公开政策库的匿名问题，不接收身份号码等办事材料。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    question: str = Field(min_length=2, max_length=300)
    as_of: date | None = None
    max_evidence: int = Field(default=5, ge=1, le=8)


class PolicyAnswerClaim(BaseModel):
    text: str = Field(min_length=2, max_length=360)
    evidence_ids: list[str] = Field(min_length=1, max_length=3)


class PolicyAnswerResponse(BaseModel):
    status: Literal[
        "answered",
        "insufficient_evidence",
        "out_of_scope",
        "blocked_instruction",
        "blocked_sensitive_data",
    ]
    question: str
    as_of: date
    answer_title: str
    claims: list[PolicyAnswerClaim] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    unanswered: list[str] = Field(default_factory=list)
    retrieval: dict[str, Any] = Field(default_factory=dict)
    generation: dict[str, Any] = Field(default_factory=dict)
    grounding_validation: dict[str, Any] = Field(default_factory=dict)
    disclaimer: str = "仅依据已登记公开政策提供咨询线索，不构成受理、审批或资格认定。"


ConditionInputField = Literal[
    "district",
    "is_local_hukou",
    "residence_proof",
    "member_scope_confirmed",
    "monthly_income_total",
    "assets_eligible",
    "rigid_expenses_12m",
    "urgent_event",
    "basic_life_interrupted",
    "special_person_category_confirmed",
    "no_labor_capacity",
    "no_livelihood_source",
    "has_capable_legal_supporter",
]


class ConditionResult(BaseModel):
    code: str
    label: str
    state: TruthValue
    reason: str
    actual: str | int | float | None = None
    expected: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    hard: bool = True
    actionable: bool = False
    action_hint: str | None = None
    input_field: ConditionInputField | None = None


class AppliedBenefitRelation(BaseModel):
    relation_id: str
    relation_type: Literal["priority_fallback", "parallel_assessment", "monitoring_link"]
    related_benefit_id: str
    direction: Literal["outgoing", "incoming", "peer"]
    reason: str
    evidence_ids: list[str] = Field(default_factory=list)


class BenefitResult(BaseModel):
    benefit_id: str
    name: str
    status: EligibilityStatus
    score: float = Field(ge=0, le=100)
    summary: str
    conditions: list[ConditionResult]
    evidence: list[Evidence]
    missing_items: list[str]
    next_actions: list[str]
    materials: list[str]
    deadline: str
    policy_version: str
    policy_snapshot: str
    official_only: bool = False
    minimal_required_inputs: list[str] = Field(default_factory=list)
    plan_role: Literal["primary", "linked", "alternative", "manual", "not_recommended"] = (
        "alternative"
    )
    plan_reason: str = "等待组合导办规划。"
    plan_relations: list[AppliedBenefitRelation] = Field(default_factory=list)


class ScreeningResponse(BaseModel):
    screening_id: str
    created_at: datetime
    policy_snapshot: str
    query_date: date
    district: str
    profile_summary: dict[str, Any]
    results: list[BenefitResult]
    global_warnings: list[str]
    disclaimer: str
    engine_version: str = "unknown"
    combination_plan_version: str = "unknown"
    recommended_office: dict[str, Any] | None = None
    outcome: dict[str, Any] = Field(default_factory=dict)
    guidance_summary: list[str] = Field(default_factory=list)
    safety_validation: dict[str, Any] = Field(default_factory=dict)
    screening_token: str | None = None
    persisted: bool = False
    data_retention_days: int = Field(default=0, ge=0)


class AssessmentMemberAdjustments(BaseModel):
    """互斥后的成员分类计数；同一成员在3.1至3.3中只能进入最有利的一档。"""

    preschool: int = Field(default=0, ge=0, le=30)
    high_school_or_full_time_college: int = Field(default=0, ge=0, le=30)
    age_70_79: int = Field(default=0, ge=0, le=30)
    age_80_plus: int = Field(default=0, ge=0, le=30)
    rare_disease: int = Field(default=0, ge=0, le=30)
    severe_or_disabled: int = Field(default=0, ge=0, le=30)
    chronic_or_half_disabled: int = Field(default=0, ge=0, le=30)
    other_labor_affecting_disease: int = Field(default=0, ge=0, le=30)

    @property
    def classified_count(self) -> int:
        return sum(self.model_dump().values())


class LivingAssessmentRequest(BaseModel):
    """2025年第二版综合评估指标的匿名计算输入。"""

    query_date: date = Field(default_factory=date.today)
    household_member_count: int = Field(ge=1, le=30)

    wage_income_monthly_avg: Decimal | None = Field(default=None, ge=0)
    operating_income_monthly_avg: Decimal | None = Field(default=None, ge=0)
    property_income_monthly_avg: Decimal | None = Field(default=None, ge=0)
    transfer_income_monthly_avg: Decimal | None = Field(default=None, ge=0)
    employment_cost_claimed: Decimal | None = Field(default=None, ge=0)
    laborer_count: int | None = Field(default=None, ge=0, le=30)
    six_month_average_confirmed: bool | None = None
    labor_income_assessment_complete: bool | None = None

    member_adjustments: AssessmentMemberAdjustments = Field(
        default_factory=AssessmentMemberAdjustments
    )
    member_nonstack_confirmed: bool | None = None
    active_duty_conscript_count: int = Field(default=0, ge=0, le=30)

    obligor_strong_count: int = Field(default=0, ge=0, le=60)
    obligor_general_count: int = Field(default=0, ge=0, le=60)
    obligor_weak_count: int = Field(default=0, ge=0, le=60)
    obligor_none_count: int = Field(default=0, ge=0, le=60)
    obligor_unreachable_with_written_explanation_count: int = Field(default=0, ge=0, le=60)
    obligor_information_complete: bool | None = None
    judicial_support_cases: int = Field(default=0, ge=0, le=60)
    judicial_support_included_in_transfer_income: bool | None = None
    judicial_cases_excluded_from_obligor_counts: bool | None = None

    no_usable_owned_housing: bool | None = None
    counted_motorcycles: int | None = Field(default=None, ge=0, le=20)
    counted_electric_bicycles: int | None = Field(default=None, ge=0, le=30)
    vehicle_exclusions_confirmed: bool | None = None

    verification_report_available: bool | None = None
    in_home_assessment_completed: bool | None = None
    investigator_confirmed: bool | None = None
    household_confirmed: bool | None = None

    @model_validator(mode="after")
    def validate_member_classification(self) -> LivingAssessmentRequest:
        if self.member_adjustments.classified_count > self.household_member_count:
            raise ValueError("成员分类计数超过共同生活家庭成员人数；同一成员不得重复计分")
        if self.laborer_count is not None and self.laborer_count > self.household_member_count:
            raise ValueError("劳动者人数不能超过共同生活家庭成员人数")
        return self


class AssessmentCalculationLine(BaseModel):
    code: str
    label: str
    quantity: int | float
    coefficient_d: Decimal
    subtotal_d: Decimal
    evidence_id: str


class LivingAssessmentResponse(BaseModel):
    policy_version: str
    policy_effective_from: date
    policy_effective_to: date
    query_date: date
    calculation_status: Literal["not_available", "incomplete", "calculated"]
    review_state: Literal["manual_review", "needs_information", "calculation_draft", "ready_for_official_review"]
    d_standard_yuan: Decimal | None = None
    base_monthly_income_yuan: Decimal | None = None
    employment_cost_cap_yuan: Decimal | None = None
    employment_cost_applied_yuan: Decimal | None = None
    structure_adjustment_d: Decimal | None = None
    living_adjustment_d: Decimal | None = None
    adjusted_family_income_d: Decimal | None = None
    assessed_per_capita_d: Decimal | None = None
    assessed_per_capita_yuan: Decimal | None = None
    threshold_comparison: Literal["below_1d", "at_or_above_1d"] | None = None
    official_process_complete: bool = False
    calculation_lines: list[AssessmentCalculationLine] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    formula: str
    decision_boundary: str


class Office(BaseModel):
    office_id: str
    region: str
    office_name: str
    phone: str
    address: str
    source_id: str
    last_verified: date


class PolicySource(BaseModel):
    source_id: str
    scope: str
    topic: str
    title: str
    issuer: str
    document_no: str | None = None
    published_date: str | None = None
    effective_from: str | None = None
    effective_to: str | None = None
    status: str
    source_url: str
    priority: str
    usage_note: str


class FeedbackRequest(BaseModel):
    screening_id: str
    helpful: bool
    issue_type: Literal["none", "policy", "reasoning", "usability", "other"] = "none"
    comment: str | None = Field(default=None, max_length=1000)
    consent_to_store_comment: bool = False


class PolicyCompileRequest(BaseModel):
    """政策条款编译请求。输出只能作为待复核规则，不能直接发布。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    source_id: str = Field(min_length=3, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
    title: str = Field(min_length=4, max_length=200)
    source_text: str = Field(min_length=20, max_length=20000)
    region: str = Field(default="广州市", min_length=2, max_length=40)
    benefit_hint: Literal["B001", "B002", "B003", "B004", "B005", "B006"] | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    use_llm: bool = True
    extraction_strategy: Literal[
        "deterministic", "llm_only", "controlled_fusion"
    ] | None = None


class CompiledRuleCondition(BaseModel):
    field: Literal[
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
    ]
    operator: Literal["lt", "lte", "gte", "eq", "within_days", "ratio_gte"]
    value: str | int | float | bool
    unit: str | None = None
    source_quote: str = Field(min_length=2, max_length=500)


class PolicyRuleCandidate(BaseModel):
    candidate_id: str
    benefit_id: Literal["B001", "B002", "B003", "B004", "B005", "B006", "unknown"]
    benefit_name: str
    region: str
    source_id: str
    title: str
    effective_from: date | None = None
    effective_to: date | None = None
    parameters: dict[str, str | int | float | bool] = Field(default_factory=dict)
    conditions: list[CompiledRuleCondition] = Field(default_factory=list)
    exceptions: list[str] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)
    status: Literal["draft_requires_dual_review"] = "draft_requires_dual_review"
    provider: str
    extraction_completeness: float = Field(ge=0, le=1)
    source_sha256: str
    model_id: str | None = None
    prompt_sha256: str | None = None
    model_latency_ms: int | None = Field(default=None, ge=0)


class PolicyValidationIssue(BaseModel):
    severity: Literal["error", "warning", "info"]
    code: str
    message: str
    field: str | None = None


class PolicyCompileResponse(BaseModel):
    candidate: PolicyRuleCandidate
    validation: list[PolicyValidationIssue]
    publishable: bool = False
    publish_blockers: list[str]
    version_diff: dict[str, Any]


class PolicyImpactRequest(BaseModel):
    candidate: PolicyRuleCandidate


class PolicyImpactResponse(BaseModel):
    benefit_id: str
    baseline_version: str | None = None
    total_cases: int
    comparable_cases: int
    changed_cases: int
    changes_by_direction: dict[str, int]
    sample_case_ids: list[str]
    notes: list[str]

