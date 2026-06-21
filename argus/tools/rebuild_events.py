from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from argus.database import connect, init_db
from argus.ingest import dmi, electricity, electricity_incidents, health, maritime, news, niord, odin, police, traffic
from argus.models import EventCreate
from argus.repository import delete_events_by_source, upsert_event


ArticleBuilder = Callable[[dict[str, Any]], EventCreate | None]
ObservationBuilder = Callable[[dict[str, Any], dict[str, Any]], EventCreate | None]


@dataclass(frozen=True)
class RebuildSource:
    id: str
    event_sources: tuple[str, ...]
    table: str
    builder: ArticleBuilder | ObservationBuilder


SOURCES: dict[str, RebuildSource] = {
    "dmi-metobs": RebuildSource(
        id="dmi-metobs",
        event_sources=("DMI metObs",),
        table="raw_observations",
        builder=lambda payload, row: dmi.event_from_observation(row),
    ),
    "energidataservice-elspot": RebuildSource(
        id="energidataservice-elspot",
        event_sources=("Energi Data Service",),
        table="raw_observations",
        builder=electricity.event_from_record,
    ),
    "dr-news": RebuildSource(
        id="dr-news",
        event_sources=("DR Nyheder",),
        table="raw_articles",
        builder=news.event_from_article,
    ),
    "greenpowerdenmark-incidents": RebuildSource(
        id="greenpowerdenmark-incidents",
        event_sources=(electricity_incidents.SOURCE_NAME,),
        table="raw_articles",
        builder=electricity_incidents.event_from_incident,
    ),
    "dma-news": RebuildSource(
        id="dma-news",
        event_sources=("Danish Maritime Authority",),
        table="raw_articles",
        builder=maritime.event_from_article,
    ),
    "niord-messages": RebuildSource(
        id="niord-messages",
        event_sources=(niord.SOURCE_NAME,),
        table="raw_articles",
        builder=niord.event_from_message,
    ),
    "odin-incidents": RebuildSource(
        id="odin-incidents",
        event_sources=(odin.SOURCE_NAME,),
        table="raw_articles",
        builder=odin.event_from_incident,
    ),
    "police-ritzau-short-messages": RebuildSource(
        id="police-ritzau-short-messages",
        event_sources=(police.SOURCE_NAME, *police.LEGACY_SOURCE_NAMES),
        table="raw_articles",
        builder=police.event_from_article,
    ),
    "trafikinfo-events": RebuildSource(
        id="trafikinfo-events",
        event_sources=("Vejdirektoratet Trafikinfo",),
        table="raw_articles",
        builder=traffic.event_from_feature,
    ),
    "health-alerts": RebuildSource(
        id="health-alerts",
        event_sources=("Sundhedsstyrelsen",),
        table="raw_articles",
        builder=health.event_from_article,
    ),
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild generated events from stored raw source data.")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Rebuild all supported sources with stored raw data.",
    )
    parser.add_argument(
        "--source",
        action="append",
        choices=sorted(SOURCES),
        help="Source id to rebuild. Can be passed more than once.",
    )
    args = parser.parse_args()

    if not args.all and not args.source:
        parser.error("pass --all or at least one --source")

    init_db()
    source_ids = sorted(SOURCES) if args.all else args.source
    for source_id in source_ids:
        result = rebuild_source(SOURCES[source_id])
        print(
            f"{result['source_id']}: raw={result['raw_rows']} "
            f"deleted={result['deleted']} created={result['created']} "
            f"updated={result['updated']} skipped={result['skipped']}"
        )


def rebuild_source(source: RebuildSource) -> dict[str, int | str]:
    rows = raw_rows(source)
    if not rows:
        return {
            "source_id": source.id,
            "raw_rows": 0,
            "deleted": 0,
            "created": 0,
            "updated": 0,
            "skipped": 0,
        }

    deleted = sum(delete_events_by_source(event_source) for event_source in source.event_sources)
    created = 0
    updated = 0
    skipped = 0

    for row in rows:
        try:
            event = build_event(source, row)
        except Exception:
            skipped += 1
            continue
        if event is None:
            skipped += 1
            continue
        _, was_created = upsert_event(event)
        if was_created:
            created += 1
        else:
            updated += 1

    return {
        "source_id": source.id,
        "raw_rows": len(rows),
        "deleted": deleted,
        "created": created,
        "updated": updated,
        "skipped": skipped,
    }


def raw_rows(source: RebuildSource) -> list[dict[str, Any]]:
    if source.table == "raw_articles":
        return list_raw_articles(source.id)
    return list_raw_observations(source.id)


def list_raw_articles(source_id: str) -> list[dict[str, Any]]:
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT payload
            FROM raw_articles
            WHERE source_id = ?
            ORDER BY published_at, created_at, id
            """,
            (source_id,),
        ).fetchall()
    return [json.loads(row["payload"]) for row in rows]


def list_raw_observations(source_id: str) -> list[dict[str, Any]]:
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT id, source_id, observed_at, parameter_id, station_id,
                   latitude, longitude, value, payload
            FROM raw_observations
            WHERE source_id = ?
            ORDER BY observed_at, created_at, id
            """,
            (source_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def build_event(source: RebuildSource, row: dict[str, Any]) -> EventCreate | None:
    if source.table == "raw_articles":
        return source.builder(row)  # type: ignore[misc]

    payload = json.loads(str(row.pop("payload")))
    return source.builder(payload, row)  # type: ignore[misc]


def supported_sources() -> Iterable[str]:
    return SOURCES.keys()


if __name__ == "__main__":
    main()
