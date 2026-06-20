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
from argus.models import AppSettings, AppSettingsUpdate, Event, EventCreate, EventUpdate
from argus.repository import (
    create_event,
    get_event,
    get_settings,
    list_events,
    update_event,
    update_settings,
)


BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    init_db()
    yield


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
