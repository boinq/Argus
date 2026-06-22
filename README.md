# Argus

Argus is a Denmark-focused hazardous event monitor. It provides a FastAPI backend,
a local SQLite database, and a web frontend centered on a satellite map of Denmark.
The Docker deployment is split into two runtime roles:

- `argus-web` serves the web UI and API.
- `argus-sensor` polls external data sources and pushes readings/events to `argus-web`.

`argus-web` owns the database. Sensors can run on the same machine, in Docker,
or on another host as long as they can reach the web API.

## Run Locally

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn argus.main:app --reload
```

Open http://localhost:8000.

Run the sensor in a second terminal when you want local polling:

```bash
ARGUS_WEB_URL=http://127.0.0.1:8000 python -m argus.sensor
```

## Run With Docker

```bash
docker compose up --build
```

Open http://localhost:8088.

Docker starts both `argus-web` and `argus-sensor`. The SQLite database is stored
with `argus-web` in the `argus-data` Docker volume. `argus-sensor` pushes data
to `argus-web` over HTTP. Set `ARGUS_DB_PATH` on `argus-web` to choose a
different local path. The web service publishes on `0.0.0.0:8088` by default so
other devices can reach
`http://<host-ip>:8088`. Set `ARGUS_BIND_ADDRESS=127.0.0.1` if you only want
local reverse proxy access.

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
ARGUS_WEB_EMBEDDED_SENSOR=false
ARGUS_WEB_URL=http://argus-web:8000
ARGUS_SENSOR_TOKEN=optional-shared-secret
ARGUS_SCHEDULER_ENABLED=true
ARGUS_SCHEDULER_STARTUP_DELAY_SECONDS=15
ARGUS_SCHEDULER_STAGGER_SECONDS=30
ARGUS_DMI_METOBS_INTERVAL_SECONDS=600
ARGUS_DR_NEWS_INTERVAL_SECONDS=600
ARGUS_ELECTRICITY_INTERVAL_SECONDS=600
ARGUS_ELECTRICITY_INCIDENTS_INTERVAL_SECONDS=600
ARGUS_MARITIME_INTERVAL_SECONDS=600
ARGUS_NIORD_INTERVAL_SECONDS=600
ARGUS_ODIN_INTERVAL_SECONDS=600
ARGUS_POLICE_RSS_INTERVAL_SECONDS=600
ARGUS_TRAFFIC_INTERVAL_SECONDS=600
ARGUS_HEALTH_ALERTS_INTERVAL_SECONDS=1800
```

The `argus-web` container starts Uvicorn through `python -m argus.server`, while
`argus-sensor` starts `python -m argus.sensor`. `argus-sensor` uses
`ARGUS_WEB_URL` to push data to the web API. Set the same `ARGUS_SENSOR_TOKEN`
on both processes if you want to require authenticated sensor writes. When using
a path prefix, configure the proxy to forward requests to the web app and
preserve or strip the prefix consistently with `ARGUS_ROOT_PATH`.

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
- `POST /api/sources/police-ritzau-short-messages/sync`
- `POST /api/sources/trafikinfo-events/sync`
- `POST /api/sources/health-alerts/sync`
- `GET /api/scheduler/jobs`
- `POST /api/scheduler/jobs/{job_id}/run`
- `POST /api/scheduler/jobs/{job_id}/pause`
- `POST /api/scheduler/jobs/{job_id}/resume`

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

The generic polling scheduler runs in `argus-sensor` when
`ARGUS_SCHEDULER_ENABLED=true`. Weather, news, electricity, maritime, Niord,
ODIN, police/Ritzau, and traffic integrations default to 10-minute polling.
Danish Health Alerts still default to 30 minutes. Pause/resume controls are
stored in `argus-web` and read by `argus-sensor` over HTTP, so the web frontend
can control sensors running on other machines.

## Other Ingestion Sources

Argus also polls these real public sources:

- DR Nyheder RSS for hazard-related national news signals.
- Energi Data Service `Elspotprices` for DK1/DK2 electricity market telemetry.
- Green Power Denmark Elnet incidents for geolocated electricity outages and operational notices.
- Danish Maritime Authority news archives for maritime safety/security notices.
- Niord nautical information for official navigational warnings and notices.
- ODIN 1-1-2 nationwide pulse RSS for recent emergency dispatches.
- Police short-message RSS via Ritzau, with each linked message page crawled for detail text.
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
