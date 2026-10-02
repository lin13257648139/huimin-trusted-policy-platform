from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.config import BASE_DIR


DATASET_PATH = BASE_DIR / "data" / "ml" / "intent_dataset.json"


@dataclass(frozen=True)
class IntentScore:
    benefit_id: str
    benefit_name: str
    score: float
    evidence_ngrams: tuple[str, ...]


def _features(text: str) -> Counter[str]:
    compact = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", text.lower())
    values: Counter[str] = Counter()
    for size in (1, 2, 3):
        values.update(compact[index : index + size] for index in range(len(compact) - size + 1))
    return values


class IntentClassifier:
    """Small reproducible multinomial Naive Bayes router.

    It only prioritizes guidance topics and never changes eligibility. Scores
    are normalized ranking scores, not calibrated probabilities.
    """

    def __init__(self, payload: dict[str, object], dataset_digest: str) -> None:
        labels = payload["labels"]
        if not isinstance(labels, dict):
            raise ValueError("intent dataset labels must be an object")
        self.names = {key: str(value["name"]) for key, value in labels.items()}
        self.document_counts: Counter[str] = Counter()
        self.feature_counts: dict[str, Counter[str]] = defaultdict(Counter)
        self.feature_totals: Counter[str] = Counter()
        vocabulary: set[str] = set()
        for label, group in labels.items():
            for text in group["train"]:
                features = _features(str(text))
                self.document_counts[label] += 1
                self.feature_counts[label].update(features)
                self.feature_totals[label] += sum(features.values())
                vocabulary.update(features)
        self.vocabulary = vocabulary
        self.total_documents = sum(self.document_counts.values())
        self.model_version = f"intent-nb/{dataset_digest[:12]}"

    def predict(self, text: str, limit: int = 3) -> list[IntentScore]:
        features = _features(text)
        if not features:
            return []
        scores: dict[str, float] = {}
        contributions: dict[str, list[tuple[float, str]]] = defaultdict(list)
        vocabulary_size = max(len(self.vocabulary), 1)
        for label in self.names:
            prior = math.log(self.document_counts[label] / self.total_documents)
            denominator = self.feature_totals[label] + vocabulary_size
            score = prior
            for feature, count in features.items():
                numerator = self.feature_counts[label][feature] + 1
                contribution = count * math.log(numerator / denominator)
                score += contribution
                if self.feature_counts[label][feature]:
                    contributions[label].append((contribution, feature))
            scores[label] = score
        peak = max(scores.values())
        exponentials = {label: math.exp(score - peak) for label, score in scores.items()}
        total = sum(exponentials.values())
        ranked = sorted(exponentials, key=exponentials.get, reverse=True)
        if exponentials[ranked[0]] / total < 0.35:
            return []
        return [
            IntentScore(
                benefit_id=label,
                benefit_name=self.names[label],
                score=round(exponentials[label] / total, 4),
                evidence_ngrams=tuple(
                    feature
                    for _, feature in sorted(contributions[label], reverse=True)[:5]
                    if len(feature) >= 2
                ),
            )
            for label in ranked[:limit]
        ]


@lru_cache(maxsize=1)
def get_intent_classifier() -> IntentClassifier:
    raw = DATASET_PATH.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    return IntentClassifier(payload, hashlib.sha256(raw).hexdigest())


def classify_intent(text: str, limit: int = 3) -> tuple[str, list[dict[str, object]]]:
    classifier = get_intent_classifier()
    predictions = [
        {
            "benefit_id": item.benefit_id,
            "benefit_name": item.benefit_name,
            "score": item.score,
            "evidence_ngrams": list(item.evidence_ngrams),
        }
        for item in classifier.predict(text, limit=limit)
    ]
    return classifier.model_version, predictions
