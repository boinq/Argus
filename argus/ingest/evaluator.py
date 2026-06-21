from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from argus.ml import as_category, as_severity, classify_category, classify_severity
from argus.repository import list_classification_terms


@dataclass(frozen=True)
class Evaluation:
    category: str
    severity: str
    score: int
    reasons: tuple[str, ...]


def evaluate_news_relevance(title: str, summary: str = "") -> Evaluation | None:
    text = normalize(f"{title} {summary}")
    if any(contains_term(text, row["term"]) for row in list_classification_terms("dr-news", rule_group="noise")):
        return None

    category, category_score, category_reasons = best_category(text)
    ml_category = classify_category(text)
    if ml_category and (category is None or ml_category.confidence >= 0.65):
        category = as_category(ml_category.label)
        category_score = max(category_score, round(ml_category.confidence * 6))
        category_reasons = [f"ml:{reason}" for reason in ml_category.reasons]

    if category is None:
        return None

    impact_score, impact_reasons = score_terms(text, list_classification_terms("dr-news", rule_group="impact"))
    geography_score = (
        1
        if any(
            contains_term(text, row["term"])
            for row in list_classification_terms("dr-news", rule_group="geography")
        )
        else 0
    )
    score = category_score + impact_score + geography_score

    if score < 5:
        return None

    ml_severity = classify_severity(text)
    severity = "high" if score >= 8 else "medium"
    if ml_severity and ml_severity.confidence >= 0.55:
        severity = as_severity(ml_severity.label)
    if severity == "low":
        return None
    return Evaluation(
        category=category,
        severity=severity,
        score=score,
        reasons=tuple(category_reasons + impact_reasons),
    )


def evaluate_maritime_relevance(title: str, summary: str = "") -> Evaluation | None:
    text = normalize(f"{title} {summary}")
    score, reasons = score_terms(text, list_classification_terms("dma-news", rule_group="maritime"))
    if score < 4:
        return None
    return Evaluation(
        category="maritime",
        severity="high" if score >= 5 else "medium",
        score=score,
        reasons=tuple(reasons),
    )


def best_category(text: str) -> tuple[str | None, int, list[str]]:
    best_name: str | None = None
    best_score = 0
    best_reasons: list[str] = []
    by_category: dict[str, list[object]] = {}
    for row in list_classification_terms("dr-news", rule_group="category"):
        by_category.setdefault(str(row["category"]), []).append(row)
    for category, terms in by_category.items():
        score, reasons = score_terms(text, terms)
        if score > best_score:
            best_name = category
            best_score = score
            best_reasons = reasons
    return best_name, best_score, best_reasons


def score_terms(text: str, terms: Iterable[object]) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    for item in terms:
        term, weight = term_score(item)
        if contains_term(text, term):
            score += weight
            reasons.append(term)
    return score, reasons


def term_score(item: object) -> tuple[str, int]:
    if isinstance(item, tuple):
        return str(item[0]), int(item[1])
    return str(item["term"]), int(item["score"])  # type: ignore[index]


def contains_term(text: str, term: str) -> bool:
    escaped = re.escape(normalize(term))
    return re.search(rf"(?<!\w){escaped}(?!\w)", text, flags=re.IGNORECASE) is not None


def normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold()).strip()
