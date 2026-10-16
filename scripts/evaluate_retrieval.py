from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.catalog import load_evidence  # noqa: E402
from app.services.retrieval import search_evidence  # noqa: E402
from scripts.evaluation_stats import rate_metric  # noqa: E402


def evaluate(path: Path, split: str | None = "frozen_final_test") -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    benchmark = payload.get("queries", payload.get("cases", [])) if isinstance(payload, dict) else payload
    if split and any("split" in item for item in benchmark):
        benchmark = [item for item in benchmark if item.get("split") == split]
    hits = {1: 0, 3: 0, 5: 0}
    reciprocal_rank = 0.0
    details = []
    for item in benchmark:
        results = search_evidence(item["query"], limit=5)
        ranked = [result["evidence"]["evidence_id"] for result in results]
        relevant = set(item["relevant_ids"])
        first_rank = next((index for index, value in enumerate(ranked, 1) if value in relevant), None)
        if first_rank:
            reciprocal_rank += 1 / first_rank
        for k in hits:
            hits[k] += int(bool(relevant & set(ranked[:k])))
        details.append(
            {
                "query_id": item.get("query_id"),
                "source_id": item.get("source_id"),
                "query": item["query"],
                "relevant_ids": item["relevant_ids"],
                "ranked_ids": ranked,
                "first_relevant_rank": first_rank,
            }
        )
    total = len(benchmark)
    return {
        "benchmark_role": "internally_curated_retrieval_benchmark",
        "query_count": total,
        "evaluated_split": split or "all",
        "recall_at_1": round(hits[1] / total, 4),
        "recall_at_1_ci95": rate_metric(hits[1], total)["ci95"],
        "recall_at_3": round(hits[3] / total, 4),
        "recall_at_3_ci95": rate_metric(hits[3], total)["ci95"],
        "recall_at_5": round(hits[5] / total, 4),
        "recall_at_5_ci95": rate_metric(hits[5], total)["ci95"],
        "mrr_at_5": round(reciprocal_rank / total, 4),
        "details": details,
        "error_table": [
            item
            for item in details
            if item["first_relevant_rank"] is None or item["first_relevant_rank"] > 3
        ],
        "policy_file_isolation": (
            payload.get("policy_file_isolation") if isinstance(payload, dict) else None
        ),
        "warning": (
            f"该结果只评价当前{len(load_evidence())}条证据片段的检索，"
            "不等于业务资格判断准确率。"
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="评测政策证据检索Recall@K与MRR。")
    parser.add_argument(
        "--benchmark",
        type=Path,
        default=ROOT / "data" / "evaluation" / "retrieval_benchmark.json",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--split", default="frozen_final_test")
    args = parser.parse_args()
    report = evaluate(args.benchmark.resolve(), split=args.split or None)
    content = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.resolve().write_text(content, encoding="utf-8")
    print(content)


if __name__ == "__main__":
    main()
