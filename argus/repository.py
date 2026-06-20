from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from argus.database import connect
from argus.models import (
    AppSettings,
    AppSettingsUpdate,
    Event,
    EventCreate,
    EventUpdate,
    RawObservation,
    Source,
)


EVENT_COLUMNS = """
    id, title, category, severity, status, source, description, latitude,
    longitude, starts_at, ends_at, updated_at
"""


def _row_to_event(row: sqlite3.Row) -> Event:
    return Event.model_validate(dict(row))


def _row_to_source(row: sqlite3.Row) -> Source:
    return Source.model_validate(dict(row))


def _row_to_raw_observation(row: sqlite3.Row) -> RawObservation:
    return RawObservation.model_validate(dict(row))


def list_events() -> list[Event]:
    with connect() as connection:
        rows = connection.execute(
            f"SELECT {EVENT_COLUMNS} FROM events ORDER BY starts_at DESC"
        ).fetchall()
    return [_row_to_event(row) for row in rows]


def get_event(event_id: int) -> Event | None:
    with connect() as connection:
        row = connection.execute(
            f"SELECT {EVENT_COLUMNS} FROM events WHERE id = ?",
            (event_id,),
        ).fetchone()
    return _row_to_event(row) if row else None


def create_event(payload: EventCreate) -> Event:
    now = datetime.now(timezone.utc).isoformat()
    data = payload.model_dump(mode="json")
    with connect() as connection:
        cursor = connection.execute(
            """
            INSERT INTO events (
                title, category, severity, status, source, description, latitude,
                longitude, starts_at, ends_at, updated_at
            )
            VALUES (
                :title, :category, :severity, :status, :source, :description,
                :latitude, :longitude, :starts_at, :ends_at, :updated_at
            )
            """,
            {**data, "updated_at": now},
        )
        event_id = cursor.lastrowid
    event = get_event(int(event_id))
    if event is None:
        raise RuntimeError("created event could not be read")
    return event


def upsert_event(payload: EventCreate) -> tuple[Event, bool]:
    now = datetime.now(timezone.utc).isoformat()
    data = payload.model_dump(mode="json")
    with connect() as connection:
        existing = connection.execute(
            "SELECT id FROM events WHERE source = ? AND title = ?",
            (payload.source, payload.title),
        ).fetchone()
        if existing:
            connection.execute(
                """
                UPDATE events SET
                    category = :category,
                    severity = :severity,
                    status = :status,
                    description = :description,
                    latitude = :latitude,
                    longitude = :longitude,
                    starts_at = :starts_at,
                    ends_at = :ends_at,
                    updated_at = :updated_at
                WHERE id = :id
                """,
                {**data, "updated_at": now, "id": existing["id"]},
            )
            event_id = int(existing["id"])
            created = False
        else:
            cursor = connection.execute(
                """
                INSERT INTO events (
                    title, category, severity, status, source, description,
                    latitude, longitude, starts_at, ends_at, updated_at
                )
                VALUES (
                    :title, :category, :severity, :status, :source,
                    :description, :latitude, :longitude, :starts_at,
                    :ends_at, :updated_at
                )
                """,
                {**data, "updated_at": now},
            )
            event_id = int(cursor.lastrowid)
            created = True
    event = get_event(event_id)
    if event is None:
        raise RuntimeError("upserted event could not be read")
    return event, created


def update_event(event_id: int, payload: EventUpdate) -> Event | None:
    changes = payload.model_dump(exclude_unset=True, mode="json")
    if not changes:
        return get_event(event_id)

    changes["updated_at"] = datetime.now(timezone.utc).isoformat()
    assignments = ", ".join(f"{key} = :{key}" for key in changes)
    with connect() as connection:
        cursor = connection.execute(
            f"UPDATE events SET {assignments} WHERE id = :id",
            {**changes, "id": event_id},
        )
        if cursor.rowcount == 0:
            return None
    return get_event(event_id)


def get_settings() -> AppSettings:
    with connect() as connection:
        rows = connection.execute("SELECT key, value FROM app_settings").fetchall()
    values = {row["key"]: row["value"] for row in rows}
    for key in ("proxy_headers", "ntfy_enabled"):
        if key in values:
            values[key] = values[key].lower() == "true"
    return AppSettings.model_validate(values)


def update_settings(payload: AppSettingsUpdate) -> AppSettings:
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        return get_settings()

    rows = [
        (key, "true" if value is True else "false" if value is False else str(value))
        for key, value in changes.items()
        if value is not None
    ]
    with connect() as connection:
        connection.executemany(
            """
            INSERT INTO app_settings (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            rows,
        )
    return get_settings()


def list_sources() -> list[Source]:
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT id, name, type, status, coverage, cadence, endpoint,
                   last_check, last_success, last_error, updated_at
            FROM sources
            ORDER BY name
            """
        ).fetchall()
    return [_row_to_source(row) for row in rows]


def list_recent_observations(
    *,
    source_id: str | None = None,
    station_id: str | None = None,
    limit: int = 500,
) -> list[RawObservation]:
    limit = max(1, min(limit, 2000))
    clauses: list[str] = []
    params: list[object] = []
    if source_id:
        clauses.append("source_id = ?")
        params.append(source_id)
    if station_id:
        clauses.append("station_id = ?")
        params.append(station_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    with connect() as connection:
        rows = connection.execute(
            f"""
            SELECT id, source_id, observed_at, parameter_id, station_id,
                   latitude, longitude, value, created_at
            FROM raw_observations
            {where}
            ORDER BY observed_at DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    return [_row_to_raw_observation(row) for row in rows]


def update_source_status(
    source_id: str,
    status: str,
    *,
    last_error: str | None = None,
    success: bool = False,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with connect() as connection:
        connection.execute(
            """
            UPDATE sources SET
                status = ?,
                last_check = ?,
                last_success = CASE WHEN ? THEN ? ELSE last_success END,
                last_error = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (status, now, success, now, last_error, now, source_id),
        )


def insert_raw_observation(
    *,
    observation_id: str,
    source_id: str,
    observed_at: str,
    parameter_id: str,
    station_id: str,
    latitude: float,
    longitude: float,
    value: float,
    payload: str,
) -> bool:
    now = datetime.now(timezone.utc).isoformat()
    with connect() as connection:
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO raw_observations (
                id, source_id, observed_at, parameter_id, station_id,
                latitude, longitude, value, payload, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                observation_id,
                source_id,
                observed_at,
                parameter_id,
                station_id,
                latitude,
                longitude,
                value,
                payload,
                now,
            ),
        )
    return cursor.rowcount > 0


def insert_raw_article(
    *,
    article_id: str,
    source_id: str,
    title: str,
    url: str,
    published_at: str | None,
    summary: str,
    payload: str,
) -> bool:
    now = datetime.now(timezone.utc).isoformat()
    with connect() as connection:
        cursor = connection.execute(
            """
            INSERT INTO raw_articles (
                id, source_id, title, url, published_at, summary, payload, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                source_id = excluded.source_id,
                title = excluded.title,
                url = excluded.url,
                published_at = excluded.published_at,
                summary = excluded.summary,
                payload = excluded.payload
            """,
            (article_id, source_id, title, url, published_at, summary, payload, now),
        )
    return cursor.rowcount > 0


def delete_events_by_source(source: str) -> int:
    with connect() as connection:
        cursor = connection.execute("DELETE FROM events WHERE source = ?", (source,))
    return cursor.rowcount
