from __future__ import annotations

import os
import socket
import sqlite3
from datetime import datetime, timezone
from typing import Sequence

import httpx

from argus.database import connect, db_path, init_db
from argus.knowledge import extract_candidate_terms, normalize_location_name
from argus.models import (
    AppSettings,
    AppSettingsUpdate,
    Event,
    EventCreate,
    EventUpdate,
    RawObservation,
    SensorStatus,
    Source,
)


EVENT_COLUMNS = """
    id, title, category, severity, status, source, description, latitude,
    longitude, starts_at, ends_at, updated_at
"""


def remote_web_url() -> str:
    return os.getenv("ARGUS_WEB_URL", "").rstrip("/")


def using_remote_repository() -> bool:
    return bool(remote_web_url())


def remote_headers() -> dict[str, str]:
    token = os.getenv("ARGUS_SENSOR_TOKEN", "")
    headers = {"X-Argus-Sensor-Id": os.getenv("ARGUS_SENSOR_ID", socket.gethostname())}
    if token:
        headers["X-Argus-Sensor-Token"] = token
    return headers


def remote_request(
    method: str,
    path: str,
    *,
    json_payload: dict[str, object] | None = None,
    params: dict[str, object] | None = None,
) -> object:
    url = f"{remote_web_url()}{path}"
    with httpx.Client(timeout=30.0, headers=remote_headers()) as client:
        response = client.request(method, url, json=json_payload, params=params)
        response.raise_for_status()
        if response.content:
            return response.json()
        return {}


def _row_to_event(row: sqlite3.Row) -> Event:
    return Event.model_validate(dict(row))


def _row_to_source(row: sqlite3.Row) -> Source:
    return Source.model_validate(dict(row))


def _row_to_raw_observation(row: sqlite3.Row) -> RawObservation:
    return RawObservation.model_validate(dict(row))


def _row_to_sensor_status(row: sqlite3.Row) -> SensorStatus:
    return SensorStatus.model_validate(dict(row))


def list_events() -> list[Event]:
    with connect() as connection:
        rows = connection.execute(
            f"SELECT {EVENT_COLUMNS} FROM events ORDER BY starts_at DESC"
        ).fetchall()
    return [_row_to_event(row) for row in rows]


def list_event_training_examples() -> list[sqlite3.Row]:
    with connect() as connection:
        return connection.execute(
            """
            SELECT title, description, category, severity
            FROM events
            WHERE source NOT LIKE 'Operator%'
            ORDER BY updated_at DESC
            LIMIT 2000
            """
        ).fetchall()


def ml_overview() -> dict[str, object]:
    with connect() as connection:
        event_count = connection.execute("SELECT count(*) AS count FROM events").fetchone()["count"]
        candidate_count = connection.execute(
            "SELECT count(*) AS count FROM classification_term_candidates"
        ).fetchone()["count"]
        active_term_count = connection.execute(
            "SELECT count(*) AS count FROM classification_terms"
        ).fetchone()["count"]
        learned_term_count = connection.execute(
            "SELECT count(*) AS count FROM classification_terms WHERE source = 'learned'"
        ).fetchone()["count"]
        categories = connection.execute(
            """
            SELECT category, count(*) AS count
            FROM events
            GROUP BY category
            ORDER BY count DESC, category
            """
        ).fetchall()
        severities = connection.execute(
            """
            SELECT severity, count(*) AS count
            FROM events
            GROUP BY severity
            ORDER BY count DESC, severity
            """
        ).fetchall()
    return {
        "events": int(event_count),
        "candidate_terms": int(candidate_count),
        "active_terms": int(active_term_count),
        "learned_terms": int(learned_term_count),
        "categories": [dict(row) for row in categories],
        "severities": [dict(row) for row in severities],
    }


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
    if using_remote_repository():
        response = remote_request(
            "POST",
            "/api/sensor/events",
            json_payload=payload.model_dump(mode="json"),
        )
        data = dict(response)  # type: ignore[arg-type]
        return Event.model_validate(data["event"]), bool(data["created"])

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


def learn_terms_from_event(payload: EventCreate) -> None:
    source_id = source_id_from_event_source(payload.source)
    rule_group = rule_group_from_event(source_id)
    if source_id is None or rule_group is None:
        return
    category = payload.category if rule_group in {"category", "event", "promote", "maritime"} else ""
    severity = payload.severity if rule_group in {"severity", "event", "promote"} else ""
    terms = extract_candidate_terms(f"{payload.title} {payload.description}", limit=12)
    now = datetime.now(timezone.utc).isoformat()
    with connect() as connection:
        connection.executemany(
            """
            INSERT INTO classification_terms (
                source_id, rule_group, term, category, severity, score, source, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, 'learned', ?)
            ON CONFLICT(source_id, rule_group, term) DO UPDATE SET
                category = CASE
                    WHEN classification_terms.source IN ('learned', 'candidate') THEN excluded.category
                    ELSE classification_terms.category
                END,
                severity = CASE
                    WHEN classification_terms.source IN ('learned', 'candidate') THEN excluded.severity
                    ELSE classification_terms.severity
                END,
                score = CASE
                    WHEN classification_terms.source IN ('learned', 'candidate')
                    THEN max(classification_terms.score, excluded.score)
                    ELSE classification_terms.score
                END,
                updated_at = excluded.updated_at
            """,
            [
                (source_id, rule_group, term, category, severity, learned_term_score(term), now)
                for term in terms
            ],
        )


def upsert_classification_term(
    *,
    source_id: str,
    rule_group: str,
    term: str,
    category: str = "",
    severity: str = "",
    score: int = 1,
    source: str = "learned",
) -> None:
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO classification_terms (
                source_id, rule_group, term, category, severity, score, source, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(source_id, rule_group, term) DO UPDATE SET
                category = excluded.category,
                severity = excluded.severity,
                score = excluded.score,
                source = excluded.source,
                updated_at = datetime('now')
            """,
            (source_id, rule_group, term, category, severity, score, source),
        )


def list_classification_term_candidates(
    *,
    source_id: str | None = None,
    limit: int = 80,
) -> list[sqlite3.Row]:
    clauses: list[str] = []
    params: list[object] = []
    if source_id:
        clauses.append("source_id = ?")
        params.append(source_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(max(1, min(limit, 250)))
    with connect() as connection:
        return connection.execute(
            f"""
            SELECT source_id, term, normalized_term, seen_count, sample_title,
                   first_seen, last_seen
            FROM classification_term_candidates
            {where}
            ORDER BY seen_count DESC, length(term) DESC, last_seen DESC
            LIMIT ?
            """,
            params,
        ).fetchall()


def list_active_classification_terms(
    *,
    source_id: str | None = None,
    limit: int = 120,
) -> list[sqlite3.Row]:
    clauses: list[str] = []
    params: list[object] = []
    if source_id:
        clauses.append("source_id = ?")
        params.append(source_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(max(1, min(limit, 500)))
    with connect() as connection:
        return connection.execute(
            f"""
            SELECT source_id, rule_group, term, category, severity, score, source, updated_at
            FROM classification_terms
            {where}
            ORDER BY updated_at DESC, score DESC, source_id, rule_group, term
            LIMIT ?
            """,
            params,
        ).fetchall()


def promote_classification_candidate(
    *,
    source_id: str,
    rule_group: str,
    term: str,
    category: str = "",
    severity: str = "",
    score: int = 1,
) -> None:
    upsert_classification_term(
        source_id=source_id,
        rule_group=rule_group,
        term=term,
        category=category,
        severity=severity,
        score=score,
        source="reviewed",
    )
    with connect() as connection:
        connection.execute(
            """
            DELETE FROM classification_term_candidates
            WHERE source_id = ? AND normalized_term = ?
            """,
            (source_id, normalize_location_name(term)),
        )


def delete_learned_classification_terms() -> int:
    with connect() as connection:
        cursor = connection.execute("DELETE FROM classification_terms WHERE source = 'learned'")
    return cursor.rowcount


def source_id_from_event_source(source: str) -> str | None:
    normalized = source.casefold()
    with connect() as connection:
        exact = connection.execute(
            "SELECT id FROM sources WHERE lower(name) = lower(?) LIMIT 1",
            (source,),
        ).fetchone()
        if exact is not None:
            return str(exact["id"])
        rows = connection.execute("SELECT id, name FROM sources").fetchall()
    for row in rows:
        name = str(row["name"]).casefold()
        if name in normalized or normalized in name:
            return str(row["id"])
    return None


def rule_group_from_event(source_id: str | None) -> str | None:
    if source_id is None:
        return None
    if source_id == "dr-news":
        return "category"
    if source_id == "dma-news":
        return "maritime"
    if source_id == "police-ritzau-short-messages":
        return "event"
    if source_id == "health-alerts":
        return "promote"
    if source_id in {"trafikinfo-events", "odin-incidents", "niord-messages"}:
        return "severity"
    return None


def learned_term_score(term: str) -> int:
    words = term.split()
    return max(1, min(5, len(words) + 1))


def reset_database() -> None:
    path = db_path()
    if path.exists():
        path.unlink()
    init_db()


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


def list_sensor_statuses() -> list[SensorStatus]:
    with connect() as connection:
        ensure_sensor_heartbeats_table(connection)
        rows = connection.execute(
            """
            SELECT sensor_id, label, last_seen, last_source_id, total_posts,
                   total_observations, total_articles, total_events,
                   total_status_updates, total_scheduler_updates
            FROM sensor_heartbeats
            ORDER BY last_seen DESC, sensor_id
            """
        ).fetchall()
    return [_row_to_sensor_status(row) for row in rows]


def record_sensor_acquisition(
    *,
    sensor_id: str,
    acquisition_type: str,
    source_id: str | None = None,
    count: int = 1,
) -> None:
    safe_sensor_id = normalize_sensor_id(sensor_id)
    if not safe_sensor_id:
        return
    count = max(0, count)
    now = datetime.now(timezone.utc).isoformat()
    column = {
        "observation": "total_observations",
        "article": "total_articles",
        "event": "total_events",
        "source_status": "total_status_updates",
        "scheduler_status": "total_scheduler_updates",
    }.get(acquisition_type)
    with connect() as connection:
        ensure_sensor_heartbeats_table(connection)
        connection.execute(
            """
            INSERT INTO sensor_heartbeats (
                sensor_id, label, last_seen, last_source_id, total_posts,
                total_observations, total_articles, total_events,
                total_status_updates, total_scheduler_updates
            )
            VALUES (?, ?, ?, ?, 0, 0, 0, 0, 0, 0)
            ON CONFLICT(sensor_id) DO UPDATE SET
                last_seen = excluded.last_seen,
                last_source_id = excluded.last_source_id
            """,
            (safe_sensor_id, safe_sensor_id, now, source_id),
        )
        connection.execute(
            """
            UPDATE sensor_heartbeats
            SET total_posts = total_posts + ?,
                total_observations = total_observations + ?,
                total_articles = total_articles + ?,
                total_events = total_events + ?,
                total_status_updates = total_status_updates + ?,
                total_scheduler_updates = total_scheduler_updates + ?
            WHERE sensor_id = ?
            """,
            (
                count if count else 1,
                count if column == "total_observations" else 0,
                count if column == "total_articles" else 0,
                count if column == "total_events" else 0,
                1 if column == "total_status_updates" else 0,
                1 if column == "total_scheduler_updates" else 0,
                safe_sensor_id,
            ),
        )


def ensure_sensor_heartbeats_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS sensor_heartbeats (
            sensor_id TEXT PRIMARY KEY,
            label TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            last_source_id TEXT,
            total_posts INTEGER NOT NULL DEFAULT 0,
            total_observations INTEGER NOT NULL DEFAULT 0,
            total_articles INTEGER NOT NULL DEFAULT 0,
            total_events INTEGER NOT NULL DEFAULT 0,
            total_status_updates INTEGER NOT NULL DEFAULT 0,
            total_scheduler_updates INTEGER NOT NULL DEFAULT 0
        )
        """
    )


def normalize_sensor_id(sensor_id: str) -> str:
    return " ".join(str(sensor_id or "").strip().split())[:120]


def update_source_status(
    source_id: str,
    status: str,
    *,
    last_error: str | None = None,
    success: bool = False,
) -> None:
    if using_remote_repository():
        remote_request(
            "POST",
            "/api/sensor/source-status",
            json_payload={
                "source_id": source_id,
                "status": status,
                "last_error": last_error,
                "success": success,
            },
        )
        return

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
    if using_remote_repository():
        response = remote_request(
            "POST",
            "/api/sensor/raw-observations",
            json_payload={
                "observation_id": observation_id,
                "source_id": source_id,
                "observed_at": observed_at,
                "parameter_id": parameter_id,
                "station_id": station_id,
                "latitude": latitude,
                "longitude": longitude,
                "value": value,
                "payload": payload,
            },
        )
        return bool(dict(response).get("inserted"))  # type: ignore[arg-type]

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
        was_inserted = cursor.rowcount > 0
        upsert_location_alias_in_connection(
            connection,
            kind="station",
            name=station_id,
            latitude=latitude,
            longitude=longitude,
            source="learned",
        )
    return was_inserted


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
    if using_remote_repository():
        response = remote_request(
            "POST",
            "/api/sensor/raw-articles",
            json_payload={
                "article_id": article_id,
                "source_id": source_id,
                "title": title,
                "url": url,
                "published_at": published_at,
                "summary": summary,
                "payload": payload,
            },
        )
        return bool(dict(response).get("inserted"))  # type: ignore[arg-type]

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
        was_changed = cursor.rowcount > 0
        record_classification_term_candidates_in_connection(
            connection,
            source_id=source_id,
            title=title,
            text=f"{title} {summary}",
            now=now,
        )
    return was_changed


def delete_events_by_source(source: str) -> int:
    if using_remote_repository():
        response = remote_request(
            "POST",
            "/api/sensor/events/delete-by-source",
            json_payload={"source": source},
        )
        return int(dict(response).get("deleted", 0))  # type: ignore[arg-type]

    with connect() as connection:
        cursor = connection.execute("DELETE FROM events WHERE source = ?", (source,))
    return cursor.rowcount


def find_location_alias(
    normalized_name: str,
    *,
    kinds: Sequence[str],
) -> tuple[float, float] | None:
    if not normalized_name or not kinds:
        return None
    placeholders = ",".join("?" for _ in kinds)
    with connect() as connection:
        row = connection.execute(
            f"""
            SELECT latitude, longitude
            FROM location_aliases
            WHERE normalized_name = ?
              AND kind IN ({placeholders})
            ORDER BY
              CASE kind
                WHEN 'station' THEN 0
                WHEN 'place' THEN 1
                WHEN 'beredskab' THEN 2
                ELSE 3
              END
            LIMIT 1
            """,
            (normalized_name, *kinds),
        ).fetchone()
    if row is None:
        return None
    return (float(row["latitude"]), float(row["longitude"]))


def get_location_alias(kind: str, name: str) -> tuple[float, float] | None:
    if using_remote_repository():
        response = remote_request(
            "GET",
            "/api/sensor/location-alias",
            params={"kind": kind, "name": name},
        )
        location = dict(response).get("location")  # type: ignore[arg-type]
        return tuple(location) if location else None  # type: ignore[return-value]

    normalized_name = normalize_location_name(name)
    with connect() as connection:
        row = connection.execute(
            """
            SELECT latitude, longitude
            FROM location_aliases
            WHERE kind = ?
              AND normalized_name = ?
            LIMIT 1
            """,
            (kind, normalized_name),
        ).fetchone()
    if row is None:
        return None
    return (float(row["latitude"]), float(row["longitude"]))


def get_fallback_location() -> tuple[float, float] | None:
    if using_remote_repository():
        response = remote_request("GET", "/api/sensor/fallback-location")
        location = dict(response).get("location")  # type: ignore[arg-type]
        return tuple(location) if location else None  # type: ignore[return-value]

    with connect() as connection:
        row = connection.execute(
            """
            SELECT avg(latitude) AS latitude, avg(longitude) AS longitude
            FROM location_aliases
            WHERE source NOT IN ('seed', 'bootstrap')
            """
        ).fetchone()
        if row and row["latitude"] is not None and row["longitude"] is not None:
            return (float(row["latitude"]), float(row["longitude"]))
        row = connection.execute(
            """
            SELECT avg(latitude) AS latitude, avg(longitude) AS longitude
            FROM events
            """
        ).fetchone()
    if row and row["latitude"] is not None and row["longitude"] is not None:
        return (float(row["latitude"]), float(row["longitude"]))
    return None


def upsert_location_alias(
    *,
    kind: str,
    name: str,
    latitude: float,
    longitude: float,
    source: str = "learned",
) -> None:
    if using_remote_repository():
        remote_request(
            "POST",
            "/api/sensor/location-aliases",
            json_payload={
                "kind": kind,
                "name": name,
                "latitude": latitude,
                "longitude": longitude,
                "source": source,
            },
        )
        return

    with connect() as connection:
        upsert_location_alias_in_connection(
            connection,
            kind=kind,
            name=name,
            latitude=latitude,
            longitude=longitude,
            source=source,
        )


def upsert_location_alias_in_connection(
    connection: sqlite3.Connection,
    *,
    kind: str,
    name: str,
    latitude: float,
    longitude: float,
    source: str,
) -> None:
    normalized_name = normalize_location_name(name)
    if not normalized_name:
        return
    connection.execute(
        """
        INSERT INTO location_aliases (
            kind, name, normalized_name, latitude, longitude, source, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(kind, normalized_name) DO UPDATE SET
            name = CASE
                WHEN location_aliases.source IN ('seed', 'bootstrap', 'learned') THEN excluded.name
                ELSE location_aliases.name
            END,
            latitude = CASE
                WHEN location_aliases.source IN ('seed', 'bootstrap', 'learned') THEN excluded.latitude
                ELSE location_aliases.latitude
            END,
            longitude = CASE
                WHEN location_aliases.source IN ('seed', 'bootstrap', 'learned') THEN excluded.longitude
                ELSE location_aliases.longitude
            END,
            source = CASE
                WHEN location_aliases.source IN ('seed', 'bootstrap') THEN location_aliases.source
                ELSE excluded.source
            END,
            updated_at = datetime('now')
        """,
        (kind, name, normalized_name, latitude, longitude, source),
    )


def list_location_aliases(*, kinds: Sequence[str]) -> list[sqlite3.Row]:
    if not kinds:
        return []
    if using_remote_repository():
        response = remote_request(
            "GET",
            "/api/sensor/location-aliases",
            params={"kinds": list(kinds)},
        )
        return list(response)  # type: ignore[arg-type,return-value]

    placeholders = ",".join("?" for _ in kinds)
    with connect() as connection:
        rows = connection.execute(
            f"""
            SELECT kind, name, normalized_name, latitude, longitude
            FROM location_aliases
            WHERE kind IN ({placeholders})
            ORDER BY length(normalized_name) DESC
            """,
            tuple(kinds),
        ).fetchall()
    return rows


def record_location_candidate(
    *,
    source_id: str,
    kind: str,
    name: str,
    normalized_name: str,
    context: str,
) -> None:
    if using_remote_repository():
        remote_request(
            "POST",
            "/api/sensor/location-candidates",
            json_payload={
                "source_id": source_id,
                "kind": kind,
                "name": name,
                "normalized_name": normalized_name,
                "context": context,
            },
        )
        return

    if not normalized_name:
        return
    now = datetime.now(timezone.utc).isoformat()
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO location_candidates (
                source_id, kind, name, normalized_name, context,
                seen_count, first_seen, last_seen
            )
            VALUES (?, ?, ?, ?, ?, 1, ?, ?)
            ON CONFLICT(source_id, kind, normalized_name) DO UPDATE SET
                name = excluded.name,
                context = excluded.context,
                seen_count = location_candidates.seen_count + 1,
                last_seen = excluded.last_seen
            """,
            (source_id, kind, name, normalized_name, context[:1000], now, now),
        )


def record_classification_term_candidates(
    *,
    source_id: str,
    title: str,
    text: str,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with connect() as connection:
        record_classification_term_candidates_in_connection(
            connection,
            source_id=source_id,
            title=title,
            text=text,
            now=now,
        )


def record_classification_term_candidates_in_connection(
    connection: sqlite3.Connection,
    *,
    source_id: str,
    title: str,
    text: str,
    now: str,
) -> None:
    rows = [
        (source_id, term, normalize_location_name(term), title[:300], now, now)
        for term in extract_candidate_terms(text)
    ]
    if not rows:
        return
    connection.executemany(
        """
        INSERT INTO classification_term_candidates (
            source_id, term, normalized_term, sample_title, first_seen, last_seen
        )
        SELECT ?, ?, ?, ?, ?, ?
        WHERE NOT EXISTS (
            SELECT 1
            FROM classification_terms
            WHERE classification_terms.source_id = ?
              AND classification_terms.term = ?
        )
        ON CONFLICT(source_id, normalized_term) DO UPDATE SET
            term = excluded.term,
            sample_title = excluded.sample_title,
            seen_count = classification_term_candidates.seen_count + 1,
            last_seen = excluded.last_seen
        """,
        [(*row, row[0], row[1]) for row in rows],
    )


def list_classification_terms(
    source_id: str,
    *,
    rule_group: str | None = None,
) -> list[sqlite3.Row]:
    if using_remote_repository():
        params: dict[str, object] = {"source_id": source_id}
        if rule_group is not None:
            params["rule_group"] = rule_group
        response = remote_request("GET", "/api/sensor/classification-terms", params=params)
        return list(response)  # type: ignore[arg-type,return-value]

    clauses = ["source_id = ?"]
    params: list[object] = [source_id]
    if rule_group is not None:
        clauses.append("rule_group = ?")
        params.append(rule_group)
    try:
        with connect() as connection:
            rows = connection.execute(
                f"""
                SELECT source_id, rule_group, term, category, severity, score
                FROM classification_terms
                WHERE {' AND '.join(clauses)}
                ORDER BY score DESC, length(term) DESC, term
                """,
                params,
            ).fetchall()
    except sqlite3.OperationalError as error:
        if "no such table" not in str(error):
            raise
        from argus.database import init_db

        init_db()
        return list_classification_terms(source_id, rule_group=rule_group)
    return rows


def scheduler_job_paused(job_id: str) -> bool:
    if using_remote_repository():
        response = remote_request("GET", f"/api/sensor/scheduler/jobs/{job_id}/control")
        return bool(dict(response).get("paused"))  # type: ignore[arg-type]

    try:
        with connect() as connection:
            ensure_scheduler_controls_table(connection)
            row = connection.execute(
                "SELECT paused FROM scheduler_controls WHERE job_id = ?",
                (job_id,),
            ).fetchone()
    except sqlite3.OperationalError as error:
        if "no such table" not in str(error):
            raise
        return False
    return bool(row["paused"]) if row else False


def set_scheduler_job_paused(job_id: str, paused: bool) -> None:
    if using_remote_repository():
        remote_request(
            "POST",
            f"/api/sensor/scheduler/jobs/{job_id}/control",
            json_payload={"paused": paused},
        )
        return

    with connect() as connection:
        ensure_scheduler_controls_table(connection)
        connection.execute(
            """
            INSERT INTO scheduler_controls (job_id, paused, updated_at)
            VALUES (?, ?, datetime('now'))
            ON CONFLICT(job_id) DO UPDATE SET
                paused = excluded.paused,
                updated_at = excluded.updated_at
            """,
            (job_id, 1 if paused else 0),
        )


def ensure_scheduler_controls_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS scheduler_controls (
            job_id TEXT PRIMARY KEY,
            paused INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        )
        """
    )


def get_scheduler_job_status(job_id: str) -> dict[str, object] | None:
    if using_remote_repository():
        response = remote_request("GET", f"/api/sensor/scheduler/jobs/{job_id}/status")
        data = dict(response)  # type: ignore[arg-type]
        return data if data else None

    try:
        with connect() as connection:
            ensure_scheduler_status_table(connection)
            row = connection.execute(
                """
                SELECT running, runs, failures, last_started, last_finished,
                       next_run_at, last_result, last_error
                FROM scheduler_status
                WHERE job_id = ?
                """,
                (job_id,),
            ).fetchone()
    except sqlite3.OperationalError as error:
        if "no such table" not in str(error):
            raise
        return None
    if row is None:
        return None
    return {
        "running": bool(row["running"]),
        "runs": int(row["runs"]),
        "failures": int(row["failures"]),
        "last_started": parse_stored_datetime(row["last_started"]),
        "last_finished": parse_stored_datetime(row["last_finished"]),
        "next_run_at": parse_stored_datetime(row["next_run_at"]),
        "last_result": row["last_result"],
        "last_error": row["last_error"],
    }


def set_scheduler_job_status(
    *,
    job_id: str,
    running: bool,
    runs: int,
    failures: int,
    last_started: datetime | None,
    last_finished: datetime | None,
    next_run_at: datetime | None,
    last_result: str | None,
    last_error: str | None,
) -> None:
    if using_remote_repository():
        remote_request(
            "POST",
            f"/api/sensor/scheduler/jobs/{job_id}/status",
            json_payload={
                "running": running,
                "runs": runs,
                "failures": failures,
                "last_started": last_started.isoformat() if last_started else None,
                "last_finished": last_finished.isoformat() if last_finished else None,
                "next_run_at": next_run_at.isoformat() if next_run_at else None,
                "last_result": last_result,
                "last_error": last_error,
            },
        )
        return

    with connect() as connection:
        ensure_scheduler_status_table(connection)
        connection.execute(
            """
            INSERT INTO scheduler_status (
                job_id, running, runs, failures, last_started, last_finished,
                next_run_at, last_result, last_error, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(job_id) DO UPDATE SET
                running = excluded.running,
                runs = excluded.runs,
                failures = excluded.failures,
                last_started = excluded.last_started,
                last_finished = excluded.last_finished,
                next_run_at = excluded.next_run_at,
                last_result = excluded.last_result,
                last_error = excluded.last_error,
                updated_at = excluded.updated_at
            """,
            (
                job_id,
                1 if running else 0,
                runs,
                failures,
                last_started.isoformat() if last_started else None,
                last_finished.isoformat() if last_finished else None,
                next_run_at.isoformat() if next_run_at else None,
                last_result,
                last_error,
            ),
        )


def ensure_scheduler_status_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS scheduler_status (
            job_id TEXT PRIMARY KEY,
            running INTEGER NOT NULL DEFAULT 0,
            runs INTEGER NOT NULL DEFAULT 0,
            failures INTEGER NOT NULL DEFAULT 0,
            last_started TEXT,
            last_finished TEXT,
            next_run_at TEXT,
            last_result TEXT,
            last_error TEXT,
            updated_at TEXT NOT NULL
        )
        """
    )


def parse_stored_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)
