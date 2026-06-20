from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from argus.models import EventCreate, IngestResult
from argus.repository import insert_raw_observation, update_source_status, upsert_event


SOURCE_ID = "dmi-metobs"
ENDPOINT = "https://dmigw.govcloud.dk/v2/metObs/collections/observation/items"
PARAMETERS = ("wind_speed", "wind_gust_always_past1h", "precip_past10min", "temp_dry")
DENMARK_BBOX = "7.7,54.4,15.4,58.2"


def sync_dmi_observations(limit: int = 500) -> IngestResult:
    try:
        features = fetch_observations(limit=limit)
    except httpx.HTTPError as error:
        update_source_status(SOURCE_ID, "error", last_error=str(error))
        return IngestResult(
            source_id=SOURCE_ID,
            observations_seen=0,
            observations_stored=0,
            events_created=0,
            events_updated=0,
            message=f"DMI request failed: {error}",
        )

    stored = 0
    created = 0
    updated = 0
    for feature in features:
        observation = parse_observation(feature)
        if observation is None:
            continue
        if insert_raw_observation(**observation, payload=json.dumps(feature)):
            stored += 1

        event = event_from_observation(observation)
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
        message="DMI observations synced.",
    )


def fetch_observations(limit: int) -> list[dict[str, Any]]:
    start = datetime.now(timezone.utc) - timedelta(hours=3)
    features: list[dict[str, Any]] = []
    with httpx.Client(timeout=20.0) as client:
        for parameter in PARAMETERS:
            params = {
                "bbox": DENMARK_BBOX,
                "limit": max(1, limit // len(PARAMETERS)),
                "parameterId": parameter,
                "datetime": f"{start.isoformat().replace('+00:00', 'Z')}/..",
            }
            response = client.get(ENDPOINT, params=params)
            response.raise_for_status()
            data = response.json()
            features.extend(data.get("features", []))
    return features


def parse_observation(feature: dict[str, Any]) -> dict[str, Any] | None:
    properties = feature.get("properties") or {}
    geometry = feature.get("geometry") or {}
    coordinates = geometry.get("coordinates") or []
    if len(coordinates) < 2:
        return None

    value = properties.get("value")
    observed_at = properties.get("observed")
    parameter_id = properties.get("parameterId")
    station_id = properties.get("stationId")
    if value is None or not observed_at or not parameter_id or not station_id:
        return None

    try:
        numeric_value = float(value)
        longitude = float(coordinates[0])
        latitude = float(coordinates[1])
    except (TypeError, ValueError):
        return None

    return {
        "observation_id": str(feature.get("id") or f"{station_id}:{parameter_id}:{observed_at}"),
        "source_id": SOURCE_ID,
        "observed_at": observed_at,
        "parameter_id": str(parameter_id),
        "station_id": str(station_id),
        "latitude": latitude,
        "longitude": longitude,
        "value": numeric_value,
    }


def event_from_observation(observation: dict[str, Any]) -> EventCreate | None:
    parameter = observation["parameter_id"]
    value = observation["value"]

    if parameter == "wind_gust_always_past1h" and value >= 24.5:
        severity = "critical" if value >= 32.7 else "high"
        title = f"DMI wind gust threshold at station {observation['station_id']}"
        description = f"DMI observed wind gusts of {value:.1f} m/s within the past hour."
    elif parameter == "wind_speed" and value >= 17.2:
        severity = "high" if value >= 24.5 else "medium"
        title = f"DMI strong wind threshold at station {observation['station_id']}"
        description = f"DMI observed sustained wind of {value:.1f} m/s."
    elif parameter == "precip_past10min" and value >= 5:
        severity = "high" if value >= 15 else "medium"
        title = f"DMI heavy precipitation threshold at station {observation['station_id']}"
        description = f"DMI observed {value:.1f} mm precipitation in 10 minutes."
    elif parameter == "temp_dry" and (value <= -10 or value >= 30):
        severity = "high" if value <= -15 or value >= 35 else "medium"
        title = f"DMI temperature threshold at station {observation['station_id']}"
        description = f"DMI observed air temperature of {value:.1f} C."
    else:
        return None

    starts_at = datetime.fromisoformat(observation["observed_at"].replace("Z", "+00:00"))
    ends_at = starts_at + timedelta(hours=2)
    return EventCreate(
        title=title,
        category="weather",
        severity=severity,
        status="current",
        source="DMI metObs",
        description=description,
        latitude=observation["latitude"],
        longitude=observation["longitude"],
        starts_at=starts_at,
        ends_at=ends_at.astimezone(timezone.utc),
    )
