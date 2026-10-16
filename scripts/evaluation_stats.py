from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any


def wilson_interval(successes: int, total: int, *, z: float = 1.959963984540054) -> dict[str, Any]:
    """Return a two-sided 95% Wilson score interval for a binomial rate."""

    if total <= 0:
        return {"method": "wilson", "confidence": 0.95, "lower": None, "upper": None}
    proportion = successes / total
    denominator = 1 + z * z / total
    centre = (proportion + z * z / (2 * total)) / denominator
    margin = (
        z
        * math.sqrt(proportion * (1 - proportion) / total + z * z / (4 * total * total))
        / denominator
    )
    return {
        "method": "wilson",
        "confidence": 0.95,
        "lower": round(max(0.0, centre - margin), 4),
        "upper": round(min(1.0, centre + margin), 4),
    }


def rate_metric(successes: int, total: int) -> dict[str, Any]:
    return {
        "successes": successes,
        "total": total,
        "estimate": round(successes / total, 4) if total else None,
        "ci95": wilson_interval(successes, total),
    }


def nearest_rank(values: Iterable[float], ratio: float) -> float | None:
    ordered = sorted(values)
    if not ordered:
        return None
    index = max(0, math.ceil(len(ordered) * ratio) - 1)
    return round(float(ordered[index]), 3)


def latency_summary(values: Iterable[float]) -> dict[str, Any]:
    samples = list(values)
    return {
        "samples": len(samples),
        "p50_ms": nearest_rank(samples, 0.50),
        "p95_ms": nearest_rank(samples, 0.95),
        "max_ms": round(max(samples), 3) if samples else None,
        "mean_ms": round(sum(samples) / len(samples), 3) if samples else None,
    }


def f1_metrics(true_positive: int, predicted: int, gold: int) -> dict[str, Any]:
    precision = true_positive / predicted if predicted else None
    recall = true_positive / gold if gold else None
    score = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and precision + recall
        else None
    )
    return {
        "true_positive": true_positive,
        "predicted": predicted,
        "gold": gold,
        "precision": round(precision, 4) if precision is not None else None,
        "precision_ci95": wilson_interval(true_positive, predicted),
        "recall": round(recall, 4) if recall is not None else None,
        "recall_ci95": wilson_interval(true_positive, gold),
        "f1": round(score, 4) if score is not None else None,
    }
