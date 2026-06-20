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
    "aalborg": (57.048, 9.919),
    "aarhus nord": (56.187, 10.197),
    "aarhus syd": (56.119, 10.158),
    "allerod": (55.872, 12.345),
    "ballerup": (55.731, 12.363),
    "birkerod": (55.847, 12.429),
    "bronderslev": (57.27, 9.941),
    "christianshavn": (55.673, 12.594),
    "esbjerg": (55.476, 8.459),
    "faelledvej": (55.696, 12.558),
    "feldborg/aulum": (56.326, 8.934),
    "feldborg aulum": (56.326, 8.934),
    "frederiksberg": (55.681, 12.532),
    "frederikshavn": (57.441, 10.537),
    "glostrup": (55.666, 12.398),
    "haderslev": (55.249, 9.489),
    "hedensted": (55.77, 9.702),
    "helsingor": (56.036, 12.613),
    "herning": (56.138, 8.967),
    "hillerod": (55.927, 12.301),
    "hobro": (56.638, 9.794),
    "holbaek": (55.718, 11.704),
    "holstebro": (56.36, 8.616),
    "horsens": (55.861, 9.85),
    "hvidovre": (55.642, 12.475),
    "hjorring": (57.456, 9.996),
    "kalundborg": (55.681, 11.089),
    "kerteminde": (55.45, 10.657),
    "knebel": (56.205, 10.493),
    "kolding": (55.491, 9.473),
    "koge": (55.458, 12.182),
    "naestved": (55.229, 11.761),
    "nakskov": (54.833, 11.139),
    "nykobing f": (54.769, 11.875),
    "nykobing falster": (54.769, 11.875),
    "odense": (55.403, 10.402),
    "randers": (56.46, 10.037),
    "ringe": (55.239, 10.478),
    "ringsted": (55.442, 11.79),
    "roskilde": (55.641, 12.087),
    "st lellinge": (55.481, 12.139),
    "st roskilde": (55.641, 12.087),
    "st store heddinge": (55.309, 12.388),
    "st torring": (55.85, 9.48),
    "silkeborg": (56.17, 9.545),
    "skanderborg": (56.039, 9.927),
    "skive": (56.567, 9.027),
    "slangerup": (55.847, 12.178),
    "slagelse": (55.403, 11.354),
    "sonderborg": (54.913, 9.792),
    "svendborg": (55.06, 10.607),
    "thisted": (56.956, 8.694),
    "tomsgarden": (55.705, 12.531),
    "tomsgaarden": (55.705, 12.531),
    "torring": (55.85, 9.48),
    "taastrup": (55.652, 12.293),
    "varde": (55.621, 8.481),
    "vesterbro": (55.669, 12.544),
    "vejle": (55.711, 9.536),
    "viborg": (56.452, 9.402),
    "aalborg ost": (57.044, 10.006),
    "aabenraa": (55.044, 9.418),
    "aars": (56.803, 9.514),
    "arhus nord": (56.187, 10.197),
    "arhus syd": (56.119, 10.158),
    "aasum odense": (55.396, 10.463),
    "åsum - odense": (55.396, 10.463),
    "asum odense": (55.396, 10.463),
}

PLACE_COORDINATES = {
    "aalborg": (57.048, 9.919),
    "aarhus": (56.162, 10.203),
    "aabenraa": (55.044, 9.418),
    "assens": (55.27, 9.9),
    "ballerup": (55.731, 12.363),
    "billund": (55.73, 9.112),
    "brondby": (55.647, 12.418),
    "bronderslev": (57.27, 9.941),
    "copenhagen": (55.676, 12.568),
    "esbjerg": (55.476, 8.459),
    "faelledvej": (55.696, 12.558),
    "farum": (55.808, 12.36),
    "fredericia": (55.565, 9.753),
    "frederiksberg": (55.681, 12.532),
    "frederikshavn": (57.441, 10.537),
    "frederikssund": (55.84, 12.069),
    "gladsaxe": (55.733, 12.489),
    "glostrup": (55.666, 12.398),
    "greve": (55.583, 12.298),
    "haderslev": (55.249, 9.489),
    "helsingor": (56.036, 12.613),
    "herlev": (55.724, 12.439),
    "herning": (56.138, 8.967),
    "hillerod": (55.927, 12.301),
    "hjorring": (57.456, 9.996),
    "hobro": (56.638, 9.794),
    "holbaek": (55.718, 11.704),
    "holstebro": (56.36, 8.616),
    "horsens": (55.861, 9.85),
    "hvidovre": (55.642, 12.475),
    "ishoj": (55.616, 12.351),
    "kalundborg": (55.681, 11.089),
    "kerteminde": (55.45, 10.657),
    "knebel": (56.205, 10.493),
    "kolding": (55.491, 9.473),
    "koge": (55.458, 12.182),
    "kobenhavn": (55.676, 12.568),
    "lemvig": (56.548, 8.31),
    "middelfart": (55.506, 9.731),
    "naestved": (55.229, 11.761),
    "nyborg": (55.312, 10.789),
    "nykobing falster": (54.769, 11.875),
    "odense": (55.403, 10.402),
    "randers": (56.46, 10.037),
    "ringkobing": (56.09, 8.244),
    "ringsted": (55.442, 11.79),
    "roskilde": (55.641, 12.087),
    "rudersdal": (55.838, 12.476),
    "silkeborg": (56.17, 9.545),
    "skanderborg": (56.039, 9.927),
    "skive": (56.567, 9.027),
    "slagelse": (55.403, 11.354),
    "store heddinge": (55.309, 12.388),
    "sonderborg": (54.913, 9.792),
    "sorø": (55.432, 11.559),
    "soro": (55.432, 11.559),
    "svendborg": (55.06, 10.607),
    "taarnby": (55.63, 12.6),
    "thisted": (56.956, 8.694),
    "varde": (55.621, 8.481),
    "vejen": (55.481, 9.137),
    "vejle": (55.711, 9.536),
    "viborg": (56.452, 9.402),
    "vordingborg": (55.009, 11.91),
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
    normalized = normalize_station_name(station)
    if not normalized:
        return DENMARK_CENTER
    if normalized in STATION_COORDINATES:
        return STATION_COORDINATES[normalized]

    for name, coordinates in sorted(
        {**PLACE_COORDINATES, **STATION_COORDINATES}.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        if re.search(rf"\b{re.escape(name)}\b", normalized):
            return coordinates
    return DENMARK_CENTER


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


def odin_severity(alarm_type: str) -> str:
    normalized = alarm_type.lower()
    if any(keyword in normalized for keyword in ("str. forurening", "kemikalie", "bygn.brand", "villa", "rækkehus")):
        return "high"
    if any(keyword in normalized for keyword in ("brand", "naturbrand", "forurening", "spild")):
        return "medium"
    return "low"
