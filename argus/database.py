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
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS sources (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                status TEXT NOT NULL,
                coverage TEXT NOT NULL,
                cadence TEXT NOT NULL,
                endpoint TEXT NOT NULL,
                last_check TEXT,
                last_success TEXT,
                last_error TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS raw_observations (
                id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                parameter_id TEXT NOT NULL,
                station_id TEXT NOT NULL,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                value REAL NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS raw_articles (
                id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                published_at TEXT,
                summary TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_events_source_title
            ON events (source, title)
            """
        )
        seed_settings(connection)
        seed_sources(connection)
        cleanup_legacy_seed_data(connection)


def seed_settings(connection: sqlite3.Connection) -> None:
    defaults = {
        "public_base_url": os.getenv("ARGUS_PUBLIC_BASE_URL", "http://localhost:8000"),
        "path_prefix": os.getenv("ARGUS_ROOT_PATH", ""),
        "trusted_hosts": os.getenv("ARGUS_TRUSTED_HOSTS", "*"),
        "proxy_headers": os.getenv("ARGUS_PROXY_HEADERS", "true"),
        "ntfy_enabled": os.getenv("ARGUS_NTFY_ENABLED", "false"),
        "ntfy_server_url": os.getenv("ARGUS_NTFY_SERVER_URL", "https://ntfy.sh"),
        "ntfy_topic": os.getenv("ARGUS_NTFY_TOPIC", ""),
        "ntfy_token": os.getenv("ARGUS_NTFY_TOKEN", ""),
        "ntfy_priority": os.getenv("ARGUS_NTFY_PRIORITY", "default"),
    }
    connection.executemany(
        "INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)",
        defaults.items(),
    )


def seed_sources(connection: sqlite3.Connection) -> None:
    rows = [
        (
            "dmi-metobs",
            "DMI Meteorological Observations",
            "weather",
            "connected",
            "Danish observation stations",
            "Every 10 minutes",
            "https://dmigw.govcloud.dk/v2/metObs/collections/observation/items",
        ),
        (
            "dr-news",
            "DR News",
            "news",
            "connected",
            "Denmark national news RSS",
            "Every 10 minutes",
            "https://www.dr.dk/nyheder/service/feeds/allenyheder",
        ),
        (
            "energidataservice-elspot",
            "Energi Data Service Electricity Prices",
            "electrical",
            "connected",
            "DK1 and DK2 electricity market telemetry",
            "Every 10 minutes",
            "https://api.energidataservice.dk/dataset/Elspotprices",
        ),
        (
            "greenpowerdenmark-incidents",
            "Green Power Denmark Elnet Incidents",
            "electrical",
            "connected",
            "Current and upcoming Danish electricity grid incidents",
            "Every 10 minutes",
            "https://api.elnet.greenpowerdenmark.dk/api/incidents",
        ),
        (
            "dma-news",
            "Danish Maritime Authority News",
            "maritime",
            "connected",
            "Official DMA maritime news archive",
            "Every 10 minutes",
            "https://www.dma.dk/news",
        ),
        (
            "niord-messages",
            "Niord Nautical Information",
            "maritime",
            "connected",
            "Official Danish navigational warnings and notices",
            "Every 10 minutes",
            "https://niord.dma.dk/rest/public/v1/messages",
        ),
        (
            "trafikinfo-events",
            "Vejdirektoratet Trafikinfo Events",
            "transport",
            "connected",
            "Current Danish traffic event feed",
            "Every 10 minutes",
            "https://storage.googleapis.com/trafikkort-data/geojson/big-screen-events.json",
        ),
        (
            "health-alerts",
            "Danish Health Alerts",
            "health",
            "connected",
            "Sundhedsstyrelsen news and public health notices",
            "Every 30 minutes",
            "https://www.sst.dk/nyheder",
        ),
        (
            "odin-incidents",
            "ODIN Beredskabsstyrelsen",
            "emergency",
            "connected",
            "Nationwide ODIN 1-1-2 emergency pulse RSS",
            "Every 10 minutes",
            "http://www.odin.dk/RSS/RSS.aspx?beredskabsID=0000",
        ),
        (
            "police-ritzau-short-messages",
            "Police/Ritzau Short Messages",
            "emergency",
            "connected",
            "Danish police authority short-message RSS with linked detail pages",
            "Every 10 minutes",
            "https://via.ritzau.dk/rss/short-messages/latest",
        ),
    ]
    connection.executemany(
        """
        INSERT INTO sources (
            id, name, type, status, coverage, cadence, endpoint, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(id) DO UPDATE SET
            name = excluded.name,
            type = excluded.type,
            coverage = excluded.coverage,
            cadence = excluded.cadence,
            endpoint = excluded.endpoint,
            updated_at = datetime('now')
        """,
        rows,
    )
    deprecated_source_ids = (
        "energinet-operational",
        "maritime-watch",
        "civil-protection",
        "municipal-reports",
        "trafikinfo",
        "manual-intel",
    )
    connection.execute(
        f"DELETE FROM sources WHERE id IN ({','.join('?' for _ in deprecated_source_ids)})",
        deprecated_source_ids,
    )


def cleanup_legacy_seed_data(connection: sqlite3.Connection) -> None:
    legacy_seed_sources = (
        "DMI coastal forecast",
        "Grid operator incident desk",
        "Maritime domain awareness feed",
        "Municipal logistics report",
        "Trafikinfo",
    )
    connection.execute(
        f"DELETE FROM events WHERE source IN ({','.join('?' for _ in legacy_seed_sources)})",
        legacy_seed_sources,
    )
