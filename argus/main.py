from __future__ import annotations

from contextlib import asynccontextmanager
import os
from pathlib import Path
from typing import AsyncIterator

from fastapi import Depends, FastAPI, Header, HTTPException, Query
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
from argus.ingest.police import sync_police_short_messages
from argus.ingest.traffic import sync_traffic
from argus.models import (
    AppSettings,
    AppSettingsUpdate,
    Event,
    EventCreate,
    EventUpdate,
    IngestResult,
    MLScoreRequest,
    PromoteTermRequest,
    RawObservation,
    SchedulerJobStatus,
    SensorDeleteEvents,
    SensorLocationAlias,
    SensorLocationCandidate,
    SensorRawArticle,
    SensorRawObservation,
    SensorSchedulerStatus,
    SensorStatus,
    SensorSourceStatusUpdate,
    Source,
)
from argus.ml import classify_category, classify_severity
from argus.repository import (
    create_event,
    delete_learned_classification_terms,
    get_event,
    get_settings,
    get_fallback_location,
    get_location_alias,
    get_scheduler_job_status,
    list_active_classification_terms,
    list_classification_term_candidates,
    list_classification_terms,
    list_location_aliases,
    list_recent_observations,
    list_sensor_statuses,
    list_sources,
    list_events,
    ml_overview,
    promote_classification_candidate,
    record_sensor_acquisition,
    record_location_candidate,
    reset_database,
    delete_events_by_source,
    insert_raw_article,
    insert_raw_observation,
    scheduler_job_paused,
    set_scheduler_job_paused,
    set_scheduler_job_status,
    update_event,
    update_settings,
    update_source_status,
    upsert_event,
    upsert_location_alias,
)
from argus.scheduler import env_bool
from argus.scheduler_registry import create_scheduler


BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"

scheduler = create_scheduler()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    init_db()
    if env_bool("ARGUS_WEB_EMBEDDED_SENSOR", False):
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


def verify_sensor_token(
    x_argus_sensor_token: str | None = Header(default=None),
    x_argus_sensor_id: str | None = Header(default=None),
) -> str:
    expected = os.getenv("ARGUS_SENSOR_TOKEN", "")
    if expected and x_argus_sensor_token != expected:
        raise HTTPException(status_code=401, detail="Invalid sensor token")
    return x_argus_sensor_id or "unknown-sensor"


@app.post("/api/sensor/source-status")
def api_sensor_source_status(
    payload: SensorSourceStatusUpdate,
    sensor_id: str = Depends(verify_sensor_token),
) -> dict[str, str]:
    update_source_status(
        payload.source_id,
        payload.status,
        last_error=payload.last_error,
        success=payload.success,
    )
    record_sensor_acquisition(
        sensor_id=sensor_id,
        acquisition_type="source_status",
        source_id=payload.source_id,
    )
    return {"status": "stored"}


@app.post("/api/sensor/raw-observations")
def api_sensor_raw_observation(
    payload: SensorRawObservation,
    sensor_id: str = Depends(verify_sensor_token),
) -> dict[str, bool]:
    inserted = insert_raw_observation(**payload.model_dump())
    if inserted:
        record_sensor_acquisition(
            sensor_id=sensor_id,
            acquisition_type="observation",
            source_id=payload.source_id,
        )
    return {"inserted": inserted}


@app.post("/api/sensor/raw-articles")
def api_sensor_raw_article(
    payload: SensorRawArticle,
    sensor_id: str = Depends(verify_sensor_token),
) -> dict[str, bool]:
    inserted = insert_raw_article(**payload.model_dump())
    if inserted:
        record_sensor_acquisition(
            sensor_id=sensor_id,
            acquisition_type="article",
            source_id=payload.source_id,
        )
    return {"inserted": inserted}


@app.post("/api/sensor/events")
def api_sensor_event(
    payload: EventCreate,
    sensor_id: str = Depends(verify_sensor_token),
) -> dict[str, object]:
    event, created = upsert_event(payload)
    record_sensor_acquisition(
        sensor_id=sensor_id,
        acquisition_type="event",
        source_id=payload.source,
    )
    return {"event": event.model_dump(mode="json"), "created": created}


@app.post("/api/sensor/events/delete-by-source")
def api_sensor_delete_events(
    payload: SensorDeleteEvents,
    _: None = Depends(verify_sensor_token),
) -> dict[str, int]:
    return {"deleted": delete_events_by_source(payload.source)}


@app.get("/api/sensor/location-alias")
def api_sensor_location_alias(
    kind: str,
    name: str,
    _: None = Depends(verify_sensor_token),
) -> dict[str, object]:
    location = get_location_alias(kind, name)
    return {"location": list(location) if location else None}


@app.get("/api/sensor/fallback-location")
def api_sensor_fallback_location(_: None = Depends(verify_sensor_token)) -> dict[str, object]:
    location = get_fallback_location()
    return {"location": list(location) if location else None}


@app.get("/api/sensor/location-aliases")
def api_sensor_location_aliases(
    kinds: list[str] = Query(default=[]),
    _: None = Depends(verify_sensor_token),
) -> list[dict[str, object]]:
    return [dict(row) for row in list_location_aliases(kinds=kinds)]


@app.post("/api/sensor/location-aliases")
def api_sensor_upsert_location_alias(
    payload: SensorLocationAlias,
    _: None = Depends(verify_sensor_token),
) -> dict[str, str]:
    upsert_location_alias(**payload.model_dump())
    return {"status": "stored"}


@app.post("/api/sensor/location-candidates")
def api_sensor_location_candidate(
    payload: SensorLocationCandidate,
    _: None = Depends(verify_sensor_token),
) -> dict[str, str]:
    record_location_candidate(**payload.model_dump())
    return {"status": "stored"}


@app.get("/api/sensor/classification-terms")
def api_sensor_classification_terms(
    source_id: str,
    rule_group: str | None = None,
    _: None = Depends(verify_sensor_token),
) -> list[dict[str, object]]:
    return [dict(row) for row in list_classification_terms(source_id, rule_group=rule_group)]


@app.get("/api/sensor/scheduler/jobs/{job_id}/control")
def api_sensor_scheduler_control(
    job_id: str,
    _: None = Depends(verify_sensor_token),
) -> dict[str, bool]:
    return {"paused": scheduler_job_paused(job_id)}


@app.post("/api/sensor/scheduler/jobs/{job_id}/control")
def api_sensor_set_scheduler_control(
    job_id: str,
    payload: dict[str, bool],
    _: None = Depends(verify_sensor_token),
) -> dict[str, bool]:
    paused = bool(payload.get("paused"))
    set_scheduler_job_paused(job_id, paused)
    return {"paused": paused}


@app.get("/api/sensor/scheduler/jobs/{job_id}/status")
def api_sensor_scheduler_status(
    job_id: str,
    _: None = Depends(verify_sensor_token),
) -> dict[str, object]:
    return get_scheduler_job_status(job_id) or {}


@app.post("/api/sensor/scheduler/jobs/{job_id}/status")
def api_sensor_set_scheduler_status(
    job_id: str,
    payload: SensorSchedulerStatus,
    sensor_id: str = Depends(verify_sensor_token),
) -> dict[str, str]:
    set_scheduler_job_status(job_id=job_id, **payload.model_dump())
    record_sensor_acquisition(
        sensor_id=sensor_id,
        acquisition_type="scheduler_status",
        source_id=job_id,
    )
    return {"status": "stored"}


@app.get("/api/events", response_model=list[Event])
def api_list_events() -> list[Event]:
    return list_events()


@app.get("/api/settings", response_model=AppSettings)
def api_get_settings() -> AppSettings:
    return get_settings()


@app.patch("/api/settings", response_model=AppSettings)
def api_update_settings(payload: AppSettingsUpdate) -> AppSettings:
    return update_settings(payload)


@app.post("/api/debug/reset-database")
async def api_reset_database() -> dict[str, str]:
    was_running = bool(scheduler.tasks)
    if was_running:
        await scheduler.stop()
    reset_database()
    if was_running:
        scheduler.start()
    return {"status": "reset"}


@app.get("/api/sources", response_model=list[Source])
def api_list_sources() -> list[Source]:
    return list_sources()


@app.get("/api/sensors", response_model=list[SensorStatus])
def api_list_sensors() -> list[SensorStatus]:
    return list_sensor_statuses()


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


@app.post("/api/sources/police-ritzau-short-messages/sync", response_model=IngestResult)
def api_sync_police_short_messages() -> IngestResult:
    return sync_police_short_messages()


@app.post("/api/sources/trafikinfo-events/sync", response_model=IngestResult)
def api_sync_traffic() -> IngestResult:
    return sync_traffic()


@app.get("/api/scheduler/jobs", response_model=list[SchedulerJobStatus])
def api_scheduler_jobs() -> list[SchedulerJobStatus]:
    return [SchedulerJobStatus.model_validate(job) for job in scheduler.snapshot()]


@app.get("/api/ml/overview")
def api_ml_overview() -> dict[str, object]:
    return ml_overview()


@app.post("/api/ml/score")
def api_ml_score(payload: MLScoreRequest) -> dict[str, object]:
    category = classify_category(payload.text)
    severity = classify_severity(payload.text)
    return {
        "category": category.__dict__ if category else None,
        "severity": severity.__dict__ if severity else None,
    }


@app.get("/api/ml/candidates")
def api_ml_candidates(source_id: str | None = None, limit: int = 80) -> list[dict[str, object]]:
    return [
        dict(row)
        for row in list_classification_term_candidates(source_id=source_id, limit=limit)
    ]


@app.get("/api/ml/terms")
def api_ml_terms(source_id: str | None = None, limit: int = 120) -> list[dict[str, object]]:
    return [
        dict(row)
        for row in list_active_classification_terms(source_id=source_id, limit=limit)
    ]


@app.post("/api/ml/terms/promote")
def api_ml_promote_term(payload: PromoteTermRequest) -> dict[str, str]:
    promote_classification_candidate(**payload.model_dump())
    return {"status": "promoted"}


@app.delete("/api/ml/terms/learned")
def api_ml_delete_learned_terms() -> dict[str, int]:
    return {"deleted": delete_learned_classification_terms()}


@app.post("/api/scheduler/jobs/{job_id}/run", response_model=IngestResult)
async def api_run_scheduler_job(job_id: str) -> IngestResult:
    if job_id not in scheduler.jobs:
        raise HTTPException(status_code=404, detail="Scheduler job not found")
    return await scheduler.run_once(job_id)


@app.post("/api/scheduler/jobs/{job_id}/pause", response_model=SchedulerJobStatus)
def api_pause_scheduler_job(job_id: str) -> SchedulerJobStatus:
    if job_id not in scheduler.jobs:
        raise HTTPException(status_code=404, detail="Scheduler job not found")
    job = scheduler.pause(job_id)
    return SchedulerJobStatus.model_validate(scheduler.snapshot_job(job))


@app.post("/api/scheduler/jobs/{job_id}/resume", response_model=SchedulerJobStatus)
def api_resume_scheduler_job(job_id: str) -> SchedulerJobStatus:
    if job_id not in scheduler.jobs:
        raise HTTPException(status_code=404, detail="Scheduler job not found")
    job = scheduler.resume(job_id)
    return SchedulerJobStatus.model_validate(scheduler.snapshot_job(job))


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
