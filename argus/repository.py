from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Sequence

from argus.database import connect, db_path, init_db
from argus.knowledge import extract_candidate_terms, normalize_location_name
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
