from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.catalog import load_evidence  # noqa: E402
from app.services.retrieval import search_evidence  # noqa: E402


def evaluate(path: Path) -> dict[str, object]:
    benchmark = json.loads(path.read_text(encoding="utf-8"))
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
        "recall_at_1": round(hits[1] / total, 4),
        "recall_at_3": round(hits[3] / total, 4),
        "recall_at_5": round(hits[5] / total, 4),
        "mrr_at_5": round(reciprocal_rank / total, 4),
        "details": details,
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
    args = parser.parse_args()
    report = evaluate(args.benchmark)
    content = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(content, encoding="utf-8")
    print(content)


if __name__ == "__main__":
    main()
