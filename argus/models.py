from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


Category = Literal[
    "weather",
    "hybrid",
    "electrical",
    "food",
    "health",
    "transport",
    "maritime",
    "emergency",
    "other",
]
Severity = Literal["low", "medium", "high", "critical"]
Status = Literal["monitoring", "upcoming", "current", "resolved"]
SourceStatus = Literal["connected", "planned", "manual", "error"]


class EventBase(BaseModel):
    title: str = Field(min_length=3, max_length=140)
    category: Category
    severity: Severity
    status: Status
    source: str = Field(min_length=2, max_length=120)
    description: str = Field(min_length=3, max_length=1000)
    latitude: float = Field(ge=54.4, le=58.2)
    longitude: float = Field(ge=7.7, le=15.4)
    starts_at: datetime
    ends_at: datetime | None = None


class EventCreate(EventBase):
    pass


class EventUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=140)
    category: Category | None = None
    severity: Severity | None = None
    status: Status | None = None
    source: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = Field(default=None, min_length=3, max_length=1000)
    latitude: float | None = Field(default=None, ge=54.4, le=58.2)
    longitude: float | None = Field(default=None, ge=7.7, le=15.4)
    starts_at: datetime | None = None
    ends_at: datetime | None = None


class Event(EventBase):
    id: int
    updated_at: datetime


class AppSettings(BaseModel):
    public_base_url: str = Field(default="http://localhost:8000", max_length=240)
    path_prefix: str = Field(default="", max_length=80)
    trusted_hosts: str = Field(default="*", max_length=500)
    proxy_headers: bool = True
    ntfy_enabled: bool = False
    ntfy_server_url: str = Field(default="https://ntfy.sh", max_length=240)
    ntfy_topic: str = Field(default="", max_length=120)
    ntfy_token: str = Field(default="", max_length=500)
    ntfy_priority: str = Field(default="default", max_length=20)


class AppSettingsUpdate(BaseModel):
    public_base_url: str | None = Field(default=None, max_length=240)
    path_prefix: str | None = Field(default=None, max_length=80)
    trusted_hosts: str | None = Field(default=None, max_length=500)
    proxy_headers: bool | None = None
    ntfy_enabled: bool | None = None
    ntfy_server_url: str | None = Field(default=None, max_length=240)
    ntfy_topic: str | None = Field(default=None, max_length=120)
    ntfy_token: str | None = Field(default=None, max_length=500)
    ntfy_priority: str | None = Field(default=None, max_length=20)


class Source(BaseModel):
    id: str
    name: str
    type: str
    status: SourceStatus
    coverage: str
    cadence: str
    endpoint: str
    last_check: datetime | None = None
    last_success: datetime | None = None
    last_error: str | None = None
    updated_at: datetime


class RawObservation(BaseModel):
    id: str
    source_id: str
    observed_at: datetime
    parameter_id: str
    station_id: str
    latitude: float
    longitude: float
    value: float
    created_at: datetime


class IngestResult(BaseModel):
    source_id: str
    observations_seen: int
    observations_stored: int
    events_created: int
    events_updated: int
    message: str


class SchedulerJobStatus(BaseModel):
    id: str
    source_id: str
    name: str
    interval_seconds: int
    enabled: bool
    running: bool
    runs: int
    failures: int
    last_started: datetime | None = None
    last_finished: datetime | None = None
    next_run_at: datetime | None = None
    last_result: str | None = None
    last_error: str | None = None


class MLScoreRequest(BaseModel):
    text: str = Field(min_length=3, max_length=3000)


class PromoteTermRequest(BaseModel):
    source_id: str = Field(min_length=2, max_length=120)
    rule_group: str = Field(min_length=2, max_length=80)
    term: str = Field(min_length=2, max_length=160)
    category: str = Field(default="", max_length=80)
    severity: str = Field(default="", max_length=20)
    score: int = Field(default=1, ge=0, le=20)
