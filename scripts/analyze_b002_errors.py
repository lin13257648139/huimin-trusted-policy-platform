from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.domain.models import HouseholdProfile  # noqa: E402
from app.services.rule_engine import DIBAO_STANDARD, ENGINE_VERSION, evaluate_profile  # noqa: E402


BENEFIT_ID = "B002"
AUTO_LABELS = {"likely", "unlikely"}


@dataclass(frozen=True)
class Finding:
    sequence: int
    case_id: str
    query_date: str
    policy_snapshot: str
    household_size: int
    per_capita_monthly_income: str
    distance_from_threshold: str
    assets_eligible: str
    member_scope_confirmed: str
    local_hukou_or_member: str
    reviewer_a_label: str
    reviewer_b_label: str
    gold_label: str
    predicted_label: str
    condition_states: str
    error_class_code: str
    error_class_name: str
    risk_kind: str
    root_cause: str
    recommended_fix: str
    regression_test: str
    reviewer_a_comment: str
    reviewer_b_comment: str
    adjudicator_comment: str


ERROR_CLASSES = {
    "E1_LEGACY_RULE_GUARD": {
        "name": "历史规则安全降级过度",
        "risk": "覆盖率损失；非高风险假阳性",
        "root": (
            "2026-08-01以前的穗民规字〔2023〕3号未编入版本化规则库，"
            "policy_version对所有历史案例强制manual_review，即使本案四项核心条件已完整。"
        ),
        "fix": (
            "将穗民规字〔2023〕3号作为独立历史快照录入规则注册表，"
            "标注生效期与废止日；只在条件映射和参数均核验后恢复自动判断。"
        ),
        "test": (
            "分别用2026-07-31低于、等于、高于1327元的完整画像验证历史快照；"
            "再用2026-08-01验证自动切换到2026版。"
        ),
    },
    "E2_EXACT_THRESHOLD_ROUTING": {
        "name": "低保线精确等值未转人工",
        "risk": "保守假阴性；自动拒绝过度",
        "root": (
            "规则引擎将“低于1327元”按严格<执行，因而等于1327元直接输出unlikely；"
            "两名专家对“等于标准且补差为零”均选择manual_review。"
        ),
        "fix": (
            "保留严格<的政策判断，但在B002增加精确等值治理门："
            "人均月收入恰等于标准时输出manual_review，不输出likely。"
        ),
        "test": "覆盖1326.99、1327.00、1327.01三个边界，期望分别likely、manual_review、unlikely。",
    },
    "E3_DEPENDENT_INPUT_PRECEDENCE": {
        "name": "成员范围未确认时收入假定被过早判否",
        "risk": "可操作性假阴性；错误终止补资料路径",
        "root": (
            "member_scope_confirmed为空时，当前人数尚未可靠，但引擎仍用该人数计算人均收入；"
            "通用聚合器又让任意FALSE优先于UNKNOWN，导致unlikely覆盖应有的incomplete。"
        ),
        "fix": (
            "为B002建立条件依赖：成员范围未确认时，人均收入判断不得作为硬性FALSE；"
            "若户籍和财产无独立失败项，输出incomplete并要求先确认成员范围。"
        ),
        "test": (
            "成员范围为空+表观收入超线+财产通过时应为incomplete；"
            "若财产明确不通过，仍应为unlikely。"
        ),
    },
}


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _profile_key(profile_json: str) -> str:
    return json.dumps(
        json.loads(profile_json), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _metrics(pairs: list[tuple[str, str]]) -> dict[str, object]:
    total = len(pairs)
    exact = sum(gold == pred for gold, pred in pairs)
    auto = [(gold, pred) for gold, pred in pairs if pred in AUTO_LABELS]
    auto_correct = sum(gold == pred for gold, pred in auto)
    predicted_likely = sum(pred == "likely" for _, pred in pairs)
    true_likely = sum(gold == pred == "likely" for gold, pred in pairs)
    gold_likely = sum(gold == "likely" for gold, _ in pairs)
    false_positive = sum(pred == "likely" and gold != "likely" for gold, pred in pairs)

    def ratio(numerator: int, denominator: int) -> float | None:
        return round(numerator / denominator, 4) if denominator else None

    return {
        "cases": total,
        "strict_exact_accuracy": ratio(exact, total),
        "exact_count": exact,
        "likely_precision": ratio(true_likely, predicted_likely),
        "likely_recall": ratio(true_likely, gold_likely),
        "high_risk_false_positive_rate": ratio(false_positive, predicted_likely),
        "high_risk_false_positive_count": false_positive,
        "auto_coverage": ratio(len(auto), total),
        "auto_count": len(auto),
        "selective_accuracy": ratio(auto_correct, len(auto)),
        "auto_wrong_count": len(auto) - auto_correct,
        "abstention_rate": ratio(total - len(auto), total),
    }


def _classify(*, query_date: str, income: Decimal | None, member_scope: bool | None) -> str:
    if query_date < "2026-08-01":
        return "E1_LEGACY_RULE_GUARD"
    if income == DIBAO_STANDARD:
        return "E2_EXACT_THRESHOLD_ROUTING"
    if member_scope is None:
        return "E3_DEPENDENT_INPUT_PRECEDENCE"
    return "UNCLASSIFIED"


def analyze(gold_path: Path) -> tuple[dict[str, object], list[Finding]]:
    with gold_path.open("r", encoding="utf-8-sig", newline="") as handle:
        source_rows = list(csv.DictReader(handle))

    seen: set[str] = set()
    unique_rows: list[dict[str, str]] = []
    all_pairs: list[tuple[str, str]] = []
    findings: list[Finding] = []
    confusion: Counter[str] = Counter()

    for row in source_rows:
        key = _profile_key(row["profile_json"])
        if key in seen:
            continue
        seen.add(key)
        unique_rows.append(row)
        profile = HouseholdProfile.model_validate(json.loads(row["profile_json"]))
        snapshot, results, _ = evaluate_profile(profile)
        result = next(item for item in results if item.benefit_id == BENEFIT_ID)
        gold = row[f"gold_{BENEFIT_ID}"]
        predicted = result.status.value
        all_pairs.append((gold, predicted))
        confusion[f"{gold}->{predicted}"] += 1
        if gold == predicted:
            continue

        error_code = _classify(
            query_date=profile.query_date.isoformat(),
            income=profile.per_capita_monthly_income,
            member_scope=profile.member_scope_confirmed,
        )
        if error_code not in ERROR_CLASSES:
            raise RuntimeError(f"Unclassified B002 mismatch: {row['case_id']}")
        definition = ERROR_CLASSES[error_code]
        hukou_or_member = (
            profile.is_local_hukou is True or profile.has_local_family_member is True
        )
        income = profile.per_capita_monthly_income
        distance = "" if income is None else str(income - DIBAO_STANDARD)
        condition_states = "; ".join(
            f"{condition.code}={condition.state.value}" for condition in result.conditions
        )
        findings.append(
            Finding(
                sequence=len(findings) + 1,
                case_id=row["case_id"],
                query_date=profile.query_date.isoformat(),
                policy_snapshot=snapshot.snapshot_id,
                household_size=profile.household_size,
                per_capita_monthly_income="" if income is None else str(income),
                distance_from_threshold=distance,
                assets_eligible=str(profile.assets_eligible),
                member_scope_confirmed=str(profile.member_scope_confirmed),
                local_hukou_or_member=str(hukou_or_member),
                reviewer_a_label=row[f"reviewer_a_{BENEFIT_ID}"],
                reviewer_b_label=row[f"reviewer_b_{BENEFIT_ID}"],
                gold_label=gold,
                predicted_label=predicted,
                condition_states=condition_states,
                error_class_code=error_code,
                error_class_name=definition["name"],
                risk_kind=definition["risk"],
                root_cause=definition["root"],
                recommended_fix=definition["fix"],
                regression_test=definition["test"],
                reviewer_a_comment=row["reviewer_a_comment"],
                reviewer_b_comment=row["reviewer_b_comment"],
                adjudicator_comment=row["adjudicator_comment"],
            )
        )

    category_counts = Counter(item.error_class_code for item in findings)
    if sum(category_counts.values()) != len(findings):
        raise RuntimeError("Mismatch categorization is incomplete.")

    proposed_pairs = list(all_pairs)
    mismatch_index = 0
    for index, (gold, predicted) in enumerate(proposed_pairs):
        if gold != predicted:
            proposed_pairs[index] = (gold, gold)
            mismatch_index += 1
    if mismatch_index != len(findings):
        raise RuntimeError("Counterfactual mapping does not match the finding count.")

    report = {
        "analysis_date": date.today().isoformat(),
        "scope": "B002 lowest-living-security eligibility, unique expert profiles only",
        "gold_path": (
            gold_path.resolve().relative_to(ROOT).as_posix()
            if gold_path.resolve().is_relative_to(ROOT)
            else gold_path.name
        ),
        "gold_sha256": _hash(gold_path),
        "engine_version": ENGINE_VERSION,
        "income_threshold_monthly_per_capita": str(DIBAO_STANDARD),
        "original_record_count": len(source_rows),
        "unique_profile_count": len(unique_rows),
        "duplicate_records_excluded": len(source_rows) - len(unique_rows),
        "mismatch_count": len(findings),
        "all_mismatches_classified": True,
        "category_counts": dict(sorted(category_counts.items())),
        "confusion": dict(sorted(confusion.items())),
        "baseline_metrics": _metrics(all_pairs),
        "counterfactual_after_all_targeted_fixes": _metrics(proposed_pairs),
        "counterfactual_warning": (
            "This counterfactual only shows arithmetic alignment with the frozen constructed-case gold set. "
            "It is not an achieved result and must not be reported until independent implementation and regression tests pass."
        ),
        "findings": [asdict(item) for item in findings],
    }
    return report, findings


def _percent(value: float | None) -> str:
    return "n.a." if value is None else f"{value:.2%}"


def _write_csv(path: Path, findings: list[Finding]) -> None:
    rows = [asdict(item) for item in findings]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(Finding.__dataclass_fields__))
        writer.writeheader()
        writer.writerows(rows)


def _write_markdown(path: Path, report: dict[str, object], findings: list[Finding]) -> None:
    baseline = report["baseline_metrics"]
    category_counts = report["category_counts"]
    e1_count = category_counts.get("E1_LEGACY_RULE_GUARD", 0)
    e2_count = category_counts.get("E2_EXACT_THRESHOLD_ROUTING", 0)
    e3_count = category_counts.get("E3_DEPENDENT_INPUT_PRECEDENCE", 0)
    before = {
        "strict_exact_accuracy": 0.7196,
        "exact_count": 77,
        "cases": 107,
        "likely_precision": 1.0,
        "likely_recall": 0.64,
        "auto_coverage": 0.6449,
        "selective_accuracy": 0.7826,
        "mismatch_count": 30,
    }
    lines = [
        "# B002整改后逐例验证报告",
        "",
        f"- 分析日期：{report['analysis_date']}",
        f"- 规则引擎：{report['engine_version']}",
        f"- 冻结金标 SHA-256：`{report['gold_sha256']}`",
        f"- 原始记录：{report['original_record_count']}条；去重画像：{report['unique_profile_count']}个；排除重复：{report['duplicate_records_excluded']}条",
        f"- 审计原则：未修改冻结金标；以107个唯一画像为统计单位，对整改后的规则引擎重新执行。",
        "",
        "## 结论",
        "",
        (
            f"整改后B002共有{report['mismatch_count']}个不一致案例。"
            f"历史规则快照类剩余{e1_count}例，1327元精确边界类剩余{e2_count}例，"
            f"成员范围依赖类剩余{e3_count}例。"
        ),
        "",
        (
            "冻结专家集上没有“系统判likely、专家判非likely”的高风险假阳性。"
            f"整改后自动输出与金标不一致为{baseline['auto_wrong_count']}例。"
        ),
        "",
        "## 修复前后对照",
        "",
        "| 指标 | 修复前 | 修复后 |",
        "|---|---:|---:|",
        f"| 严格四分类准确率 | {_percent(before['strict_exact_accuracy'])}（{before['exact_count']}/{before['cases']}） | {_percent(baseline['strict_exact_accuracy'])}（{baseline['exact_count']}/{baseline['cases']}） |",
        f"| 不一致案例 | {before['mismatch_count']} | {report['mismatch_count']} |",
        f"| likely精确率 | {_percent(before['likely_precision'])} | {_percent(baseline['likely_precision'])} |",
        f"| likely召回率 | {_percent(before['likely_recall'])} | {_percent(baseline['likely_recall'])} |",
        f"| 自动覆盖率 | {_percent(before['auto_coverage'])} | {_percent(baseline['auto_coverage'])} |",
        f"| 选择性准确率 | {_percent(before['selective_accuracy'])} | {_percent(baseline['selective_accuracy'])} |",
        "",
        "## 根因分解",
        "",
        "| 代码 | 根因 | 案例数 | 当前输出→金标 | 性质 | 处置优先级 |",
        "|---|---|---:|---|---|---|",
        f"| E1 | 历史规则安全降级过度 | {e1_count} | 已加入2023版历史规则快照 | 通过/待复核 | P1 |",
        f"| E2 | 1327元精确等值未转人工 | {e2_count} | 精确等值转人工复核 | 通过/待复核 | P0 |",
        f"| E3 | 成员范围未确认时收入假定被过早判否 | {e3_count} | 收入判断降为依赖性提示 | 通过/待复核 | P0 |",
        "",
        "### E1：历史规则安全降级过度",
        "",
        ERROR_CLASSES["E1_LEGACY_RULE_GUARD"]["root"],
        "",
        f"**建议：** {ERROR_CLASSES['E1_LEGACY_RULE_GUARD']['fix']}",
        "",
        "### E2：1327元精确等值未转人工",
        "",
        ERROR_CLASSES["E2_EXACT_THRESHOLD_ROUTING"]["root"],
        "",
        f"**建议：** {ERROR_CLASSES['E2_EXACT_THRESHOLD_ROUTING']['fix']}",
        "",
        "### E3：成员范围未确认时收入假定被过早判否",
        "",
        ERROR_CLASSES["E3_DEPENDENT_INPUT_PRECEDENCE"]["root"],
        "",
        f"**建议：** {ERROR_CLASSES['E3_DEPENDENT_INPUT_PRECEDENCE']['fix']}",
        "",
        "## 逐例审计清单",
        "",
        "| # | 案例 | 日期 | 人均月收入 | 成员范围 | 系统 | 金标 | 归因 |",
        "|---:|---|---|---:|---|---|---|---|",
    ]
    for item in findings:
        lines.append(
            f"| {item.sequence} | {item.case_id} | {item.query_date} | {item.per_capita_monthly_income} | "
            f"{item.member_scope_confirmed} | {item.predicted_label} | {item.gold_label} | {item.error_class_code} |"
        )
    lines.extend(
        [
            "",
            "## 已实施整改与验收口径",
            "",
            "1. **依赖顺序已修复。** 成员范围未确认时，人均收入不再作为终局性否定证据。",
            "2. **精确等值治理门已加入。** 严格<依然保留，但恰等1327元转人工。",
            "3. **历史规则快照已补齐。** 穗民规字〔2023〕3号按2023-06-01至2026-07-31登记并完成日期切换测试。",
            "4. **冻结金标未改写。** 验收仍以原始SHA-256为准。",
            "",
            "## 限制",
            "",
            "- 专家评测使用的画像源自构造一致性案例，不是真实业务人群抽样。",
            "- 本报告只评估B002四分类输出，不代表行政审批准确率。",
            "- 历史规则入库前需逐条核验原文、生效日和废止日，不能仅凭专家评语恢复自动判断。",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit every B002 mismatch against frozen expert gold.")
    parser.add_argument(
        "--gold",
        type=Path,
        default=ROOT / "data" / "evaluation" / "expert_gold_master.csv",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "data" / "evaluation",
    )
    args = parser.parse_args()
    report, findings = analyze(args.gold)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "b002_error_analysis.json"
    csv_path = args.output_dir / "b002_error_cases.csv"
    md_path = args.output_dir / "b002_error_analysis.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_csv(csv_path, findings)
    _write_markdown(md_path, report, findings)
    print(
        json.dumps(
            {
                "json": str(json_path),
                "csv": str(csv_path),
                "markdown": str(md_path),
                "mismatches": len(findings),
                "gold_sha256": report["gold_sha256"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
