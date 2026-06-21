from __future__ import annotations

import re
from collections import Counter


def extract_candidate_terms(text: str, *, limit: int = 20) -> list[str]:
    tokens = [
        token
        for token in re.findall(r"[0-9a-zA-ZæøåÆØÅ_-]{3,}", text.casefold())
        if not token.isdigit()
    ]
    candidates: Counter[str] = Counter()
    for size in (1, 2, 3):
        for index in range(0, max(0, len(tokens) - size + 1)):
            phrase = " ".join(tokens[index : index + size])
            if len(phrase) >= 4:
                candidates[phrase] += 1
    return [term for term, _ in candidates.most_common(limit)]


def normalize_location_name(name: str) -> str:
    normalized = name.strip().lower()
    replacements = {
        "æ": "ae",
        "ø": "o",
        "å": "aa",
        "ä": "ae",
        "ö": "o",
        "ü": "u",
    }
    for source, target in replacements.items():
        normalized = normalized.replace(source, target)
    normalized = normalized.replace("&", " og ")
    for character in "/,;:._-":
        normalized = normalized.replace(character, " ")
    return " ".join(normalized.split())
