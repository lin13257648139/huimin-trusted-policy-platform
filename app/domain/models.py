from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class TruthValue(str, Enum):
    TRUE = "true"
    FALSE = "false"
    UNKNOWN = "unknown"


class EligibilityStatus(str, Enum):
    LIKELY = "likely"
    UNLIKELY = "unlikely"
    INCOMPLETE = "incomplete"
    MANUAL_REVIEW = "manual_review"


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

    urgent_event: bool = False
    urgent_event_date: date | None = None
    urgent_event_type: str | None = None
    basic_life_interrupted: bool | None = None
    residence_proof: bool | None = None

    user_statement: str | None = Field(default=None, max_length=2000)

    @field_validator("city")
    @classmethod
    def normalize_city(cls, value: str) -> str:
        if value in {"广州", "广州市"}:
            return "广州市"
        return value

    @model_validator(mode="after")
    def validate_event(self) -> "HouseholdProfile":
        if self.urgent_event_date and not self.urgent_event:
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
    assets_eligible: bool | None = None
    rigid_expenses_12m: Decimal | None = Field(default=None, ge=0)
    urgent_event: bool | None = None
    urgent_event_date: date | None = None
    urgent_event_type: str | None = None
    basic_life_interrupted: bool | None = None
    residence_proof: bool | None = None
    skipped_fields: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("skipped_fields")
    @classmethod
    def validate_skipped_fields(cls, value: list[str]) -> list[str]:
        allowed = {
            "district", "urgent_event", "household_size", "monthly_income_total",
            "member_scope_confirmed", "assets_eligible", "rigid_expenses_12m",
            "is_local_hukou", "urgent_event_date", "basic_life_interrupted",
            "residence_proof",
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
    recommended_office: dict[str, Any] | None = None
    guidance_summary: list[str] = Field(default_factory=list)
    safety_validation: dict[str, Any] = Field(default_factory=dict)
    screening_token: str | None = None
    data_retention_days: int = 30


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


class PolicyCompileRequest(BaseModel):
    """政策条款编译请求。输出只能作为待复核规则，不能直接发布。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    source_id: str = Field(min_length=3, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
    title: str = Field(min_length=4, max_length=200)
    source_text: str = Field(min_length=20, max_length=20000)
    region: str = Field(default="广州市", min_length=2, max_length=40)
    benefit_hint: Literal["B001", "B002", "B003", "B004", "B005"] | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    use_llm: bool = True


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
    ]
    operator: Literal["lt", "lte", "gte", "eq", "within_days", "ratio_gte"]
    value: str | int | float | bool
    unit: str | None = None
    source_quote: str = Field(min_length=2, max_length=500)


class PolicyRuleCandidate(BaseModel):
    candidate_id: str
    benefit_id: Literal["B001", "B002", "B003", "B004", "B005"]
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

