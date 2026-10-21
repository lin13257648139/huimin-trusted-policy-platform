from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from app.domain.models import PolicyQuestionRequest  # noqa: E402
from app.services import policy_qa  # noqa: E402
from scripts.evaluation_stats import rate_metric  # noqa: E402


def evaluate(
    benchmark_path: Path,
    *,
    split: str = "frozen_final_test",
    live_model: bool = False,
    limit: int | None = None,
) -> dict[str, Any]:
    payload = json.loads(benchmark_path.read_text(encoding="utf-8"))
    cases = payload.get("queries", payload.get("cases", []))
    cases = [item for item in cases if item.get("split") == split]
    if limit is not None:
        cases = cases[:limit]

    original_settings = policy_qa.settings
    policy_qa.settings = SimpleNamespace(
        policy_as_of=settings.policy_as_of,
        ollama_enabled=live_model,
    )
    details = []
    generation_modes: Counter[str] = Counter()
    try:
        for item in cases:
            response = policy_qa.answer_policy_question(
                PolicyQuestionRequest(
                    question=item["query"],
                    max_evidence=5,
                )
            )
            cited = sorted(
                {evidence_id for claim in response.claims for evidence_id in claim.evidence_ids}
            )
            available = {evidence.evidence_id for evidence in response.evidence}
            relevant = set(item["relevant_ids"])
            citation_valid = set(cited) <= available
            relevant_cited = bool(relevant & set(cited))
            quote_verified = all(evidence.quote_verified for evidence in response.evidence)
            generation_mode = str(response.generation.get("mode", "unknown"))
            generation_modes[generation_mode] += 1
            evidence_by_id = {item.evidence_id: item for item in response.evidence}
            claim_grounding_scores = []
            unsupported_numbers: set[str] = set()
            unsafe_decision_claims = []
            for claim in response.claims:
                source_text = " ".join(
                    " ".join(
                        filter(
                            None,
                            (
                                evidence_by_id[evidence_id].verbatim_quote,
                                evidence_by_id[evidence_id].excerpt,
                                evidence_by_id[evidence_id].plain_language_explanation,
                            ),
                        )
                    )
                    for evidence_id in claim.evidence_ids
                    if evidence_id in evidence_by_id
                )
                claim_grounding_scores.append(
                    policy_qa._lexical_grounding_coverage(claim.text, source_text)
                )
                unsupported_numbers.update(
                    set(re.findall(r"\d+(?:\.\d+)?%?", claim.text))
                    - set(re.findall(r"\d+(?:\.\d+)?%?", item["query"] + " " + source_text))
                )
                if policy_qa._UNSAFE_DECISION.search(claim.text):
                    unsafe_decision_claims.append(claim.text)
            claim_grounding_valid = all(score >= 0.35 for score in claim_grounding_scores)
            details.append(
                {
                    "query_id": item.get("query_id"),
                    "source_id": item.get("source_id"),
                    "status": response.status,
                    "relevant_ids": sorted(relevant),
                    "cited_ids": cited,
                    "relevant_cited": relevant_cited,
                    "citation_allowlist_valid": citation_valid,
                    "all_quotes_verified": quote_verified,
                    "claim_count": len(response.claims),
                    "claim_grounding_scores": [round(score, 4) for score in claim_grounding_scores],
                    "claim_grounding_valid": claim_grounding_valid,
                    "unsupported_numbers": sorted(unsupported_numbers),
                    "decision_boundary_valid": not unsafe_decision_claims,
                    "generation_mode": generation_mode,
                    "fallback_reason": response.generation.get("fallback_reason"),
                }
            )
    finally:
        policy_qa.settings = original_settings

    total = len(details)
    answerable = sum(item["status"] == "answered" for item in details)
    relevant_hits = sum(item["relevant_cited"] for item in details)
    valid_citations = sum(item["citation_allowlist_valid"] for item in details)
    verified_quotes = sum(item["all_quotes_verified"] for item in details)
    grounded_claims = sum(item["claim_grounding_valid"] for item in details)
    numeric_grounding = sum(not item["unsupported_numbers"] for item in details)
    safe_boundaries = sum(item["decision_boundary_valid"] for item in details)
    successful = sum(
        item["status"] == "answered"
        and item["relevant_cited"]
        and item["citation_allowlist_valid"]
        and item["all_quotes_verified"]
        and item["claim_grounding_valid"]
        and not item["unsupported_numbers"]
        and item["decision_boundary_valid"]
        for item in details
    )
    return {
        "benchmark_role": "internally_curated_policy_qa_grounding_benchmark",
        "evaluated_split": split,
        "case_count": total,
        "live_model_enabled": live_model,
        "answerable_rate": rate_metric(answerable, total),
        "expected_evidence_citation_rate": rate_metric(relevant_hits, total),
        "citation_allowlist_valid_rate": rate_metric(valid_citations, total),
        "verified_quote_rate": rate_metric(verified_quotes, total),
        "claim_lexical_grounding_rate": rate_metric(grounded_claims, total),
        "numeric_grounding_rate": rate_metric(numeric_grounding, total),
        "decision_boundary_valid_rate": rate_metric(safe_boundaries, total),
        "end_to_end_grounded_success_rate": rate_metric(successful, total),
        "generation_modes": dict(generation_modes),
        "error_table": [
            item
            for item in details
            if not (
                item["status"] == "answered"
                and item["relevant_cited"]
                and item["citation_allowlist_valid"]
                and item["all_quotes_verified"]
                and item["claim_grounding_valid"]
                and not item["unsupported_numbers"]
                and item["decision_boundary_valid"]
            )
        ],
        "details": details,
        "policy_file_isolation": payload.get("policy_file_isolation"),
        "claim_boundary": (
            "该基准复用冻结检索集，评价端到端回答是否引用预期证据、引用是否在检索"
            "白名单内及原文是否核验；不代表真实群众满意度、资格判断准确率或外部专家评测。"
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="评估有据政策问答的引用与回退闭环。")
    parser.add_argument(
        "--benchmark",
        type=Path,
        default=ROOT / "data" / "evaluation" / "retrieval_benchmark.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data" / "evaluation" / "policy_qa_report.json",
    )
    parser.add_argument("--split", default="frozen_final_test")
    parser.add_argument("--live-model", action="store_true")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    report = evaluate(
        args.benchmark.resolve(),
        split=args.split,
        live_model=args.live_model,
        limit=args.limit,
    )
    content = json.dumps(report, ensure_ascii=False, indent=2)
    args.output.resolve().write_text(content, encoding="utf-8")
    print(content)


if __name__ == "__main__":
    main()
