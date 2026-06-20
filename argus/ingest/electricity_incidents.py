from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from argus.ingest.common import clean_html
from argus.models import EventCreate, IngestResult
from argus.repository import delete_events_by_source, insert_raw_article, update_source_status, upsert_event


SOURCE_ID = "greenpowerdenmark-incidents"
SOURCE_NAME = "Green Power Denmark Elnet"
ENDPOINT = "https://api.elnet.greenpowerdenmark.dk/api/incidents"
DENMARK_TZ = ZoneInfo("Europe/Copenhagen")


def sync_electricity_incidents(limit: int = 1000) -> IngestResult:
    try:
        incidents = fetch_electricity_incidents(limit=limit)
    except httpx.HTTPError as error:
        update_source_status(SOURCE_ID, "error", last_error=str(error))
        return IngestResult(
            source_id=SOURCE_ID,
            observations_seen=0,
            observations_stored=0,
            events_created=0,
            events_updated=0,
            message=f"Green Power Denmark incidents request failed: {error}",
        )

    stored = 0
    created = 0
    updated = 0
    delete_events_by_source(SOURCE_NAME)
    for incident in incidents:
        if insert_raw_article(
            article_id=f"{SOURCE_ID}:{incident.get('id')}",
            source_id=SOURCE_ID,
            title=clean_html(str(incident.get("title") or "Electricity incident")),
            url=ENDPOINT,
            published_at=(parse_incident_datetime(incident.get("created")) or datetime.now(timezone.utc)).isoformat(),
            summary=incident_summary(incident),
            payload=json.dumps(incident, ensure_ascii=False),
        ):
            stored += 1

        event = event_from_incident(incident)
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
        observations_seen=len(incidents),
        observations_stored=stored,
        events_created=created,
        events_updated=updated,
        message="Green Power Denmark electricity incidents synced.",
    )


def fetch_electricity_incidents(limit: int) -> list[dict[str, Any]]:
    with httpx.Client(timeout=25.0, follow_redirects=True) as client:
        response = client.get(ENDPOINT, headers={"User-Agent": "Argus/0.1 Denmark hazard monitor"})
        response.raise_for_status()
    payload = response.json()
    incidents = payload if isinstance(payload, list) else []
    return [incident for incident in incidents if isinstance(incident, dict) and is_relevant_incident(incident)][:limit]


def is_relevant_incident(incident: dict[str, Any]) -> bool:
    if not coordinates(incident):
        return False
    status = str(incident.get("incidentStatus") or "").lower()
    if status and status != "aktiv":
        return False
    now = datetime.now(timezone.utc)
    latest_known = parse_incident_datetime(incident.get("endDate")) or parse_incident_datetime(
        incident.get("expectedDowntime")
    )
    if latest_known and latest_known < now - timedelta(hours=1):
        return False
    return True


def event_from_incident(incident: dict[str, Any]) -> EventCreate | None:
    if not should_promote_incident(incident):
        return None
    location = coordinates(incident)
    if location is None:
        return None
    latitude, longitude = location
    starts_at = parse_incident_datetime(incident.get("startDate")) or parse_incident_datetime(
        incident.get("created")
    ) or datetime.now(timezone.utc)
    ends_at = parse_incident_datetime(incident.get("endDate")) or parse_incident_datetime(incident.get("expectedDowntime"))
    incident_id = str(incident.get("id") or "")
    title = clean_html(str(incident.get("title") or "Electricity incident"))
    event_status = event_status_from_times(starts_at, ends_at)
    return EventCreate(
        title=f"El incident {incident_id}: {title}"[:140],
        category="electrical",
        severity=incident_severity(incident),
        status=event_status,
        source=SOURCE_NAME,
        description=incident_summary(incident)[:1000],
        latitude=latitude,
        longitude=longitude,
        starts_at=starts_at,
        ends_at=ends_at,
    )


def event_status_from_times(starts_at: datetime, ends_at: datetime | None) -> str:
    now = datetime.now(timezone.utc)
    if ends_at and ends_at < now:
        return "resolved"
    if starts_at > now:
        return "upcoming"
    return "current"


def should_promote_incident(incident: dict[str, Any]) -> bool:
    incident_type = str(incident.get("incidentType") or "").lower()
    affected = int_or_zero(incident.get("effectedCustomers"))
    if "uvarslet" in incident_type:
        return True
    if "varslet" in incident_type:
        return affected >= 100
    return affected >= 250


def incident_summary(incident: dict[str, Any]) -> str:
    parts = [
        clean_html(str(incident.get("incidentType") or "")),
        clean_html(str(incident.get("cause") or "")),
        clean_html(str(incident.get("comment") or "")),
        f"Supplier: {clean_html(str(incident.get('supplierName') or 'Unknown'))}",
        f"Affected customers: {int_or_zero(incident.get('effectedCustomers'))}",
        f"Zipcodes: {clean_html(str(incident.get('zipcodes') or 'Unknown'))}",
    ]
    return " | ".join(part for part in parts if part)


def incident_severity(incident: dict[str, Any]) -> str:
    affected = int_or_zero(incident.get("effectedCustomers"))
    incident_type = str(incident.get("incidentType") or "").lower()
    if affected >= 5000:
        return "critical"
    if affected >= 500:
        return "high"
    if affected >= 100 or "uvarslet" in incident_type:
        return "medium"
    return "low"


def coordinates(incident: dict[str, Any]) -> tuple[float, float] | None:
    try:
        latitude = float(incident.get("centerLat"))
        longitude = float(incident.get("centerLng"))
    except (TypeError, ValueError):
        return None
    if 54.4 <= latitude <= 58.2 and 7.7 <= longitude <= 15.4:
        return latitude, longitude
    return None


def parse_incident_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=DENMARK_TZ)
    return parsed.astimezone(timezone.utc)


def int_or_zero(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
