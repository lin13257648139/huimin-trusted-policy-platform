from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from app.domain.models import PolicyCompileRequest
from app.services import policy_compiler as compiler


def _request(text: str, *, title: str = "政策测试", hint: str | None = None):
    return PolicyCompileRequest(
        source_id="BRANCH-TEST",
        title=title,
        source_text=text,
        region="广州市",
        benefit_hint=hint,
        use_llm=False,
    )


def test_date_and_benefit_detection_edge_paths() -> None:
    assert compiler._quote_for("第一句。第二句。", "不存在") == "第一句。第二句。"
    assert compiler._parse_chinese_date("2026", "2", "30") is None
    assert compiler._extract_dates("自2026年2月29日起施行") == (None, None)
    assert compiler._extract_dates("2026年8月1日实施，有效期至2027年7月31日") == (
        date(2026, 8, 1),
        date(2027, 7, 31),
    )
    leap_start, leap_end = compiler._extract_dates("自2024年2月29日起施行，有效期4年")
    assert (leap_start, leap_end) == (date(2024, 2, 29), date(2028, 2, 28))
    assert compiler._detect_benefit("可申请哪些救助", None, "社会救助一件事") == "B001"
    assert compiler._detect_benefit("指标说明", None, "申请家庭生活状况综合评估指标") == "B002"
    assert compiler._detect_benefit("最低生活保障边缘家庭", None) == "B003"
    assert compiler._detect_benefit("发生急难型事件", None) == "B005"
    assert compiler._detect_benefit("会议通知", None) == "unknown"
    assert compiler._detect_benefit("低保与社会救助", None) == "B002"


def test_parameter_extraction_covers_all_supported_numeric_forms() -> None:
    text = (
        "最低生活保障标准每人每月1300元；低保边缘家庭标准为1950元/人/月；"
        "最低生活保障标准的1.5倍；申请日前20日；"
        "刚性支出达到其家庭年收入的60%。"
    )
    parameters = compiler._extract_parameters(text, "B004")
    assert parameters == {
        "income_standard_monthly_per_capita": "1300.00",
        "edge_standard_monthly_per_capita": "1950.00",
        "income_multiplier": 1.5,
        "urgent_event_days": 20,
        "rigid_expense_income_ratio": 0.6,
    }
    assert compiler._extract_parameters("临时救助申请日前一个月发生急难", "B005") == {
        "urgent_event_days": 31
    }
    assert compiler._extract_parameters("申请日前一个月", "B002") == {}
    assert compiler._money_value("not-number") is None


def test_condition_extraction_covers_manual_and_emergency_paths() -> None:
    b004_text = (
        "具有本市户籍，共同生活家庭成员财产符合规定；家庭人均收入低于上年度"
        "本市居民人均可支配收入；必需支出占家庭总收入比例达到规定比例；"
        "基本生活困难，持有居住证。"
    )
    b004 = compiler._extract_conditions(b004_text, "B004", {})
    fields = {item.field for item in b004}
    assert {
        "per_capita_annual_income",
        "assets_eligible",
        "is_local_hukou",
        "rigid_expenses_12m",
        "member_scope_confirmed",
        "basic_life_interrupted",
        "residence_proof",
    } <= fields

    b005_text = "临时救助申请日前15日发生急难事件，基本生活无法维持。"
    parameters = compiler._extract_parameters(b005_text, "B005")
    b005 = compiler._extract_conditions(b005_text, "B005", parameters)
    assert {item.field for item in b005} == {
        "urgent_event",
        "urgent_event_date",
        "basic_life_interrupted",
    }


def test_llm_allowlist_validation_rejects_unanchored_and_malformed_values() -> None:
    request = _request("低保标准为1300元。共同生活家庭成员应当核对。", title="低保政策")
    assert compiler._parameter_has_source_anchor("unsupported", 1, request.source_text) is False
    assert (
        compiler._parameter_has_source_anchor(
            "income_standard_monthly_per_capita", True, request.source_text
        )
        is False
    )
    assert (
        compiler._parameter_has_source_anchor(
            "income_standard_monthly_per_capita", "一千三百元", request.source_text
        )
        is False
    )
    result = compiler._validated_llm_result(
        request,
        {
            "benefit_id": "B002",
            "effective_from": "bad-date",
            "effective_to": "2027-01-01",
            "parameters": {
                "income_standard_monthly_per_capita": 1300,
                "urgent_event_days": 99,
                "unsupported": 1,
            },
            "conditions": [
                "not-an-object",
                {
                    "field": "unsupported",
                    "operator": "eq",
                    "value": True,
                    "source_quote": "共同生活",
                },
                {
                    "field": "member_scope_confirmed",
                    "operator": "eq",
                    "value": True,
                    "source_quote": "共同生活",
                },
            ],
        },
    )
    assert result["benefit_id"] == "B002"
    assert result["effective_from"] is None
    assert result["effective_to"] == date(2027, 1, 1)
    assert result["parameters"] == {"income_standard_monthly_per_capita": 1300}
    assert len(result["conditions"]) == 1


def test_controlled_merge_only_fills_missing_allowlisted_values() -> None:
    request = _request("低保标准为1300元。共同生活家庭成员。", title="低保政策")
    deterministic = {
        "benefit_id": "unknown",
        "effective_from": None,
        "effective_to": None,
        "parameters": {},
        "conditions": [],
    }
    assert compiler._merge_llm(request, deterministic, None) == (deterministic, False, [])
    merged, used, conflicts = compiler._merge_llm(
        request,
        deterministic,
        {
            "benefit_id": "B002",
            "effective_from": "2026-01-01",
            "effective_to": "2026-12-31",
            "parameters": {"income_standard_monthly_per_capita": 1300},
            "conditions": [
                {
                    "field": "member_scope_confirmed",
                    "operator": "eq",
                    "value": True,
                    "source_quote": "共同生活",
                }
            ],
        },
    )
    assert used is True
    assert conflicts == []
    assert merged["benefit_id"] == "B002"
    assert merged["effective_from"] == date(2026, 1, 1)
    assert merged["parameters"]["income_standard_monthly_per_capita"] == 1300
    assert len(merged["conditions"]) == 1


def test_controlled_merge_rejects_duplicate_and_boundary_conflict() -> None:
    request = _request(
        "低保标准为1400元。共同生活家庭成员人均月收入低于最低生活保障标准，家庭财产符合规定。",
        title="低保政策",
        hint="B002",
    )
    parameters = compiler._extract_parameters(request.source_text, "B002")
    deterministic = {
        "benefit_id": "B002",
        "effective_from": None,
        "effective_to": None,
        "parameters": parameters,
        "conditions": compiler._extract_conditions(request.source_text, "B002", parameters),
    }
    merged, used, conflicts = compiler._merge_llm(
        request,
        deterministic,
        {
            "benefit_id": "B002",
            "effective_from": None,
            "effective_to": None,
            "parameters": {},
            "conditions": [
                {
                    "field": "per_capita_monthly_income",
                    "operator": "lt",
                    "value": 1400,
                    "unit": "元/人/月",
                    "source_quote": "人均月收入低于最低生活保障标准",
                },
                {
                    "field": "assets_eligible",
                    "operator": "eq",
                    "value": True,
                    "source_quote": "家庭财产符合规定",
                },
            ],
        },
    )

    assert used is True
    assert [item.field for item in merged["conditions"]].count("assets_eligible") == 1
    assert [item.field for item in merged["conditions"]].count("per_capita_monthly_income") == 1
    assert conflicts == [
        {
            "field": "per_capita_monthly_income",
            "kept": "lte 1400.00",
            "rejected": "lt 1400",
            "message": (
                "字段 per_capita_monthly_income 出现不一致条件：已保留 lte 1400.00，"
                "拒绝合并 lt 1400；必须回看原文确认边界。"
            ),
        }
    ]


def test_condition_deduplication_allows_a_consistent_numeric_range() -> None:
    conditions = [
        compiler.CompiledRuleCondition(
            field="per_capita_monthly_income",
            operator="gte",
            value=1000,
            source_quote="人均月收入不低于1000元",
        ),
        compiler.CompiledRuleCondition(
            field="per_capita_monthly_income",
            operator="lte",
            value="1400.00",
            source_quote="人均月收入不超过1400元",
        ),
    ]

    accepted, conflicts = compiler._deduplicate_conditions(conditions)

    assert accepted == conditions
    assert conflicts == []


def test_ollama_failure_is_auditable_safe_fallback(monkeypatch) -> None:
    monkeypatch.setattr(compiler, "settings", SimpleNamespace(ollama_enabled=True))
    monkeypatch.setattr(
        compiler,
        "chat_json",
        lambda **_kwargs: (_ for _ in ()).throw(compiler.ModelRuntimeError("offline")),
    )
    assert compiler._ollama_extract(
        _request("这是一段用于测试本地模型失败回退的低保政策原文。")
    ) == (
        None,
        None,
    )


def test_ollama_retries_once_with_concise_prompt(monkeypatch) -> None:
    monkeypatch.setattr(compiler, "settings", SimpleNamespace(ollama_enabled=True))
    prompts: list[str] = []

    def flaky_chat_json(**kwargs):
        prompts.append(kwargs["system_prompt"])
        if len(prompts) == 1:
            raise compiler.ModelRuntimeError("invalid-json")
        return compiler.JsonModelResult(
            payload={
                "benefit_id": "B004",
                "effective_from": None,
                "effective_to": None,
                "parameters": {},
                "conditions": [],
            },
            provider="ollama-json-schema",
            model_id="test-model",
            latency_ms=1,
            prompt_sha256="a" * 64,
            response_sha256="b" * 64,
        )

    monkeypatch.setattr(compiler, "chat_json", flaky_chat_json)
    payload, trace = compiler._ollama_extract(
        _request("这是一段用于测试格式修复重试的刚性支出困难家庭政策原文。")
    )

    assert payload is not None
    assert payload["benefit_id"] == "B004"
    assert trace is not None
    assert len(prompts) == 2
    assert "格式修复重试" not in prompts[0]
    assert "格式修复重试" in prompts[1]


def test_ollama_prompt_defines_every_benefit_identifier(monkeypatch) -> None:
    captured: dict[str, str] = {}
    monkeypatch.setattr(compiler, "settings", SimpleNamespace(ollama_enabled=True))

    def fake_chat_json(**kwargs):
        captured["system_prompt"] = kwargs["system_prompt"]
        return compiler.JsonModelResult(
            payload={},
            provider="ollama",
            model_id="test-model",
            latency_ms=1,
            prompt_sha256="a" * 64,
            response_sha256="b" * 64,
        )

    monkeypatch.setattr(compiler, "chat_json", fake_chat_json)
    compiler._ollama_extract(_request("这是一段用于测试编号语义映射的最低生活保障政策原文。"))

    prompt = captured["system_prompt"]
    assert "B001低收入人口认定与监测" in prompt
    assert "B002最低生活保障" in prompt
    assert "B003最低生活保障边缘家庭" in prompt
    assert "B004刚性支出困难家庭" in prompt
    assert "B005临时救助" in prompt
    assert "B006特困人员救助供养" in prompt


def test_compile_reports_invalid_range_and_missing_executable_fields() -> None:
    response = compiler.compile_policy(
        _request("自2027年1月1日起实施，有效期至2026年12月31日", hint="B002")
    )
    codes = {item.code for item in response.validation}
    assert {"invalid_effective_range", "no_executable_condition", "no_parameter"} <= codes


def test_impact_handles_unknown_and_non_threshold_benefits() -> None:
    unknown = compiler.compile_policy(
        _request("本通知用于安排会议室维护和值班采购流程，不涉及救助事项。")
    )
    assert compiler.analyze_policy_impact(unknown.candidate).comparable_cases == 0
    temporary = compiler.compile_policy(
        _request("本条规定临时救助急难事件应当转由人工核验并记录。", hint="B005")
    )
    impact = compiler.analyze_policy_impact(temporary.candidate)
    assert impact.comparable_cases == 0
    assert any("只对低保" in note for note in impact.notes)
