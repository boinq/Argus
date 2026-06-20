from __future__ import annotations

from contextlib import asynccontextmanager
import os
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from argus.database import init_db
from argus.ingest.dmi import sync_dmi_observations
from argus.ingest.electricity import sync_electricity
from argus.ingest.electricity_incidents import sync_electricity_incidents
from argus.ingest.health import sync_health_alerts
from argus.ingest.maritime import sync_maritime
from argus.ingest.news import sync_news
from argus.ingest.niord import sync_niord
from argus.ingest.odin import sync_odin
from argus.ingest.traffic import sync_traffic
from argus.models import (
    AppSettings,
    AppSettingsUpdate,
    Event,
    EventCreate,
    EventUpdate,
    IngestResult,
    RawObservation,
    SchedulerJobStatus,
    Source,
)
from argus.repository import (
    create_event,
    get_event,
    get_settings,
    list_recent_observations,
    list_sources,
    list_events,
    update_event,
    update_settings,
)
from argus.scheduler import PollJob, PollScheduler, env_bool, env_int


BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"

scheduler = PollScheduler(
    enabled=env_bool("ARGUS_SCHEDULER_ENABLED", True),
)
scheduler.register(
    PollJob(
        id="dmi-metobs",
        source_id="dmi-metobs",
        name="DMI meteorological observations",
        interval_seconds=max(60, env_int("ARGUS_DMI_METOBS_INTERVAL_SECONDS", 600)),
        handler=sync_dmi_observations,
    )
)
scheduler.register(
    PollJob(
        id="dr-news",
        source_id="dr-news",
        name="DR news",
        interval_seconds=max(60, env_int("ARGUS_DR_NEWS_INTERVAL_SECONDS", 600)),
        handler=sync_news,
    )
)
scheduler.register(
    PollJob(
        id="energidataservice-elspot",
        source_id="energidataservice-elspot",
        name="Energi Data Service electricity telemetry",
        interval_seconds=max(60, env_int("ARGUS_ELECTRICITY_INTERVAL_SECONDS", 600)),
        handler=sync_electricity,
    )
)
scheduler.register(
    PollJob(
        id="greenpowerdenmark-incidents",
        source_id="greenpowerdenmark-incidents",
        name="Green Power Denmark elnet incidents",
        interval_seconds=max(60, env_int("ARGUS_ELECTRICITY_INCIDENTS_INTERVAL_SECONDS", 600)),
        handler=sync_electricity_incidents,
    )
)
scheduler.register(
    PollJob(
        id="dma-news",
        source_id="dma-news",
        name="Danish Maritime Authority news",
        interval_seconds=max(60, env_int("ARGUS_MARITIME_INTERVAL_SECONDS", 600)),
        handler=sync_maritime,
    )
)
scheduler.register(
    PollJob(
        id="niord-messages",
        source_id="niord-messages",
        name="Niord nautical information",
        interval_seconds=max(60, env_int("ARGUS_NIORD_INTERVAL_SECONDS", 600)),
        handler=sync_niord,
    )
)
scheduler.register(
    PollJob(
        id="odin-incidents",
        source_id="odin-incidents",
        name="ODIN 1-1-2 pulse",
        interval_seconds=max(60, env_int("ARGUS_ODIN_INTERVAL_SECONDS", 600)),
        handler=sync_odin,
    )
)
scheduler.register(
    PollJob(
        id="trafikinfo-events",
        source_id="trafikinfo-events",
        name="Vejdirektoratet traffic events",
        interval_seconds=max(60, env_int("ARGUS_TRAFFIC_INTERVAL_SECONDS", 600)),
        handler=sync_traffic,
    )
)
scheduler.register(
    PollJob(
        id="health-alerts",
        source_id="health-alerts",
        name="Danish health alerts",
        interval_seconds=max(300, env_int("ARGUS_HEALTH_ALERTS_INTERVAL_SECONDS", 1800)),
        handler=sync_health_alerts,
    )
)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    init_db()
    scheduler.start()
    try:
        yield
    finally:
        await scheduler.stop()


app = FastAPI(
    title="Argus",
    description="Denmark-focused hazardous event monitoring API.",
    version="0.1.0",
    lifespan=lifespan,
    root_path=os.getenv("ARGUS_ROOT_PATH", ""),
)

trusted_hosts = [
    host.strip()
    for host in os.getenv("ARGUS_TRUSTED_HOSTS", "*").split(",")
    if host.strip()
]
app.add_middleware(TrustedHostMiddleware, allowed_hosts=trusted_hosts or ["*"])
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.head("/", include_in_schema=False)
def head_index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/events", response_model=list[Event])
def api_list_events() -> list[Event]:
    return list_events()


@app.get("/api/settings", response_model=AppSettings)
def api_get_settings() -> AppSettings:
    return get_settings()


@app.patch("/api/settings", response_model=AppSettings)
def api_update_settings(payload: AppSettingsUpdate) -> AppSettings:
    return update_settings(payload)


@app.get("/api/sources", response_model=list[Source])
def api_list_sources() -> list[Source]:
    return list_sources()


@app.get("/api/observations", response_model=list[RawObservation])
def api_list_observations(
    source_id: str | None = None,
    station_id: str | None = None,
    limit: int = 500,
) -> list[RawObservation]:
    return list_recent_observations(source_id=source_id, station_id=station_id, limit=limit)


@app.post("/api/sources/dmi-metobs/sync", response_model=IngestResult)
def api_sync_dmi_metobs() -> IngestResult:
    return sync_dmi_observations()


@app.post("/api/sources/health-alerts/sync", response_model=IngestResult)
def api_sync_health_alerts() -> IngestResult:
    return sync_health_alerts()


@app.post("/api/sources/dr-news/sync", response_model=IngestResult)
def api_sync_news() -> IngestResult:
    return sync_news()


@app.post("/api/sources/energidataservice-elspot/sync", response_model=IngestResult)
def api_sync_electricity() -> IngestResult:
    return sync_electricity()


@app.post("/api/sources/greenpowerdenmark-incidents/sync", response_model=IngestResult)
def api_sync_electricity_incidents() -> IngestResult:
    return sync_electricity_incidents()


@app.post("/api/sources/dma-news/sync", response_model=IngestResult)
def api_sync_maritime() -> IngestResult:
    return sync_maritime()


@app.post("/api/sources/niord-messages/sync", response_model=IngestResult)
def api_sync_niord() -> IngestResult:
    return sync_niord()


@app.post("/api/sources/odin-incidents/sync", response_model=IngestResult)
def api_sync_odin() -> IngestResult:
    return sync_odin()


@app.post("/api/sources/trafikinfo-events/sync", response_model=IngestResult)
def api_sync_traffic() -> IngestResult:
    return sync_traffic()


@app.get("/api/scheduler/jobs", response_model=list[SchedulerJobStatus])
def api_scheduler_jobs() -> list[SchedulerJobStatus]:
    return [SchedulerJobStatus.model_validate(job) for job in scheduler.snapshot()]


@app.post("/api/scheduler/jobs/{job_id}/run", response_model=IngestResult)
async def api_run_scheduler_job(job_id: str) -> IngestResult:
    if job_id not in scheduler.jobs:
        raise HTTPException(status_code=404, detail="Scheduler job not found")
    return await scheduler.run_once(job_id)


@app.get("/api/events/{event_id}", response_model=Event)
def api_get_event(event_id: int) -> Event:
    event = get_event(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


@app.post("/api/events", response_model=Event, status_code=201)
def api_create_event(payload: EventCreate) -> Event:
    return create_event(payload)


@app.patch("/api/events/{event_id}", response_model=Event)
def api_update_event(event_id: int, payload: EventUpdate) -> Event:
    event = update_event(event_id, payload)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return event
