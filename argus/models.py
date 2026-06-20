from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


Category = Literal["weather", "hybrid", "electrical", "food", "health", "transport", "other"]
Severity = Literal["low", "medium", "high", "critical"]
Status = Literal["monitoring", "upcoming", "current", "resolved"]


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


class AppSettingsUpdate(BaseModel):
    public_base_url: str | None = Field(default=None, max_length=240)
    path_prefix: str | None = Field(default=None, max_length=80)
    trusted_hosts: str | None = Field(default=None, max_length=500)
    proxy_headers: bool | None = None
