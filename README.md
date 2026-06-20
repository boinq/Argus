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

Open http://localhost:8000.

The SQLite database is stored in the `argus-data` Docker volume. Set
`ARGUS_DB_PATH` to choose a different local path.

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
```

The Docker image starts Uvicorn through `python -m argus.server`, which reads
these environment variables. When using a path prefix, configure the proxy to
forward requests to the app and preserve or strip the prefix consistently with
`ARGUS_ROOT_PATH`.

The in-app Settings page stores these values in SQLite for operators, but
changes to runtime proxy behavior require restarting the container.

## API

- `GET /api/health`
- `GET /api/events`
- `GET /api/events/{event_id}`
- `POST /api/events`
- `PATCH /api/events/{event_id}`

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```
