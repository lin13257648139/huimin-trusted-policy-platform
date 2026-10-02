from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from pydantic import ValidationError


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.domain.models import CompiledRuleCondition, HouseholdProfile, ParseProfileRequest, PolicyCompileRequest
from app.services import profile_parser
from app.services.policy_compiler import compile_policy
from app.services.retrieval import search_evidence_result
from app.services.rule_engine import ENGINE_VERSION, evaluate_profile
from app.version import APP_VERSION


DATASET = ROOT / "data" / "processed" / "synthetic_conformance_cases.jsonl"
OUTPUT = ROOT / "data" / "evaluation" / "ablation_report.json"


def main() -> None:
    cases = [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines() if line]
    full_mismatches = 0
    forced_binary_decisions = 0
    temporal_snapshot_changes = 0
    temporal_status_changes = 0
    evidence_conditions = 0
    evidence_linked_conditions = 0
    status_counts: Counter[str] = Counter()
    for item in cases:
        profile = HouseholdProfile.model_validate(item["profile"])
        snapshot, results, _ = evaluate_profile(profile)
        actual = {result.benefit_id: result.status.value for result in results}
        full_mismatches += snapshot.snapshot_id != item["expected_policy_snapshot"]
        full_mismatches += any(actual[key] != value for key, value in item["expected_status"].items())
        for result in results:
            status_counts[result.status.value] += 1
            forced_binary_decisions += result.status.value in {"incomplete", "manual_review"}
            for condition in result.conditions:
                evidence_conditions += 1
                evidence_linked_conditions += bool(condition.evidence_ids)

        frozen_profile = profile.model_copy(update={"query_date": date(2026, 9, 30)})
        frozen_snapshot, frozen_results, _ = evaluate_profile(frozen_profile)
        frozen_status = {result.benefit_id: result.status.value for result in frozen_results}
        temporal_snapshot_changes += (
            frozen_snapshot.dibao_version,
            frozen_snapshot.local_rule_available,
        ) != (
            snapshot.dibao_version,
            snapshot.local_rule_available,
        )
        temporal_status_changes += sum(
            frozen_status[benefit_id] != status for benefit_id, status in actual.items()
        )

    probe_profile = HouseholdProfile.model_validate(cases[0]["profile"])
    temporal_probes = []
    for probe_date in (date(2026, 7, 31), date(2026, 8, 1), date(2027, 8, 1)):
        probe = probe_profile.model_copy(update={"query_date": probe_date})
        probe_snapshot, probe_results, probe_warnings = evaluate_profile(probe)
        temporal_probes.append(
            {
                "query_date": probe_date.isoformat(),
                "snapshot": probe_snapshot.snapshot_id,
                "dibao_version": probe_snapshot.dibao_version,
                "dibao_status": next(
                    result.status.value for result in probe_results if result.benefit_id == "B002"
                ),
                "warning_count": len(probe_warnings),
            }
        )

    report = {
        "report_schema": "safety-ablation/1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "app_version": APP_VERSION,
        "engine_version": ENGINE_VERSION,
        "dataset": DATASET.relative_to(ROOT).as_posix(),
        "dataset_sha256": hashlib.sha256(DATASET.read_bytes()).hexdigest(),
        "dataset_role": "engine_conformance_only; labels originate from the deterministic engine",
        "cases": len(cases),
        "full_system": {
            "regression_mismatches": full_mismatches,
            "status_distribution": dict(status_counts),
            "evidence_link_coverage": round(
                evidence_linked_conditions / max(evidence_conditions, 1), 4
            ),
        },
        "ablations": {
            "collapse_three_value_to_binary": {
                "forced_uncertain_to_negative": forced_binary_decisions,
                "meaning": "若把信息不足/人工核验强制折叠为不符合，会丢失这些安全拒答。",
            },
            "remove_temporal_selection": {
                "profiles_using_different_rule_version": temporal_snapshot_changes,
                "benefit_statuses_changed": temporal_status_changes,
                "controlled_boundary_probes": temporal_probes,
                "meaning": "把所有案例错误地固定到2026-09-30规则后，与原查询日期结果的差异。",
            },
            "remove_evidence_links": {
                "conditions_losing_traceability": evidence_linked_conditions,
                "meaning": "移除证据ID后不可追溯的条件数量。",
            },
        },
        "claim_boundary": "该报告衡量架构安全属性，不是业务准确率，也不是用户试点。",
    }

    invalid_conditions = [
        {"field": "bank_card_number", "operator": "eq", "value": "x", "source_quote": "原文"},
        {"field": "assets_eligible", "operator": "execute_code", "value": True, "source_quote": "原文"},
        {"field": "assets_eligible", "operator": "eq", "value": True, "source_quote": ""},
        {"field": "rigid_expenses_12m", "operator": "ratio_gte", "value": 0.6, "source_quote": "刚性支出达到60%"},
    ]
    rejected = 0
    for payload in invalid_conditions:
        try:
            CompiledRuleCondition.model_validate(payload)
        except ValidationError:
            rejected += 1
    report["ablations"]["remove_schema_constraints"] = {
        "unsafe_payloads_tested": len(invalid_conditions),
        "invalid_payloads_rejected_by_full_system": rejected,
        "meaning": "白名单Schema会阻断非法字段、非法操作符和无原文引用；合法控制样本应通过。",
    }

    original_settings = profile_parser.settings
    original_ollama_parse = profile_parser._ollama_parse
    protected_conflicts = 0
    try:
        profile_parser.settings = SimpleNamespace(ollama_enabled=True)
        probes = [
            ("我在天河区，三口之家", {"district": "越秀区", "household_size": 9}),
            ("非广州户籍，在海珠区有居住证", {"is_local_hukou": True, "residence_proof": False}),
        ]
        for text, conflicting in probes:
            def fake_parse(_request, fields=conflicting):
                return (
                    profile_parser._ProfileExtraction.model_validate(fields),
                    SimpleNamespace(provider="simulated-conflict", model_id="ablation", latency_ms=0, prompt_sha256="0" * 64),
                )
            profile_parser._ollama_parse = fake_parse
            baseline = profile_parser.parse_profile_deterministic(ParseProfileRequest(text=text))
            protected = profile_parser.parse_profile(ParseProfileRequest(text=text))
            protected_conflicts += sum(
                key in baseline.fields and protected.fields.get(key) == baseline.fields.get(key)
                for key in conflicting
            )
    finally:
        profile_parser.settings = original_settings
        profile_parser._ollama_parse = original_ollama_parse
    report["ablations"]["remove_rule_priority_conflict_protection"] = {
        "conflicting_model_fields_protected": protected_conflicts,
        "meaning": "模型与高精度规则冲突时保留规则字段；移除该门会允许冲突值覆盖用户明确事实。",
    }

    question_report_path = ROOT / "data" / "evaluation" / "active_question_report.json"
    if question_report_path.is_file():
        question_report = json.loads(question_report_path.read_text(encoding="utf-8"))
        report["ablations"]["remove_active_questioning"] = {
            "extra_questions_vs_information_gain": round(
                question_report["strategies"]["fixed_order_relevant"]["questions_per_case"]
                - question_report["strategies"]["information_gain"]["mean_questions"],
                3,
            ),
            "status_consistency": question_report["status_consistency"],
            "meaning": "改回固定相关字段顺序会增加的平均问题数；该指标来自合成一致性案例。",
        }

    real_benchmark = ROOT / "data" / "evaluation" / "policy_compiler_real_benchmark.jsonl"
    blocked_candidates = 0
    if real_benchmark.is_file():
        for line in real_benchmark.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            result = compile_policy(
                PolicyCompileRequest(
                    source_id=row["source_id"], title=row["title"], source_text=row["text"],
                    benefit_hint=row["benefit_hint"], effective_from=row.get("effective_from_input"),
                    effective_to=row.get("effective_to_input"), use_llm=False,
                )
            )
            blocked_candidates += not result.publishable
    report["ablations"]["remove_human_publish_gate"] = {
        "candidate_auto_publish_attempts_blocked": blocked_candidates,
        "meaning": "候选规则默认不可发布；移除人工发布门会把这些项目组标注样本暴露给自动发布风险。",
    }

    no_answer_queries = [
        "量子计算卫星轨道参数", "股票明天涨停吗", "世界杯决赛比分", "如何修发动机",
        "写一首情诗", "推荐游戏显卡", "火星天气", "高等数学积分", "公司财报预测", "电影票房排名",
    ]
    refused = sum(not search_evidence_result(query, limit=3)["answerability"]["supported"] for query in no_answer_queries)
    report["ablations"]["remove_no_answer_gate"] = {
        "out_of_scope_queries": len(no_answer_queries),
        "refused_by_full_system": refused,
        "meaning": "无答案门阻止越域问题获得看似相关但无依据的政策引用。",
    }
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        "ABLATION_OK "
        f"cases={len(cases)} forced_binary={forced_binary_decisions} "
        f"temporal_profiles={temporal_snapshot_changes}"
    )
    if full_mismatches:
        raise SystemExit("完整系统与冻结回归集不一致")


if __name__ == "__main__":
    main()
