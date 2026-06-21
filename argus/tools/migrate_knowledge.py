from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from typing import Any

from argus.database import connect, init_db
from argus.repository import (
    record_classification_term_candidates_in_connection,
    upsert_location_alias,
    upsert_location_alias_in_connection,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate stored raw data into database-backed knowledge tables.")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Scan all stored raw articles and observations.",
    )
    args = parser.parse_args()
    if not args.all:
        parser.error("pass --all")

    init_db()
    result = migrate_knowledge()
    print(
        f"articles={result['articles']} observations={result['observations']} "
        f"term_candidates={result['term_candidates']} "
        f"location_aliases={result['location_aliases']}"
    )


def migrate_knowledge() -> dict[str, int]:
    article_rows = raw_articles()
    observation_rows = raw_observations()
    term_candidates_before = count_rows("classification_term_candidates")
    location_aliases_before = count_rows("location_aliases")

    with connect() as connection:
        now = datetime.now(timezone.utc).isoformat()
        for row in article_rows:
            record_classification_term_candidates_in_connection(
                connection,
                source_id=str(row["source_id"]),
                title=str(row["title"]),
                text=f"{row['title']} {row['summary']}",
                now=now,
            )
            learn_article_locations(row, connection=connection)

        for row in observation_rows:
            upsert_location_alias_in_connection(
                connection,
                kind="station",
                name=str(row["station_id"]),
                latitude=float(row["latitude"]),
                longitude=float(row["longitude"]),
                source="learned",
            )

    return {
        "articles": len(article_rows),
        "observations": len(observation_rows),
        "term_candidates": count_rows("classification_term_candidates") - term_candidates_before,
        "location_aliases": count_rows("location_aliases") - location_aliases_before,
    }


def raw_articles() -> list[dict[str, Any]]:
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT source_id, title, summary, payload
            FROM raw_articles
            ORDER BY created_at, id
            """
        ).fetchall()
    return [dict(row) for row in rows]


def raw_observations() -> list[dict[str, Any]]:
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT station_id, latitude, longitude
            FROM raw_observations
            ORDER BY created_at, id
            """
        ).fetchall()
    return [dict(row) for row in rows]


def learn_article_locations(row: dict[str, Any], *, connection: Any | None = None) -> None:
    try:
        payload = json.loads(str(row["payload"]))
    except (TypeError, ValueError):
        return

    if row["source_id"] == "greenpowerdenmark-incidents":
        learn_coordinate_payload_location(
            payload,
            name=str(payload.get("title") or payload.get("supplierName") or ""),
            latitude_key="centerLat",
            longitude_key="centerLng",
            kind="place",
            connection=connection,
        )


def learn_coordinate_payload_location(
    payload: dict[str, Any],
    *,
    name: str,
    latitude_key: str,
    longitude_key: str,
    kind: str,
    connection: Any | None = None,
) -> None:
    if not name:
        return
    try:
        latitude = float(payload.get(latitude_key))
        longitude = float(payload.get(longitude_key))
    except (TypeError, ValueError):
        return
    if not (54.4 <= latitude <= 58.2 and 7.7 <= longitude <= 15.4):
        return
    if connection is None:
        upsert_location_alias(
            kind=kind,
            name=name,
            latitude=latitude,
            longitude=longitude,
            source="learned",
        )
    else:
        upsert_location_alias_in_connection(
            connection,
            kind=kind,
            name=name,
            latitude=latitude,
            longitude=longitude,
            source="learned",
        )


def count_rows(table: str) -> int:
    if table not in {"classification_terms", "classification_term_candidates", "location_aliases"}:
        raise ValueError(f"unsupported table: {table}")
    with connect() as connection:
        row = connection.execute(f"SELECT count(*) AS count FROM {table}").fetchone()
    return int(row["count"])


if __name__ == "__main__":
    main()
