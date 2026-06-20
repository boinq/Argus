from __future__ import annotations

from argus.database import init_db
from argus.main import api_create_event, api_list_events, health
from argus.models import EventCreate


def test_health(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGUS_DB_PATH", str(tmp_path / "argus.db"))

    assert health() == {"status": "ok"}


def test_seeded_events_are_returned(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGUS_DB_PATH", str(tmp_path / "argus.db"))
    init_db()

    events = api_list_events()
    assert len(events) >= 4
    assert {event.category for event in events} >= {
        "weather",
        "hybrid",
        "electrical",
        "food",
    }


def test_create_event(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGUS_DB_PATH", str(tmp_path / "argus.db"))
    init_db()
    payload = EventCreate.model_validate({
        "title": "Rail disruption near Odense",
        "category": "transport",
        "severity": "medium",
        "status": "current",
        "source": "Trafikinfo",
        "description": "Signal disruption is affecting regional departures.",
        "latitude": 55.4038,
        "longitude": 10.4024,
        "starts_at": "2026-06-20T16:30:00+02:00",
        "ends_at": None,
    })

    event = api_create_event(payload)

    assert event.id > 0
    assert event.title == payload.title
