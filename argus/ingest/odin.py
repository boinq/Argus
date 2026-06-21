from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any
from xml.etree import ElementTree

import httpx

from argus.ingest.common import clean_html, clean_id, parse_feed_datetime
from argus.models import EventCreate, IngestResult
from argus.repository import (
    delete_events_by_source,
    find_location_alias,
    insert_raw_article,
    list_location_aliases,
    list_classification_terms,
    record_location_candidate,
    update_source_status,
    upsert_event,
)


SOURCE_ID = "odin-incidents"
SOURCE_NAME = "ODIN Beredskabsstyrelsen"
ENDPOINT = "http://www.odin.dk/RSS/RSS.aspx?beredskabsID=0000"
SOURCE_URL = "http://www.odin.dk/112puls/"


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


def event_from_incident(incident: dict[str, Any]) -> EventCreate | None:
    station = str(incident.get("station") or "")
    location = incident_location(incident)
    if location is None:
        return None
    latitude, longitude = location
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


def station_location(station: str) -> tuple[float, float] | None:
    normalized = normalize_station_name(station)
    if not normalized:
        return None
    return resolve_location(normalized, kinds=("station", "place"))


def incident_location(incident: dict[str, Any]) -> tuple[float, float] | None:
    station = str(incident.get("station") or "")
    station_normalized = normalize_station_name(station)
    location = resolve_location(station_normalized, kinds=("station", "place"))
    if location is not None:
        return location

    context = f"{incident.get('title', '')} {incident.get('summary', '')}".strip()
    if station_normalized:
        record_location_candidate(
            source_id=SOURCE_ID,
            kind="station",
            name=station,
            normalized_name=station_normalized,
            context=context,
        )

    beredskab = str(incident.get("title") or "")
    beredskab_normalized = normalize_beredskab_name(beredskab)
    location = resolve_location(beredskab_normalized, kinds=("beredskab",))
    if location is not None:
        return location

    if beredskab_normalized:
        record_location_candidate(
            source_id=SOURCE_ID,
            kind="beredskab",
            name=beredskab,
            normalized_name=beredskab_normalized,
            context=context,
        )
    return None


def beredskab_location(name: str) -> tuple[float, float] | None:
    normalized = normalize_beredskab_name(name)
    if not normalized:
        return None
    return (
        resolve_location(normalized, kinds=("beredskab",))
        or station_location(name)
    )


def resolve_location(
    normalized_name: str,
    *,
    kinds: tuple[str, ...],
) -> tuple[float, float] | None:
    if not normalized_name:
        return None

    exact = find_location_alias(normalized_name, kinds=kinds)
    if exact is not None:
        return exact

    for row in list_location_aliases(kinds=kinds):
        alias = row["normalized_name"]
        if re.search(rf"\b{re.escape(alias)}\b", normalized_name):
            return (float(row["latitude"]), float(row["longitude"]))
    return None


def normalize_station_name(station: str) -> str:
    normalized = station.strip().lower()
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
    normalized = re.sub(r"\([^)]*\)", " ", normalized)
    normalized = re.sub(r"[/,;:._-]+", " ", normalized)
    normalized = re.sub(
        r"\b(station|brandstation|beredskab|beredskabet|brandvaesen|brandvæsen|"
        r"brand|redning|redningsberedskab|hovedstadens|trekantomraadets|"
        r"midtjyllands|nordjyllands|sydjyllands|ostjyllands|østjyllands|"
        r"vestegnen|f\b)\b",
        " ",
        normalized,
    )
    return re.sub(r"\s+", " ", normalized).strip()


def normalize_beredskab_name(name: str) -> str:
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
    normalized = re.sub(r"\([^)]*\)", " ", normalized)
    normalized = re.sub(r"[/,;:._-]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def odin_severity(alarm_type: str) -> str:
    normalized = alarm_type.lower()
    for row in list_classification_terms(SOURCE_ID, rule_group="severity"):
        if str(row["term"]).lower() in normalized:
            return str(row["severity"])
    return "low"
