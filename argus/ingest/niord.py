from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import httpx

from argus.ingest.common import clean_html
from argus.models import EventCreate, IngestResult
from argus.repository import (
    delete_events_by_source,
    get_fallback_location,
    insert_raw_article,
    list_classification_terms,
    update_source_status,
    upsert_event,
)


SOURCE_ID = "niord-messages"
SOURCE_NAME = "Niord Nautical Information"
ENDPOINT = "https://niord.dma.dk/rest/public/v1/messages"
MAP_URL = "https://nautiskinformation.soefartsstyrelsen.dk/index.html#/messages/map"
DK_LAT_MIN = 54.4
DK_LAT_MAX = 58.2
DK_LON_MIN = 7.7
DK_LON_MAX = 15.4


def sync_niord(limit: int = 250) -> IngestResult:
    try:
        messages = fetch_niord_messages(limit=limit)
    except httpx.HTTPError as error:
        update_source_status(SOURCE_ID, "error", last_error=str(error))
        return IngestResult(
            source_id=SOURCE_ID,
            observations_seen=0,
            observations_stored=0,
            events_created=0,
            events_updated=0,
            message=f"Niord request failed: {error}",
        )

    stored = 0
    created = 0
    updated = 0
    delete_events_by_source(SOURCE_NAME)
    for message in messages:
        article = article_from_message(message)
        if article is None:
            continue
        if insert_raw_article(payload=json.dumps(message, ensure_ascii=False), **article):
            stored += 1

        event = event_from_message(message)
        if event is None:
            continue
        _, was_created = upsert_event(event)
        if was_created:
            created += 1
        else:
            updated += 1

    update_source_status(SOURCE_ID, "connected", success=True)
    return IngestResult(
        source_id=SOURCE_ID,
        observations_seen=len(messages),
        observations_stored=stored,
        events_created=created,
        events_updated=updated,
        message="Niord nautical messages synced.",
    )


def fetch_niord_messages(limit: int) -> list[dict[str, Any]]:
    with httpx.Client(timeout=25.0, follow_redirects=True) as client:
        response = client.get(ENDPOINT)
        response.raise_for_status()
    payload = response.json()
    messages = payload if isinstance(payload, list) else payload.get("data", [])
    return [message for message in messages if isinstance(message, dict)][:limit]


def article_from_message(message: dict[str, Any]) -> dict[str, Any] | None:
    message_id = str(message.get("id") or message.get("shortId") or "")
    title = message_title(message)
    if not message_id or not title:
        return None
    published = parse_niord_time(message.get("publishDateFrom") or message.get("created"))
    return {
        "article_id": f"{SOURCE_ID}:{message_id}",
        "source_id": SOURCE_ID,
        "title": title,
        "url": f"{MAP_URL}/{message_id}",
        "published_at": published.isoformat() if published else None,
        "summary": message_summary(message),
    }


def event_from_message(message: dict[str, Any]) -> EventCreate | None:
    title = message_title(message)
    if not title or str(message.get("status", "")).upper() != "PUBLISHED":
        return None

    location = message_location(message)
    if location is None:
        if not has_denmark_area(message):
            return None
        location = get_fallback_location()
        if location is None:
            return None
    latitude, longitude = location

    starts_at = parse_niord_time(message.get("publishDateFrom") or message.get("created")) or datetime.now(timezone.utc)
    ends_at = parse_niord_time(message.get("followUpDate"))
    return EventCreate(
        title=f"Niord: {title}"[:140],
        category="maritime",
        severity=niord_severity(f"{title} {message_summary(message)}"),
        status="upcoming" if starts_at > datetime.now(timezone.utc) else "current",
        source=SOURCE_NAME,
        description=message_summary(message)[:1000] or title,
        latitude=latitude,
        longitude=longitude,
        starts_at=starts_at,
        ends_at=ends_at,
    )


def message_title(message: dict[str, Any]) -> str:
    desc = preferred_desc(message.get("descs", []))
    return clean_html(str(desc.get("title") or message.get("shortId") or ""))


def message_summary(message: dict[str, Any]) -> str:
    details: list[str] = []
    for part in message.get("parts", []):
        if not isinstance(part, dict):
            continue
        desc = preferred_desc(part.get("descs", []))
        subject = clean_html(str(desc.get("subject") or ""))
        body = clean_html(str(desc.get("details") or ""))
        details.append(" - ".join(item for item in (subject, body) if item))
    if details:
        return " ".join(details)
    desc = preferred_desc(message.get("descs", []))
    return clean_html(str(desc.get("source") or ""))


def preferred_desc(descs: Any) -> dict[str, Any]:
    if not isinstance(descs, list):
        return {}
    for lang in ("da", "en"):
        for desc in descs:
            if isinstance(desc, dict) and desc.get("lang") == lang:
                return desc
    return next((desc for desc in descs if isinstance(desc, dict)), {})


def message_location(message: dict[str, Any]) -> tuple[float, float] | None:
    points: list[tuple[float, float]] = []
    for part in message.get("parts", []):
        if isinstance(part, dict):
            points.extend(points_from_geometry(part.get("geometry")))
    points = [(lat, lon) for lat, lon in points if in_denmark(lat, lon)]
    if not points:
        return None
    return (
        sum(lat for lat, _ in points) / len(points),
        sum(lon for _, lon in points) / len(points),
    )


def points_from_geometry(geometry: Any) -> list[tuple[float, float]]:
    if not isinstance(geometry, dict):
        return []
    if geometry.get("type") == "FeatureCollection":
        points: list[tuple[float, float]] = []
        for feature in geometry.get("features", []):
            if isinstance(feature, dict):
                points.extend(points_from_geometry(feature.get("geometry")))
        return points
    if geometry.get("type") == "Feature":
        return points_from_geometry(geometry.get("geometry"))
    return points_from_coordinates(geometry.get("coordinates"))


def points_from_coordinates(coordinates: Any) -> list[tuple[float, float]]:
    if not isinstance(coordinates, list):
        return []
    if len(coordinates) >= 2 and all(isinstance(value, (int, float)) for value in coordinates[:2]):
        longitude = float(coordinates[0])
        latitude = float(coordinates[1])
        return [(latitude, longitude)]
    points: list[tuple[float, float]] = []
    for item in coordinates:
        points.extend(points_from_coordinates(item))
    return points


def has_denmark_area(message: dict[str, Any]) -> bool:
    for area in message.get("areas", []):
        if not isinstance(area, dict):
            continue
        if area.get("mrn") == "urn:mrn:iho:country:dk":
            return True
        for desc in area.get("descs", []):
            if isinstance(desc, dict) and str(desc.get("name", "")).lower() in {"danmark", "denmark"}:
                return True
        parent = area.get("parent")
        if isinstance(parent, dict) and parent.get("mrn") == "urn:mrn:iho:country:dk":
            return True
    return False


def in_denmark(latitude: float, longitude: float) -> bool:
    return DK_LAT_MIN <= latitude <= DK_LAT_MAX and DK_LON_MIN <= longitude <= DK_LON_MAX


def niord_severity(text: str) -> str:
    normalized = text.lower()
    for row in list_classification_terms(SOURCE_ID, rule_group="severity"):
        if str(row["term"]).lower() in normalized:
            return str(row["severity"])
    return "low"


def parse_niord_time(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        timestamp = int(value)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc)
