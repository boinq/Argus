# Argus

Argus is a Denmark-focused hazardous event monitor. It provides a FastAPI backend,
a local SQLite database, and a web frontend centered on a satellite map of Denmark.

## Run Locally

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn argus.main:app --reload
```

Open http://localhost:8000.

## Run With Docker

```bash
docker compose up --build
```

Open http://localhost:8088.

The SQLite database is stored in the `argus-data` Docker volume. Set
`ARGUS_DB_PATH` to choose a different local path. The container publishes on
`127.0.0.1:8088` by default; set `ARGUS_BIND_ADDRESS=0.0.0.0` only if you want
to expose it directly without a reverse proxy.

For production deployment on a host server, copy `.env.example` to `.env` and
use:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

See [DEPLOY.md](DEPLOY.md) for reverse proxy examples, update commands, and
backup/restore notes.

## Reverse Proxy Hosting

Argus is safe to place behind a reverse proxy. The frontend uses relative API
and static asset paths, so it can be served from `/` or from a proxy path such
as `/argus`.

Runtime proxy values are read when the app starts:

```bash
ARGUS_PUBLIC_BASE_URL=https://argus.example.dk
ARGUS_ROOT_PATH=/argus
ARGUS_TRUSTED_HOSTS=argus.example.dk,localhost
ARGUS_PROXY_HEADERS=true
ARGUS_FORWARDED_ALLOW_IPS=10.0.0.0/8
ARGUS_NTFY_ENABLED=true
ARGUS_NTFY_SERVER_URL=https://ntfy.sh
ARGUS_NTFY_TOPIC=argus-alerts
ARGUS_NTFY_TOKEN=optional-token
ARGUS_NTFY_PRIORITY=high
ARGUS_SCHEDULER_ENABLED=true
ARGUS_SCHEDULER_STARTUP_DELAY_SECONDS=15
ARGUS_DMI_METOBS_INTERVAL_SECONDS=600
ARGUS_DR_NEWS_INTERVAL_SECONDS=600
ARGUS_ELECTRICITY_INTERVAL_SECONDS=600
ARGUS_ELECTRICITY_INCIDENTS_INTERVAL_SECONDS=600
ARGUS_MARITIME_INTERVAL_SECONDS=600
ARGUS_NIORD_INTERVAL_SECONDS=600
ARGUS_ODIN_INTERVAL_SECONDS=600
ARGUS_TRAFFIC_INTERVAL_SECONDS=600
ARGUS_HEALTH_ALERTS_INTERVAL_SECONDS=1800
```

The Docker image starts Uvicorn through `python -m argus.server`, which reads
these environment variables. When using a path prefix, configure the proxy to
forward requests to the app and preserve or strip the prefix consistently with
`ARGUS_ROOT_PATH`.

The in-app Settings page stores these values in SQLite for operators, but
changes to runtime proxy behavior require restarting the container.

NTFY settings are configuration-only at this stage. Alert delivery will use
these values once notification dispatch is added.

## API

- `GET /api/health`
- `GET /api/events`
- `GET /api/events/{event_id}`
- `POST /api/events`
- `PATCH /api/events/{event_id}`
- `GET /api/sources`
- `POST /api/sources/dmi-metobs/sync`
- `POST /api/sources/dr-news/sync`
- `POST /api/sources/energidataservice-elspot/sync`
- `POST /api/sources/greenpowerdenmark-incidents/sync`
- `POST /api/sources/dma-news/sync`
- `POST /api/sources/niord-messages/sync`
- `POST /api/sources/odin-incidents/sync`
- `POST /api/sources/trafikinfo-events/sync`
- `POST /api/sources/health-alerts/sync`
- `GET /api/scheduler/jobs`
- `POST /api/scheduler/jobs/{job_id}/run`

## DMI Ingestion

Argus can ingest DMI meteorological observations from DMI's Frie Data gateway:

```text
https://dmigw.govcloud.dk/v2/metObs/collections/observation/items
```

The current integration fetches recent Danish observations for wind speed, wind
gusts, 10-minute precipitation, and dry-bulb temperature. Raw observations are
stored in SQLite, and weather events are created only when conservative hazard
thresholds are crossed.

Trigger a manual sync from the Sources page or with:

```bash
curl -X POST http://localhost:8000/api/scheduler/jobs/dmi-metobs/run
```

The generic polling scheduler starts with the app when
`ARGUS_SCHEDULER_ENABLED=true`. Weather, news, electricity, maritime, Niord,
ODIN, and traffic integrations default to 10-minute polling. Danish Health
Alerts still default to 30 minutes.

## Other Ingestion Sources

Argus also polls these real public sources:

- DR Nyheder RSS for hazard-related national news signals.
- Energi Data Service `Elspotprices` for DK1/DK2 electricity market telemetry.
- Green Power Denmark Elnet incidents for geolocated electricity outages and operational notices.
- Danish Maritime Authority news archives for maritime safety/security notices.
- Niord nautical information for official navigational warnings and notices.
- ODIN 1-1-2 nationwide pulse RSS for recent emergency dispatches.
- Vejdirektoratet Trafikinfo event JSON for current road and traffic events.

## Danish Health Alerts

Argus ingests public health notices from Sundhedsstyrelsen's official news page:

```text
https://www.sst.dk/nyheder
```

The current integration stores raw article metadata and promotes items to
health events when titles or summaries contain risk keywords such as infectious
disease, outbreaks, travel recommendations, vaccination, opioids, or critical
health infrastructure.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```
