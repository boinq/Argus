from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from argus.ingest.common import parse_iso_datetime
from argus.models import EventCreate, IngestResult
from argus.repository import (
    get_location_alias,
    insert_raw_observation,
    update_source_status,
    upsert_event,
)


SOURCE_ID = "energidataservice-elspot"
ENDPOINT = "https://api.energidataservice.dk/dataset/Elspotprices"


def sync_electricity(limit: int = 20) -> IngestResult:
    try:
        records = fetch_elspot_records(limit=limit)
    except httpx.HTTPError as error:
        update_source_status(SOURCE_ID, "error", last_error=str(error))
        return IngestResult(
            source_id=SOURCE_ID,
            observations_seen=0,
            observations_stored=0,
            events_created=0,
            events_updated=0,
            message=f"Energi Data Service request failed: {error}",
        )

    stored = 0
    created = 0
    updated = 0
    for record in records:
        observation = parse_elspot_record(record)
        if observation is None:
            continue
        if insert_raw_observation(**observation, payload=json.dumps(record)):
            stored += 1

        event = event_from_record(record, observation)
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
        observations_seen=len(records),
        observations_stored=stored,
        events_created=created,
        events_updated=updated,
        message="Energi Data Service electricity telemetry synced.",
    )


def fetch_elspot_records(limit: int) -> list[dict[str, Any]]:
    with httpx.Client(timeout=20.0) as client:
        response = client.get(
            ENDPOINT,
            params={"limit": limit},
            headers={"User-Agent": "Argus/0.1 Denmark hazard monitor"},
        )
        response.raise_for_status()
    records = response.json().get("records", [])
    return [
        record
        for record in records
        if area_coordinates(str(record.get("PriceArea") or "")) is not None
    ]


def parse_elspot_record(record: dict[str, Any]) -> dict[str, Any] | None:
    area = record.get("PriceArea")
    hour = record.get("HourUTC")
    price = record.get("SpotPriceDKK")
    if not area or not hour or price is None:
        return None
    location = area_coordinates(str(area))
    if location is None:
        return None
    observed_at = parse_iso_datetime(str(hour))
    if observed_at is None:
        return None
    try:
        numeric_price = float(price)
    except (TypeError, ValueError):
        return None
    latitude, longitude = location
    return {
        "observation_id": f"{SOURCE_ID}:{area}:{observed_at.isoformat()}",
        "source_id": SOURCE_ID,
        "observed_at": observed_at.isoformat(),
        "parameter_id": "elspot_price_dkk_mwh",
        "station_id": str(area),
        "latitude": latitude,
        "longitude": longitude,
        "value": numeric_price,
    }


def area_coordinates(area: str) -> tuple[float, float] | None:
    return get_location_alias("electricity_area", area)


def event_from_record(record: dict[str, Any], observation: dict[str, Any]) -> EventCreate | None:
    price = observation["value"]
    if price < 2500:
        return None
    severity = "critical" if price >= 5000 else "high"
    starts_at = datetime.fromisoformat(observation["observed_at"])
    area = observation["station_id"]
    return EventCreate(
        title=f"Electricity price stress in {area}",
        category="electrical",
        severity=severity,
        status="monitoring",
        source="Energi Data Service",
        description=(
            f"Elspot price for {area} reached {price:.0f} DKK/MWh. "
            "This is a market stress signal, not a confirmed outage."
        ),
        latitude=observation["latitude"],
        longitude=observation["longitude"],
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=1),
    )
