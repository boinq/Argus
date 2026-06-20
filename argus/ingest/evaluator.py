from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Evaluation:
    category: str
    severity: str
    score: int
    reasons: tuple[str, ...]


CATEGORY_TERMS: dict[str, tuple[tuple[str, int], ...]] = {
    "weather": (
        ("storm", 3),
        ("skybrud", 4),
        ("oversvømmelse", 4),
        ("orkan", 4),
        ("brandfare", 3),
        ("dmi varsler", 4),
    ),
    "hybrid": (
        ("cyberangreb", 5),
        ("sabotage", 5),
        ("spionage", 4),
        ("hybridangreb", 5),
        ("hybrid krig", 5),
        ("kritisk infrastruktur", 4),
        ("beredskab", 3),
    ),
    "electrical": (
        ("strømafbrydelse", 5),
        ("blackout", 5),
        ("elforsyning", 4),
        ("elnet", 3),
        ("energinet", 3),
        ("forsyningssikkerhed", 4),
    ),
    "food": (
        ("fødevaremangel", 5),
        ("fødevaresikkerhed", 4),
        ("drikkevand", 5),
        ("forurening", 4),
        ("forsyningskrise", 5),
    ),
    "health": (
        ("udbrud", 4),
        ("smitte", 3),
        ("epidemi", 5),
        ("virus", 3),
        ("hospital", 3),
        ("akutberedskab", 4),
    ),
    "transport": (
        ("togaflysninger", 4),
        ("togbusser", 3),
        ("regionaltog", 3),
        ("motorvej", 3),
        ("bro lukket", 5),
        ("færge aflyst", 4),
        ("lufthavn lukket", 5),
    ),
    "maritime": (
        ("navigationsadvarsel", 5),
        ("navigation warning", 5),
        ("sejlads", 3),
        ("farvand", 3),
        ("havn lukket", 5),
        ("ship accident", 5),
        ("maritime security", 5),
    ),
}

IMPACT_TERMS: tuple[tuple[str, int], ...] = (
    ("akut", 2),
    ("alvorlig", 2),
    ("kritisk", 3),
    ("fare", 2),
    ("lukket", 2),
    ("spærret", 2),
    ("aflyst", 2),
    ("rammer", 2),
    ("nedbrud", 3),
    ("mangel", 2),
    ("beredskab", 2),
    ("forbudt", 2),
    ("evakuering", 4),
)

DENMARK_TERMS = (
    "danmark",
    "dansk",
    "danske",
    "sjælland",
    "jylland",
    "fyn",
    "bornholm",
    "københavn",
    "aarhus",
    "odense",
    "aalborg",
    "danish",
)

NOISE_TERMS = (
    "tv-serie",
    "kunstværk",
    "kongeparret",
    "sport",
    "kendt",
    "film",
    "musik",
    "hybrid-bil",
    "hybrid-biler",
)


def evaluate_news_relevance(title: str, summary: str = "") -> Evaluation | None:
    text = normalize(f"{title} {summary}")
    if any(contains_term(text, term) for term in NOISE_TERMS):
        return None

    category, category_score, category_reasons = best_category(text)
    if category is None:
        return None

    impact_score, impact_reasons = score_terms(text, IMPACT_TERMS)
    geography_score = 1 if any(contains_term(text, term) for term in DENMARK_TERMS) else 0
    score = category_score + impact_score + geography_score

    if score < 5:
        return None

    severity = "high" if score >= 8 or "kritisk" in impact_reasons else "medium"
    return Evaluation(
        category=category,
        severity=severity,
        score=score,
        reasons=tuple(category_reasons + impact_reasons),
    )


def evaluate_maritime_relevance(title: str, summary: str = "") -> Evaluation | None:
    text = normalize(f"{title} {summary}")
    score, reasons = score_terms(
        text,
        (
            ("navigation warning", 5),
            ("navigational warning", 5),
            ("warning", 4),
            ("accident", 5),
            ("cyber", 4),
            ("sanction", 4),
            ("security", 4),
            ("safety", 3),
            ("aids to navigation", 4),
        ),
    )
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
    for category, terms in CATEGORY_TERMS.items():
        score, reasons = score_terms(text, terms)
        if score > best_score:
            best_name = category
            best_score = score
            best_reasons = reasons
    return best_name, best_score, best_reasons


def score_terms(text: str, terms: tuple[tuple[str, int], ...]) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    for term, weight in terms:
        if contains_term(text, term):
            score += weight
            reasons.append(term)
    return score, reasons


def contains_term(text: str, term: str) -> bool:
    escaped = re.escape(normalize(term))
    return re.search(rf"(?<!\w){escaped}(?!\w)", text, flags=re.IGNORECASE) is not None


def normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold()).strip()
