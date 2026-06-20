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
