from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

import httpx

from argus.ingest.common import clean_html, parse_iso_datetime
from argus.models import EventCreate, IngestResult
from argus.repository import delete_events_by_source, insert_raw_article, update_source_status, upsert_event


SOURCE_ID = "trafikinfo-events"
ENDPOINT = "https://storage.googleapis.com/trafikkort-data/geojson/big-screen-events.json"


def sync_traffic(limit: int = 200) -> IngestResult:
    try:
        features = fetch_traffic_features(limit=limit)
    except httpx.HTTPError as error:
        update_source_status(SOURCE_ID, "error", last_error=str(error))
        return IngestResult(
            source_id=SOURCE_ID,
            observations_seen=0,
            observations_stored=0,
            events_created=0,
            events_updated=0,
            message=f"Vejdirektoratet traffic request failed: {error}",
        )

    delete_events_by_source("Vejdirektoratet Trafikinfo")
    stored = 0
    created = 0
    updated = 0
    for feature in features:
        article = article_from_feature(feature)
        if article is None:
            continue
        if insert_raw_article(payload=json.dumps(feature, ensure_ascii=False), **article):
            stored += 1

        event = event_from_feature(feature)
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
        observations_seen=len(features),
        observations_stored=stored,
        events_created=created,
        events_updated=updated,
        message="Vejdirektoratet traffic events synced.",
    )


def fetch_traffic_features(limit: int) -> list[dict[str, Any]]:
    with httpx.Client(timeout=20.0, follow_redirects=True) as client:
        response = client.get(ENDPOINT)
        response.raise_for_status()
    collections = response.json()
    features: list[dict[str, Any]] = []
    seen: set[str] = set()
    for collection in collections if isinstance(collections, list) else [collections]:
        for feature in collection.get("features", []):
            feature_id = str((feature.get("properties") or {}).get("featureId") or feature.get("id") or "")
            if not feature_id or feature_id in seen:
                continue
            seen.add(feature_id)
            features.append(feature)
            if len(features) >= limit:
                return features
    return features


def article_from_feature(feature: dict[str, Any]) -> dict[str, Any] | None:
    props = feature.get("properties") or {}
    feature_id = str(props.get("featureId") or "")
    title = str(props.get("header") or props.get("title") or "")
    if not feature_id or not title:
        return None
    published = parse_traffic_datetime(props.get("lastModifiedString") or props.get("dateInsertedInListString"))
    return {
        "article_id": f"{SOURCE_ID}:{feature_id}",
        "source_id": SOURCE_ID,
        "title": clean_traffic_text(title),
        "url": "https://trafikkort.vejdirektoratet.dk/",
        "published_at": published.isoformat() if published else None,
        "summary": clean_traffic_text(str(props.get("description") or "")),
    }


def event_from_feature(feature: dict[str, Any]) -> EventCreate | None:
    props = feature.get("properties") or {}
    geometry = feature.get("geometry") or {}
    coordinates = geometry.get("coordinates") or []
    if len(coordinates) < 2 or str(props.get("suspended", "")).lower() == "true":
        return None
    try:
        longitude = float(coordinates[0])
        latitude = float(coordinates[1])
    except (TypeError, ValueError):
        return None

    title = clean_traffic_text(str(props.get("header") or props.get("title") or "Traffic event"))
    description = clean_traffic_text(str(props.get("description") or props.get("explanationText") or title))
    starts_at = parse_traffic_datetime(props.get("beginPeriod")) or parse_traffic_datetime(
        props.get("lastModifiedString")
    ) or datetime.now(timezone.utc)
    ends_at = parse_traffic_datetime(props.get("endPeriod"))
    severity = traffic_severity(f"{title} {description}".lower())
    status = "upcoming" if str(props.get("future", "")).lower() == "true" else "current"
    return EventCreate(
        title=f"Trafikinfo: {title}"[:140],
        category="transport",
        severity=severity,
        status=status,
        source="Vejdirektoratet Trafikinfo",
        description=description[:1000],
        latitude=latitude,
        longitude=longitude,
        starts_at=starts_at,
        ends_at=ends_at,
    )


def traffic_severity(text: str) -> str:
    if any(keyword in text for keyword in ("vejen er spærret", "spærret vej", "uheld", "redningsarbejde")):
        return "high"
    if any(keyword in text for keyword in ("spor spærret", "spor blokeret", "glat føre")):
        return "medium"
    return "low"


def clean_traffic_text(value: str | None) -> str:
    text = clean_html(value)
    text = re.sub(r"\s*<\d+[a-zA-Z]?>\s*", " ", text)
    text = re.sub(r"\s+([,.;:])", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_traffic_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    parsed = parse_iso_datetime(str(value))
    if parsed:
        return parsed
    try:
        naive = datetime.strptime(str(value), "%d-%m-%Y kl. %H:%M")
    except ValueError:
        return None
    return naive.replace(tzinfo=timezone.utc)
