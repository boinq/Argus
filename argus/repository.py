from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from argus.database import connect
from argus.models import AppSettings, AppSettingsUpdate, Event, EventCreate, EventUpdate


EVENT_COLUMNS = """
    id, title, category, severity, status, source, description, latitude,
    longitude, starts_at, ends_at, updated_at
"""


def _row_to_event(row: sqlite3.Row) -> Event:
    return Event.model_validate(dict(row))


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
    if "proxy_headers" in values:
        values["proxy_headers"] = values["proxy_headers"].lower() == "true"
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
