from __future__ import annotations

import hashlib
import json
import platform
import statistics
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import settings
from app.domain.models import ParseProfileRequest
from app.services.ai_runtime import ollama_runtime_status
from app.services.intent_classifier import DATASET_PATH, classify_intent
from app.services.profile_parser import parse_profile, parse_profile_deterministic
from app.services.retrieval import search_evidence, search_evidence_result
from app.version import APP_VERSION


PROFILE_DATASET = ROOT / "data" / "evaluation" / "profile_extraction_benchmark.jsonl"
RETRIEVAL_DATASET = ROOT / "data" / "evaluation" / "retrieval_benchmark.json"
OUTPUT = ROOT / "data" / "evaluation" / "ai_pipeline_report.json"
SYSTEM_FIELDS = {"query_date", "city"}


def _intent_metrics(pairs: list[tuple[str, str]]) -> dict[str, Any]:
    labels = sorted({gold for gold, _ in pairs})
    correct = sum(gold == predicted for gold, predicted in pairs)
    per_label: dict[str, dict[str, float]] = {}
    f1_values = []
    for label in labels:
        tp = sum(gold == label and predicted == label for gold, predicted in pairs)
        fp = sum(gold != label and predicted == label for gold, predicted in pairs)
        fn = sum(gold == label and predicted != label for gold, predicted in pairs)
        precision = tp / max(tp + fp, 1)
        recall = tp / max(tp + fn, 1)
        f1 = 2 * precision * recall / max(precision + recall, 1e-12)
        f1_values.append(f1)
        per_label[label] = {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
        }
    return {
        "cases": len(pairs),
        "accuracy": round(correct / max(len(pairs), 1), 4),
        "macro_f1": round(sum(f1_values) / max(len(f1_values), 1), 4),
        "per_label": per_label,
    }


def _evaluate_intent() -> dict[str, Any]:
    payload = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    keyword_map = {
        "B001": ("低收入人口", "监测", "困难人口登记"),
        "B002": ("低保", "最低生活保障"),
        "B003": ("低保边缘", "超过低保线", "衔接救助"),
        "B004": ("刚性支出", "住院", "医疗", "学费", "大病"),
        "B005": ("临时救助", "火灾", "事故", "意外", "急难"),
    }
    nb_pairs: list[tuple[str, str]] = []
    keyword_pairs: list[tuple[str, str]] = []
    for label, group in payload["labels"].items():
        for text in group["test"]:
            _, predictions = classify_intent(text, limit=1)
            nb_pairs.append((label, predictions[0]["benefit_id"] if predictions else "abstain"))
            scores = {
                candidate: sum(term in text for term in terms)
                for candidate, terms in keyword_map.items()
            }
            best = max(scores, key=scores.get)
            keyword_pairs.append((label, best if scores[best] else "abstain"))
    model_version, _ = classify_intent("低保申请", limit=1)
    return {
        "dataset": DATASET_PATH.relative_to(ROOT).as_posix(),
        "dataset_sha256": _sha256(DATASET_PATH),
        "origin": payload["origin"],
        "keyword_baseline": _intent_metrics(keyword_pairs),
        "char_ngram_naive_bayes": {
            "model_version": model_version,
            **_intent_metrics(nb_pairs),
            "role": "只排序可能关注事项，不参与资格结论",
            "score_note": "归一化排序分数，未做概率校准",
        },
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _normal(value: object) -> object:
    if isinstance(value, float):
        return f"{value:.2f}"
    return value


def _percentile(values: list[int], fraction: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = round((len(ordered) - 1) * fraction)
    return ordered[index]


def _evaluate_profile_method(
    cases: list[dict[str, Any]],
    parser: Callable[[ParseProfileRequest], Any],
) -> dict[str, Any]:
    true_positive = false_positive = false_negative = 0
    exact_cases = 0
    hallucination_cases: list[str] = []
    by_category: dict[str, Counter[str]] = defaultdict(Counter)
    modes: Counter[str] = Counter()
    latencies: list[int] = []
    fallbacks: Counter[str] = Counter()
    for item in cases:
        result = parser(
            ParseProfileRequest(text=item["text"], query_date=date(2026, 9, 30))
        )
        modes[result.mode] += 1
        if result.latency_ms is not None:
            latencies.append(result.latency_ms)
        if result.fallback_used:
            fallbacks[result.fallback_reason or "unspecified"] += 1
        expected = {key: _normal(value) for key, value in item["expected_fields"].items()}
        predicted = {
            key: _normal(value)
            for key, value in result.fields.items()
            if key not in SYSTEM_FIELDS
        }
        matched = {key for key, value in expected.items() if predicted.get(key) == value}
        wrong_or_extra = {
            key for key, value in predicted.items() if key not in expected or expected.get(key) != value
        }
        missed = set(expected) - matched
        true_positive += len(matched)
        false_positive += len(wrong_or_extra)
        false_negative += len(missed)
        exact_cases += predicted == expected
        if wrong_or_extra:
            hallucination_cases.append(item["case_id"])
        bucket = by_category[item["category"]]
        bucket["cases"] += 1
        bucket["exact"] += predicted == expected
    precision = true_positive / max(true_positive + false_positive, 1)
    recall = true_positive / max(true_positive + false_negative, 1)
    return {
        "cases": len(cases),
        "field_precision": round(precision, 4),
        "field_recall": round(recall, 4),
        "field_f1": round(2 * precision * recall / max(precision + recall, 1e-12), 4),
        "case_exact_match": round(exact_cases / max(len(cases), 1), 4),
        "hallucination_case_rate": round(len(hallucination_cases) / max(len(cases), 1), 4),
        "hallucination_case_ids": hallucination_cases,
        "routes": dict(modes),
        "latency_ms": {
            "measured_cases": len(latencies),
            "mean": round(statistics.fmean(latencies), 1) if latencies else None,
            "p50": _percentile(latencies, 0.50),
            "p95": _percentile(latencies, 0.95),
            "max": max(latencies) if latencies else None,
            "includes_model_cold_start": True if latencies else None,
        },
        "fallbacks": {"count": sum(fallbacks.values()), "reasons": dict(fallbacks)},
        "by_category": {
            key: {"cases": value["cases"], "exact_match": round(value["exact"] / value["cases"], 4)}
            for key, value in sorted(by_category.items())
        },
    }


def _evaluate_retrieval(benchmark: list[dict[str, Any]], hybrid: bool) -> dict[str, Any]:
    ranks: list[int | None] = []
    actual_routes: Counter[str] = Counter()
    latencies: list[int] = []
    for item in benchmark:
        if hybrid:
            result = search_evidence_result(item["query"], limit=5)
            results = result["items"]
            actual_routes[result["retriever"]["name"]] += 1
            latency = result["retriever"].get("latency_ms")
            if isinstance(latency, int):
                latencies.append(latency)
        else:
            results = search_evidence(item["query"], limit=5)
            actual_routes["field-weighted-bm25"] += 1
        ids = [row["evidence"]["evidence_id"] for row in results]
        expected = set(item.get("relevant_evidence_ids", item.get("relevant_ids", [])))
        rank = next((index for index, value in enumerate(ids, start=1) if value in expected), None)
        ranks.append(rank)
    return {
        "queries": len(ranks),
        "recall_at_1": round(sum(rank == 1 for rank in ranks) / max(len(ranks), 1), 4),
        "recall_at_3": round(sum(rank is not None and rank <= 3 for rank in ranks) / max(len(ranks), 1), 4),
        "mrr_at_5": round(sum(1 / rank if rank else 0 for rank in ranks) / max(len(ranks), 1), 4),
        "actual_routes": dict(actual_routes),
        "latency_ms": {
            "measured_queries": len(latencies),
            "mean": round(statistics.fmean(latencies), 1) if latencies else None,
            "p50": _percentile(latencies, 0.50),
            "p95": _percentile(latencies, 0.95),
            "max": max(latencies) if latencies else None,
        },
    }


def main() -> None:
    if not PROFILE_DATASET.is_file():
        raise SystemExit("缺少画像抽取基准，请先运行 scripts/generate_ai_benchmark.py")
    profile_cases = [
        json.loads(line) for line in PROFILE_DATASET.read_text(encoding="utf-8").splitlines() if line
    ]
    retrieval_cases = json.loads(RETRIEVAL_DATASET.read_text(encoding="utf-8"))
    if isinstance(retrieval_cases, dict):
        retrieval_cases = retrieval_cases.get("queries", retrieval_cases.get("cases", []))
    runtime = ollama_runtime_status()
    deterministic = _evaluate_profile_method(profile_cases, parse_profile_deterministic)
    report: dict[str, Any] = {
        "report_schema": "ai-experiment/1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "internal synthetic benchmark; not real-user effectiveness evidence",
        "app_version": APP_VERSION,
        "environment": {
            "python": platform.python_version(),
            "platform": platform.system(),
            "architecture": platform.machine(),
            "executable_path_stored": False,
        },
        "datasets": {
            "profile": {
                "path": PROFILE_DATASET.relative_to(ROOT).as_posix(),
                "sha256": _sha256(PROFILE_DATASET),
                "cases": len(profile_cases),
                "origin": "team-authored synthetic utterances",
            },
            "retrieval": {
                "path": RETRIEVAL_DATASET.relative_to(ROOT).as_posix(),
                "sha256": _sha256(RETRIEVAL_DATASET),
                "queries": len(retrieval_cases),
                "origin": "internal policy retrieval questions",
            },
        },
        "ai_runtime": runtime,
        "intent_classification": _evaluate_intent(),
        "profile_extraction": {"deterministic_baseline": deterministic},
        "retrieval": {
            "bm25_baseline": _evaluate_retrieval(retrieval_cases, hybrid=False),
            "configured_pipeline": _evaluate_retrieval(retrieval_cases, hybrid=True),
        },
        "claim_boundary": [
            "画像基准是内部合成语句，不代表真实困难群众表达分布。",
            "模型未实际运行时不得引用模型指标；报告中的actual_routes是唯一准确信号。",
            "最终资格始终由时态规则与三值逻辑求值，模型输出仅为待确认候选字段。",
        ],
    }
    if runtime["reachable"] and runtime.get("model_present"):
        assisted = _evaluate_profile_method(profile_cases, parse_profile)
        if assisted["routes"].get("llm_assisted") == len(profile_cases):
            report["profile_extraction"]["schema_constrained_llm_ensemble"] = assisted
        else:
            report["profile_extraction"]["schema_constrained_llm_ensemble"] = {
                "status": "invalid_run",
                "reason": "部分案例发生安全降级，不能作为完整模型实验",
                "observed": assisted,
            }
    else:
        report["profile_extraction"]["schema_constrained_llm_ensemble"] = {
            "status": "not_run",
            "reason": runtime["reason"],
        }
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        "AI_EVAL_OK "
        f"profile_cases={len(profile_cases)} retrieval_queries={len(retrieval_cases)} "
        f"llm_status={report['profile_extraction']['schema_constrained_llm_ensemble'].get('status', 'completed')}"
    )


if __name__ == "__main__":
    main()
