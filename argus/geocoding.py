from __future__ import annotations

from typing import Any

import httpx


DAWA_STEDNAVNE_URL = "https://api.dataforsyningen.dk/stednavne2"


def geocode_danish_place(name: str) -> tuple[float, float] | None:
    query = " ".join(name.split())
    if not query:
        return None
    try:
        with httpx.Client(timeout=8.0, follow_redirects=True) as client:
            response = client.get(
                DAWA_STEDNAVNE_URL,
                params={"q": query, "struktur": "mini", "per_side": 5},
                headers={"User-Agent": "Argus/0.1 Denmark hazard monitor"},
            )
            response.raise_for_status()
            items = response.json()
            if not isinstance(items, list):
                items = items.get("data", [])
            for item in items:
                location = coordinates_from_payload(item)
                if location is not None:
                    return location
                href = item.get("href") if isinstance(item, dict) else None
                if not href:
                    continue
                detail = client.get(href, headers={"User-Agent": "Argus/0.1 Denmark hazard monitor"})
                detail.raise_for_status()
                location = coordinates_from_payload(detail.json())
                if location is not None:
                    return location
    except httpx.HTTPError:
        return None
    return None


def coordinates_from_payload(value: Any) -> tuple[float, float] | None:
    if isinstance(value, dict):
        for key in ("visueltcenter", "geopunkt", "coordinates", "koordinater"):
            location = coordinates_from_pair(value.get(key))
            if location is not None:
                return location
        for key in ("stednavn", "geometri", "geometry"):
            location = coordinates_from_payload(value.get(key))
            if location is not None:
                return location
        for item in value.values():
            location = coordinates_from_payload(item)
            if location is not None:
                return location
    if isinstance(value, list):
        location = coordinates_from_pair(value)
        if location is not None:
            return location
        for item in value:
            location = coordinates_from_payload(item)
            if location is not None:
                return location
    return None


def coordinates_from_pair(value: Any) -> tuple[float, float] | None:
    if not isinstance(value, list) or len(value) < 2:
        return None
    if not all(isinstance(item, (int, float)) for item in value[:2]):
        return None
    first = float(value[0])
    second = float(value[1])
    if 54.4 <= first <= 58.2 and 7.7 <= second <= 15.4:
        return first, second
    if 7.7 <= first <= 15.4 and 54.4 <= second <= 58.2:
        return second, first
    return None
