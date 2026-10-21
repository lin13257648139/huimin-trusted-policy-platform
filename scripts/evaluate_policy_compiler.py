from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import UTC, date, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.domain.models import PolicyCompileRequest  # noqa: E402
from app.services.ai_runtime import ollama_runtime_status  # noqa: E402
from app.services.policy_compiler import compile_policy  # noqa: E402
from app.version import APP_VERSION  # noqa: E402
from scripts.evaluation_stats import (  # noqa: E402
    f1_metrics,
    latency_summary,
    rate_metric,
)

TRACKS = ("deterministic", "llm_only", "controlled_fusion")
NEGATIVE_TOPICS = (
    "会议室设备维护和办公用品采购流程",
    "机房交换机季度巡检与维修登记",
    "年度档案目录整理和移交办法",
    "公共体育场馆开放秩序公告",
    "城市道路施工期间交通绕行通告",
    "软件采购安装测试和资产验收规则",
    "公园绿化浇灌修剪作业规范",
    "办公室照明空调节能倡议",
    "培训会议签到和学习记录安排",
    "公共图书借阅续借管理规则",
    "社区垃圾分类投放指引",
    "电梯年度检验与故障维修制度",
    "学校运动会报名和赛程安排",
    "网络账户密码定期更换提示",
    "停车场车辆进出收费说明",
    "食堂食品采购留样管理制度",
    "快递包裹收发登记流程",
    "博物馆参观预约和讲解安排",
    "公共自行车维护保养计划",
    "河道水质监测采样技术规范",
    "办公电脑报废处置操作规程",
    "城市路灯巡查维修工作方案",
    "志愿服务活动排班通知",
    "小区消防通道日常检查制度",
    "视频会议系统使用说明",
    "园林苗木采购质量验收标准",
    "公共厕所保洁考核办法",
    "社区文艺演出节目征集通知",
    "机关车辆加油维修管理办法",
    "仓库物资盘点和领用流程",
)


def _date_visible_in_text(value: str | None, text: str) -> bool:
    if not value:
        return False
    parsed = date.fromisoformat(value)
    variants = {
        value,
        f"{parsed.year}年{parsed.month}月{parsed.day}日",
        f"{parsed.year}年{parsed.month:02d}月{parsed.day:02d}日",
    }
    return any(item in text for item in variants)


def _normalize_parameter_pairs(values: dict[str, object]) -> set[tuple[str, str]]:
    return {(key, str(value)) for key, value in values.items()}


def _evaluate_rejection(strategy: str) -> dict[str, Any]:
    details = []
    latencies = []
    for index, topic in enumerate(NEGATIVE_TOPICS, start=1):
        started = perf_counter()
        result = compile_policy(
            PolicyCompileRequest(
                source_id=f"NEG-{index:03d}",
                title="一般行政材料工作说明",
                source_text=f"本文件规定{topic}。各部门应按要求完成登记并接受检查。",
                extraction_strategy=strategy,
                use_llm=strategy != "deterministic",
            )
        )
        latencies.append((perf_counter() - started) * 1000)
        passed = result.candidate.benefit_id == "unknown" and not result.publishable
        details.append(
            {
                "case_id": f"NEG-{index:03d}",
                "passed": passed,
                "predicted_benefit_id": result.candidate.benefit_id,
                "provider": result.candidate.provider,
            }
        )
    passed = sum(bool(item["passed"]) for item in details)
    return {
        "cases": len(details),
        "accuracy": round(passed / len(details), 4),
        "accuracy_ci95": rate_metric(passed, len(details))["ci95"],
        "latency_ms": latency_summary(latencies),
        "error_table": [item for item in details if not item["passed"]],
    }


def _evaluate_track(rows: list[dict[str, Any]], strategy: str) -> dict[str, Any]:
    benefit_correct = benefit_total = 0
    start_correct = start_total = 0
    end_correct = end_total = 0
    parameter_counts: Counter[str] = Counter()
    condition_counts: Counter[str] = Counter()
    grounded_quotes = total_quotes = 0
    providers: Counter[str] = Counter()
    total_latencies: list[float] = []
    model_latencies: list[float] = []
    errors: list[dict[str, Any]] = []
    runtime_fallback_cases: list[str] = []
    by_source: dict[str, Counter[str]] = defaultdict(Counter)

    for row in rows:
        expected = row["expected"]
        if not isinstance(expected, dict):
            raise TypeError("expected must be an object")
        started = perf_counter()
        result = compile_policy(
            PolicyCompileRequest(
                source_id=str(row["source_id"]),
                title=str(row["title"]),
                source_text=str(row["text"]),
                extraction_strategy=strategy,
                use_llm=strategy != "deterministic",
            )
        )
        total_latencies.append((perf_counter() - started) * 1000)
        candidate = result.candidate
        if candidate.model_latency_ms is not None:
            model_latencies.append(float(candidate.model_latency_ms))
        providers[candidate.provider] += 1
        if strategy != "deterministic" and not (
            candidate.provider.startswith("ollama/") or "+ollama/" in candidate.provider
        ):
            runtime_fallback_cases.append(str(row["case_id"]))
        text = str(row["text"])
        source_id = str(row["source_id"])
        source_bucket = by_source[source_id]
        source_bucket["cases"] += 1

        benefit_evaluable = bool(row.get("unassisted_benefit_evaluable", True))
        benefit_match: bool | None = None
        if benefit_evaluable:
            benefit_total += 1
            benefit_match = candidate.benefit_id == expected["benefit_id"]
            benefit_correct += int(benefit_match)
            source_bucket["benefit_total"] += 1
            source_bucket["benefit_correct"] += int(benefit_match)

        actual_start = candidate.effective_from.isoformat() if candidate.effective_from else None
        actual_end = candidate.effective_to.isoformat() if candidate.effective_to else None
        expected_start = expected.get("effective_from")
        expected_end = expected.get("effective_to")
        start_match: bool | None = None
        end_match: bool | None = None
        if _date_visible_in_text(expected_start, text):
            start_total += 1
            start_match = actual_start == expected_start
            start_correct += int(start_match)
        if _date_visible_in_text(expected_end, text):
            end_total += 1
            end_match = actual_end == expected_end
            end_correct += int(end_match)

        predicted_parameters = _normalize_parameter_pairs(candidate.parameters)
        gold_parameters = _normalize_parameter_pairs(expected["parameters"])
        parameter_counts["tp"] += len(predicted_parameters & gold_parameters)
        parameter_counts["predicted"] += len(predicted_parameters)
        parameter_counts["gold"] += len(gold_parameters)
        predicted_fields = {item.field for item in candidate.conditions}
        gold_fields = set(expected["condition_fields"])
        condition_counts["tp"] += len(predicted_fields & gold_fields)
        condition_counts["predicted"] += len(predicted_fields)
        condition_counts["gold"] += len(gold_fields)
        quote_matches = [item.source_quote in text for item in candidate.conditions]
        grounded_quotes += sum(quote_matches)
        total_quotes += len(quote_matches)

        wrong = []
        if benefit_match is False:
            wrong.append("benefit_id")
        if start_match is False:
            wrong.append("effective_from")
        if end_match is False:
            wrong.append("effective_to")
        if predicted_parameters != gold_parameters:
            wrong.append("parameters")
        if predicted_fields != gold_fields:
            wrong.append("condition_fields")
        if not all(quote_matches):
            wrong.append("source_quote")
        if wrong:
            errors.append(
                {
                    "case_id": row["case_id"],
                    "source_id": source_id,
                    "locator": row.get("locator"),
                    "wrong_dimensions": wrong,
                    "expected_benefit_id": expected["benefit_id"],
                    "predicted_benefit_id": candidate.benefit_id,
                    "expected_parameters": expected["parameters"],
                    "predicted_parameters": candidate.parameters,
                    "expected_condition_fields": sorted(gold_fields),
                    "predicted_condition_fields": sorted(predicted_fields),
                }
            )

    return {
        "strategy": strategy,
        "metadata_assistance_used": False,
        "case_count": len(rows),
        "providers": dict(providers),
        "benefit_accuracy": round(benefit_correct / benefit_total, 4) if benefit_total else None,
        "benefit_accuracy_ci95": rate_metric(benefit_correct, benefit_total)["ci95"],
        "benefit_evaluable_cases": benefit_total,
        "benefit_context_dependent_cases": len(rows) - benefit_total,
        "effective_from_accuracy": round(start_correct / start_total, 4) if start_total else None,
        "effective_from_accuracy_ci95": rate_metric(start_correct, start_total)["ci95"],
        "effective_from_evaluable_cases": start_total,
        "effective_to_accuracy": round(end_correct / end_total, 4) if end_total else None,
        "effective_to_accuracy_ci95": rate_metric(end_correct, end_total)["ci95"],
        "effective_to_evaluable_cases": end_total,
        "parameter_pair": f1_metrics(
            parameter_counts["tp"], parameter_counts["predicted"], parameter_counts["gold"]
        ),
        "condition_field": f1_metrics(
            condition_counts["tp"], condition_counts["predicted"], condition_counts["gold"]
        ),
        "source_quote_grounding": rate_metric(grounded_quotes, total_quotes),
        "end_to_end_latency_ms": latency_summary(total_latencies),
        "model_latency_ms": latency_summary(model_latencies),
        "unknown_rejection": _evaluate_rejection(strategy),
        "runtime_fallback_cases": runtime_fallback_cases,
        "by_source": {
            source_id: {
                "cases": counts["cases"],
                "benefit_accuracy": rate_metric(counts["benefit_correct"], counts["benefit_total"]),
            }
            for source_id, counts in sorted(by_source.items())
        },
        "error_table": errors,
    }


def evaluate(
    path: Path,
    *,
    split: str | None,
    tracks: tuple[str, ...],
    require_live_llm: bool,
) -> dict[str, Any]:
    all_rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    rows = [row for row in all_rows if split is None or row.get("split") == split]
    if not rows:
        raise RuntimeError(f"数据集中没有split={split!r}的案例")
    development_sources = {
        str(row["source_id"]) for row in all_rows if row.get("split") == "development"
    }
    final_sources = {
        str(row["source_id"]) for row in all_rows if row.get("split") == "frozen_final_test"
    }
    overlap = sorted(development_sources & final_sources)
    if overlap:
        raise RuntimeError(f"政策文件分组泄漏：{overlap}")
    runtime = ollama_runtime_status()
    if require_live_llm and (not runtime["reachable"] or not runtime.get("model_present")):
        raise RuntimeError(f"要求真实LLM但运行时不可用：{runtime['reason']}")
    track_reports = {strategy: _evaluate_track(rows, strategy) for strategy in tracks}
    if require_live_llm:
        for strategy in tracks:
            if strategy == "deterministic":
                continue
            providers = track_reports[strategy]["providers"]
            live_cases = sum(
                int(count)
                for provider, count in providers.items()
                if str(provider).startswith("ollama/") or "+ollama/" in str(provider)
            )
            if live_cases != len(rows):
                fallback_cases = track_reports[strategy]["runtime_fallback_cases"]
                raise RuntimeError(
                    f"{strategy}真实LLM调用不完整：{live_cases}/{len(rows)}；"
                    f"降级案例={fallback_cases}"
                )
    return {
        "report_schema": "policy2rule-three-track/3.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "app_version": APP_VERSION,
        "dataset": path.relative_to(ROOT).as_posix(),
        "dataset_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "evaluated_split": split or "all",
        "case_count": len(rows),
        "dataset_origin": "official verbatim clauses with project-authored labels",
        "policy_file_isolation": {
            "development_source_ids": sorted(development_sources),
            "frozen_final_source_ids": sorted(final_sources),
            "overlap": overlap,
            "passed": not overlap,
        },
        "ai_runtime": runtime,
        "tracks": track_reports,
        "claim_boundary": [
            "三轨均只接收政策原文，不使用benefit_hint或生效日期元数据回填。",
            "最终测试按完整政策文件隔离，同一source_id不得跨开发集与冻结测试集。",
            "标签由项目组按公开标注指南制作，尚不是外部专家双人盲标。",
            "指标及95%置信区间只描述本冻结集，不外推为真实政务业务准确率。",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="评测Policy2Rule三轨候选编译器。")
    parser.add_argument(
        "--benchmark",
        type=Path,
        default=ROOT / "data" / "evaluation" / "policy_compiler_benchmark.jsonl",
    )
    parser.add_argument("--split", default=None)
    parser.add_argument(
        "--tracks",
        default="deterministic",
        help="deterministic、llm_only、controlled_fusion或all",
    )
    parser.add_argument("--require-live-llm", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    tracks = TRACKS if args.tracks == "all" else tuple(args.tracks.split(","))
    if not tracks or any(track not in TRACKS for track in tracks):
        raise SystemExit(f"tracks必须来自{TRACKS}或all")
    report = evaluate(
        args.benchmark.resolve(),
        split=args.split,
        tracks=tracks,
        require_live_llm=args.require_live_llm,
    )
    content = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.resolve().write_text(content + "\n", encoding="utf-8")
    print(
        "POLICY2RULE_EVAL_OK "
        f"split={report['evaluated_split']} cases={report['case_count']} "
        f"tracks={','.join(tracks)}"
    )
    if not args.output:
        print(content)


if __name__ == "__main__":
    main()
