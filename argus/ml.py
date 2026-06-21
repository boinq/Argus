from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass

from argus.models import Category, Severity
from argus.repository import list_event_training_examples


@dataclass(frozen=True)
class TextScore:
    label: str
    confidence: float
    reasons: tuple[str, ...]


TOKEN_PATTERN = re.compile(r"[0-9a-zA-ZæøåÆØÅ_-]{3,}")


def classify_category(text: str) -> TextScore | None:
    return score_label(text, label_field="category", minimum_examples=3, minimum_confidence=0.52)


def classify_severity(text: str) -> TextScore | None:
    return score_label(text, label_field="severity", minimum_examples=3, minimum_confidence=0.50)


def score_label(
    text: str,
    *,
    label_field: str,
    minimum_examples: int,
    minimum_confidence: float,
) -> TextScore | None:
    examples = list_event_training_examples()
    grouped: dict[str, Counter[str]] = defaultdict(Counter)
    document_counts: Counter[str] = Counter()
    vocabulary: set[str] = set()
    for row in examples:
        label = str(row[label_field])
        tokens = set(tokenize(f"{row['title']} {row['description']}"))
        if not tokens:
            continue
        document_counts[label] += 1
        grouped[label].update(tokens)
        vocabulary.update(tokens)

    if sum(document_counts.values()) < minimum_examples or len(grouped) < 2:
        return None

    input_tokens = tokenize(text)
    if not input_tokens:
        return None

    total_documents = sum(document_counts.values())
    vocabulary_size = max(1, len(vocabulary))
    label_scores: dict[str, float] = {}
    label_reasons: dict[str, list[str]] = {}
    for label, counts in grouped.items():
        total_terms = sum(counts.values())
        score = math.log(document_counts[label] / total_documents)
        reasons: list[str] = []
        for token in input_tokens:
            if token not in vocabulary:
                continue
            token_score = math.log((counts[token] + 1) / (total_terms + vocabulary_size))
            score += token_score
            if counts[token] > 0:
                reasons.append(token)
        label_scores[label] = score
        label_reasons[label] = reasons

    if not label_scores:
        return None

    confidence_by_label = softmax(label_scores)
    label, confidence = max(confidence_by_label.items(), key=lambda item: item[1])
    if len(set(label_reasons[label])) < 2:
        return None
    if confidence < minimum_confidence:
        return None
    return TextScore(label=label, confidence=confidence, reasons=tuple(label_reasons[label][:8]))


def softmax(scores: dict[str, float]) -> dict[str, float]:
    high = max(scores.values())
    exp_scores = {label: math.exp(score - high) for label, score in scores.items()}
    total = sum(exp_scores.values())
    return {label: score / total for label, score in exp_scores.items()}


def tokenize(text: str) -> list[str]:
    return [
        token
        for token in TOKEN_PATTERN.findall(text.casefold())
        if not token.isdigit()
    ]


def as_category(value: str) -> Category:
    if value in Category.__args__:  # type: ignore[attr-defined]
        return value  # type: ignore[return-value]
    return "other"


def as_severity(value: str) -> Severity:
    if value in Severity.__args__:  # type: ignore[attr-defined]
        return value  # type: ignore[return-value]
    return "low"
