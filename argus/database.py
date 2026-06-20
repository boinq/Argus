from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


DEFAULT_DB_PATH = "data/argus.db"


def db_path() -> Path:
    return Path(os.getenv("ARGUS_DB_PATH", DEFAULT_DB_PATH))


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def init_db() -> None:
    with connect() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                category TEXT NOT NULL,
                severity TEXT NOT NULL,
                status TEXT NOT NULL,
                source TEXT NOT NULL,
                description TEXT NOT NULL,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                starts_at TEXT NOT NULL,
                ends_at TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        seed_settings(connection)
        count = connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        if count == 0:
            seed_events(connection)


def seed_settings(connection: sqlite3.Connection) -> None:
    defaults = {
        "public_base_url": os.getenv("ARGUS_PUBLIC_BASE_URL", "http://localhost:8000"),
        "path_prefix": os.getenv("ARGUS_ROOT_PATH", ""),
        "trusted_hosts": os.getenv("ARGUS_TRUSTED_HOSTS", "*"),
        "proxy_headers": os.getenv("ARGUS_PROXY_HEADERS", "true"),
    }
    connection.executemany(
        "INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)",
        defaults.items(),
    )


def seed_events(connection: sqlite3.Connection) -> None:
    rows = [
        (
            "Storm surge watch, southwest Jutland",
            "weather",
            "high",
            "upcoming",
            "DMI coastal forecast",
            "Elevated water levels and strong westerly winds may affect low-lying coastal roads.",
            55.333,
            8.763,
            "2026-06-20T18:00:00+02:00",
            "2026-06-21T06:00:00+02:00",
            "2026-06-20T16:00:00+02:00",
        ),
        (
            "Power disruption reports, Greater Copenhagen",
            "electrical",
            "medium",
            "current",
            "Grid operator incident desk",
            "Localized outages are being tracked across several eastern suburbs.",
            55.676,
            12.568,
            "2026-06-20T15:20:00+02:00",
            None,
            "2026-06-20T15:45:00+02:00",
        ),
        (
            "Suspicious maritime activity, Great Belt",
            "hybrid",
            "medium",
            "monitoring",
            "Maritime domain awareness feed",
            "Unusual vessel behavior near critical infrastructure is under observation.",
            55.347,
            10.958,
            "2026-06-20T11:30:00+02:00",
            None,
            "2026-06-20T14:10:00+02:00",
        ),
        (
            "Regional supply pressure, North Jutland",
            "food",
            "low",
            "upcoming",
            "Municipal logistics report",
            "Distribution delays could affect selected shelf-stable goods if transport disruption continues.",
            57.048,
            9.919,
            "2026-06-21T08:00:00+02:00",
            "2026-06-22T20:00:00+02:00",
            "2026-06-20T13:20:00+02:00",
        ),
    ]
    connection.executemany(
        """
        INSERT INTO events (
            title, category, severity, status, source, description, latitude,
            longitude, starts_at, ends_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
