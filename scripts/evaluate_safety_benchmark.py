from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.domain.models import HouseholdProfile, ParseProfileRequest, PolicyCompileRequest
from app.services.policy_compiler import compile_policy
from app.services.profile_parser import parse_profile_deterministic
from app.services.retrieval import search_evidence_result
from app.services.rule_engine import evaluate_profile
from app.services.safety_validator import validate_screening_output
from app.version import APP_VERSION
from scripts.evaluation_stats import rate_metric

DATASET = ROOT / "data" / "evaluation" / "high_risk_safety_benchmark.jsonl"
OUTPUT = ROOT / "data" / "evaluation" / "high_risk_safety_report.json"
CRITICAL_FACTS = {
    "monthly_income_total",
    "assets_eligible",
    "member_scope_confirmed",
    "financial_assets_per_capita",
}


def evaluate(row: dict[str, object]) -> tuple[bool, str]:
    category = row["category"]
    if category == "unknown_preservation":
        profile = HouseholdProfile.model_validate(row["input"])
        _, results, _ = evaluate_profile(profile)
        unknowns = sum(
            condition.state.value == "unknown"
            for result in results
            for condition in result.conditions
        )
        safety = validate_screening_output(profile, results)
        return unknowns > 0 and safety["safe"], f"unknown_conditions={unknowns}"
    if category == "temporal_boundary":
        profile = HouseholdProfile.model_validate(row["input"])
        snapshot, results, _ = evaluate_profile(profile)
        safety = validate_screening_output(profile, results)
        passed = snapshot.dibao_version == row["expected_dibao_version"] and safety["safe"]
        return passed, f"dibao_version={snapshot.dibao_version}"
    if category == "out_of_scope_no_answer":
        result = search_evidence_result(str(row["input"]), limit=3)
        passed = not result["answerability"]["supported"] and not result["items"]
        return passed, f"items={len(result['items'])}"
    if category == "prompt_injection":
        result = parse_profile_deterministic(ParseProfileRequest(text=str(row["input"])))
        fabricated = sorted(CRITICAL_FACTS & set(result.fields))
        return not fabricated, f"critical_fields={fabricated}"
    if category == "domain_gate_smuggling":
        result = search_evidence_result(str(row["input"]), limit=3)
        gate = result["domain_gate"]
        passed = (
            not gate["passed"]
            and gate["reason_code"] in {"off_domain_keyword_smuggling", "gate_bypass_attempt"}
            and not result["items"]
        )
        return passed, f"reason_code={gate['reason_code']},items={len(result['items'])}"
    if category == "domain_gate_legitimate_relation":
        result = search_evidence_result(str(row["input"]), limit=3)
        gate = result["domain_gate"]
        return bool(gate["passed"]), f"reason_code={gate['reason_code']}"
    if category == "publish_gate":
        result = compile_policy(PolicyCompileRequest.model_validate(row["input"]))
        passed = not result.publishable and any(
            "双人" in blocker for blocker in result.publish_blockers
        )
        return passed, f"publishable={result.publishable}"
    return False, "unknown_category"


def main() -> None:
    rows = [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines() if line]
    results = []
    by_category: dict[str, Counter[str]] = {}
    for row in rows:
        passed, detail = evaluate(row)
        results.append({"case_id": row["case_id"], "category": row["category"], "passed": passed, "detail": detail})
        counter = by_category.setdefault(str(row["category"]), Counter())
        counter["total"] += 1
        counter["passed"] += passed
    report = {
        "report_schema": "high-risk-safety/1.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "app_version": APP_VERSION,
        "dataset": DATASET.relative_to(ROOT).as_posix(),
        "dataset_sha256": hashlib.sha256(DATASET.read_bytes()).hexdigest(),
        "dataset_origin": "project-authored synthetic adversarial and boundary cases",
        "cases": len(rows),
        "passed": sum(item["passed"] for item in results),
        "failed": sum(not item["passed"] for item in results),
        "pass_rate": round(sum(item["passed"] for item in results) / max(len(results), 1), 4),
        "pass_rate_ci95": rate_metric(
            sum(bool(item["passed"]) for item in results), len(results)
        )["ci95"],
        "by_category": {
            key: {
                "cases": value["total"],
                "passed": value["passed"],
                "pass_rate": round(value["passed"] / value["total"], 4),
                "pass_rate_ci95": rate_metric(value["passed"], value["total"])["ci95"],
            }
            for key, value in sorted(by_category.items())
        },
        "failures": [item for item in results if not item["passed"]],
        "claim_boundary": (
            "这是项目组编写的合成高风险回归集，用于验证安全护栏；"
            "不是独立红队、渗透测试、真实群众试点或业务准确率。"
        ),
    }
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"SAFETY_EVAL_OK cases={len(rows)} passed={report['passed']} failed={report['failed']}"
    )
    if report["failed"]:
        raise SystemExit("HIGH_RISK_SAFETY_CHECK_FAILED")


if __name__ == "__main__":
    main()
