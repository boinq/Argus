from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any
from xml.etree import ElementTree

import httpx

from argus.ingest.common import DENMARK_CENTER, clean_html, clean_id, parse_feed_datetime
from argus.models import EventCreate, IngestResult
from argus.repository import delete_events_by_source, insert_raw_article, update_source_status, upsert_event


SOURCE_ID = "odin-incidents"
SOURCE_NAME = "ODIN Beredskabsstyrelsen"
ENDPOINT = "http://www.odin.dk/RSS/RSS.aspx?beredskabsID=0000"
SOURCE_URL = "http://www.odin.dk/112puls/"

STATION_COORDINATES = {
    "aarhus nord": (56.187, 10.197),
    "aarhus syd": (56.119, 10.158),
    "christianshavn": (55.673, 12.594),
    "feldborg/aulum": (56.326, 8.934),
    "frederiksberg": (55.681, 12.532),
    "hedensted": (55.77, 9.702),
    "hvidovre": (55.642, 12.475),
    "kolding": (55.491, 9.473),
    "nakskov": (54.833, 11.139),
    "ringe": (55.239, 10.478),
    "slangerup": (55.847, 12.178),
    "vesterbro": (55.669, 12.544),
    "vejle": (55.711, 9.536),
    "åsum - odense": (55.396, 10.463),
}


def sync_odin(limit: int = 20) -> IngestResult:
    try:
        incidents = fetch_odin_incidents(limit=limit)
    except httpx.HTTPError as error:
        update_source_status(SOURCE_ID, "error", last_error=str(error))
        return IngestResult(
            source_id=SOURCE_ID,
            observations_seen=0,
            observations_stored=0,
            events_created=0,
            events_updated=0,
            message=f"ODIN RSS request failed: {error}",
        )

    stored = 0
    created = 0
    updated = 0
    delete_events_by_source(SOURCE_NAME)
    for incident in incidents:
        if insert_raw_article(
            article_id=incident["id"],
            source_id=SOURCE_ID,
            title=incident["title"],
            url=incident["url"],
            published_at=incident.get("published_at"),
            summary=incident.get("summary", ""),
            payload=json.dumps(incident, ensure_ascii=False),
        ):
            stored += 1

        event = event_from_incident(incident)
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
        message="ODIN 1-1-2 pulse synced.",
    )


def fetch_odin_incidents(limit: int) -> list[dict[str, Any]]:
    with httpx.Client(timeout=20.0, follow_redirects=True) as client:
        response = client.get(ENDPOINT)
        response.raise_for_status()
    return parse_odin_rss(response.text)[:limit]


def parse_odin_rss(xml_text: str) -> list[dict[str, Any]]:
    root = ElementTree.fromstring(xml_text.lstrip("\ufeff"))
    incidents: list[dict[str, Any]] = []
    for item in root.findall(".//item"):
        district = clean_html(item.findtext("title") or "")
        summary = clean_html(item.findtext("description") or "")
        comments = clean_html(item.findtext("comments") or "")
        published = parse_feed_datetime(item.findtext("pubDate"))
        if not district or not summary:
            continue
        alarm_type = parse_alarm_type(summary)
        station = parse_station(summary)
        identifier = clean_id(f"{district}:{summary}:{comments or published}")
        incidents.append(
            {
                "id": f"{SOURCE_ID}:{identifier}",
                "title": district,
                "summary": summary,
                "url": SOURCE_URL,
                "published_at": published.isoformat() if published else None,
                "alarm_type": alarm_type,
                "station": station,
                "reported_at": comments,
            }
        )
    return incidents


def event_from_incident(incident: dict[str, Any]) -> EventCreate:
    station = str(incident.get("station") or "")
    latitude, longitude = station_location(station)
    starts_at = (
        datetime.fromisoformat(incident["published_at"])
        if incident.get("published_at")
        else datetime.now(timezone.utc)
    )
    alarm_type = str(incident.get("alarm_type") or "1-1-2 alarm")
    station_text = f" at {station}" if station else ""
    return EventCreate(
        title=f"ODIN: {incident['title']} - {alarm_type}"[:140],
        category="emergency",
        severity=odin_severity(alarm_type),
        status="current",
        source=SOURCE_NAME,
        description=f"{incident['summary']}{station_text}"[:1000],
        latitude=latitude,
        longitude=longitude,
        starts_at=starts_at,
        ends_at=None,
    )


def parse_alarm_type(summary: str) -> str:
    match = re.search(r"Førstemelding:\s*(?P<value>.*?)(?:\s+Station:|$)", summary)
    return clean_html(match.group("value")) if match else summary


def parse_station(summary: str) -> str:
    match = re.search(r"Station:\s*(?P<value>.+)$", summary)
    return clean_html(match.group("value")) if match else ""


def station_location(station: str) -> tuple[float, float]:
    normalized = station.strip().lower()
    return STATION_COORDINATES.get(normalized, DENMARK_CENTER)


def odin_severity(alarm_type: str) -> str:
    normalized = alarm_type.lower()
    if any(keyword in normalized for keyword in ("str. forurening", "kemikalie", "bygn.brand", "villa", "rækkehus")):
        return "high"
    if any(keyword in normalized for keyword in ("brand", "naturbrand", "forurening", "spild")):
        return "medium"
    return "low"
