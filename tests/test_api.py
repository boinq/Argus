from __future__ import annotations

import base64
import asyncio
import json
from urllib.parse import quote

from argus.database import connect, init_db
from argus.geocoding import coordinates_from_payload
from argus.ingest.evaluator import evaluate_news_relevance
from argus.ingest.odin import (
    beredskab_location,
    incident_location,
    parse_odin_rss,
    station_geocode_queries,
    station_location,
)
from argus.ingest.police import (
    parse_article_page,
    parse_police_rss,
    police_location,
    police_location_candidates,
)
from argus.ingest.traffic import clean_traffic_text
from argus.main import (
    api_create_event,
    api_get_settings,
    api_list_events,
    api_list_observations,
    api_list_sensors,
    api_list_sources,
    api_ml_candidates,
    api_ml_overview,
    api_ml_promote_term,
    api_ml_score,
    api_ml_terms,
    api_pause_scheduler_job,
    api_reset_database,
    api_resume_scheduler_job,
    api_scheduler_jobs,
    api_sensor_event,
    api_sensor_raw_observation,
    api_sensor_source_status,
    api_sync_electricity,
    api_sync_electricity_incidents,
    api_sync_health_alerts,
    api_sync_maritime,
    api_sync_news,
    api_sync_dmi_metobs,
    api_sync_niord,
    api_sync_odin,
    api_sync_police_short_messages,
    api_sync_traffic,
    api_update_settings,
    health,
)
from argus.models import (
    AppSettingsUpdate,
    EventCreate,
    MLScoreRequest,
    PromoteTermRequest,
    SensorRawObservation,
    SensorSourceStatusUpdate,
)
from argus.repository import (
    get_location_alias,
    insert_raw_article,
    insert_raw_observation,
    list_classification_terms,
    upsert_classification_term,
    upsert_location_alias,
)
from argus.scheduler import PollJob, PollScheduler
from argus.models import IngestResult
from argus.tools.rebuild_events import SOURCES, rebuild_source


def learn_test_location(kind: str, name: str, latitude: float, longitude: float) -> None:
    upsert_location_alias(
        kind=kind,
        name=name,
        latitude=latitude,
        longitude=longitude,
        source="learned",
    )


def learn_test_term(
    source_id: str,
    rule_group: str,
    term: str,
    *,
    category: str = "",
    severity: str = "",
    score: int = 1,
) -> None:
    upsert_classification_term(
        source_id=source_id,
        rule_group=rule_group,
        term=term,
        category=category,
        severity=severity,
        score=score,
        source="learned",
    )


def test_health(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGUS_DB_PATH", str(tmp_path / "argus.db"))

    assert health() == {"status": "ok"}


def test_database_starts_empty_until_ingestion(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGUS_DB_PATH", str(tmp_path / "argus.db"))
    init_db()

    events = api_list_events()
    assert events == []


def test_create_event(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGUS_DB_PATH", str(tmp_path / "argus.db"))
    init_db()
    payload = EventCreate.model_validate({
        "title": "Rail disruption near Odense",
        "category": "transport",
        "severity": "medium",
        "status": "current",
        "source": "Operator test input",
        "description": "Signal disruption is affecting regional departures.",
        "latitude": 55.4038,
        "longitude": 10.4024,
        "starts_at": "2026-06-20T16:30:00+02:00",
        "ends_at": None,
    })

    event = api_create_event(payload)

    assert event.id > 0
    assert event.title == payload.title


def test_debug_reset_database_clears_runtime_data(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGUS_DB_PATH", str(tmp_path / "argus.db"))
    init_db()
    api_create_event(
        EventCreate.model_validate(
            {
                "title": "Temporary disruption",
                "category": "transport",
                "severity": "medium",
                "status": "current",
                "source": "Operator test input",
                "description": "Temporary test event.",
                "latitude": 55.4,
                "longitude": 10.4,
                "starts_at": "2026-06-20T16:30:00+02:00",
                "ends_at": None,
            }
        )
    )

    assert api_list_events()

    asyncio.run(api_reset_database())

    assert api_list_events() == []
    assert {source.id for source in api_list_sources()} >= {"dr-news", "odin-incidents"}


def test_ml_api_lists_scores_and_promotes_candidates(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGUS_DB_PATH", str(tmp_path / "argus.db"))
    init_db()
    for title, category, description in (
        ("Bridge closed after traffic accident", "transport", "Traffic accident closed a major bridge."),
        ("Bridge traffic accident blocks lanes", "transport", "Traffic accident blocked a bridge."),
        ("Power outage affects homes", "electrical", "Electricity outage affected customers."),
    ):
        api_create_event(
            EventCreate.model_validate(
                {
                    "title": title,
                    "category": category,
                    "severity": "high",
                    "status": "current",
                    "source": "DR Nyheder",
                    "description": description,
                    "latitude": 55.4,
                    "longitude": 10.4,
                    "starts_at": "2026-06-20T16:30:00+02:00",
                    "ends_at": None,
                }
            )
        )
    insert_raw_article(
        article_id="dr-news:ml-candidate",
        source_id="dr-news",
        title="Bro lukket efter større uheld",
        url="https://example.test/ml",
        published_at="2026-06-20T12:00:00+00:00",
        summary="Trafikken er påvirket.",
        payload="{}",
    )

    overview = api_ml_overview()
    candidates = api_ml_candidates(source_id="dr-news")
    score = api_ml_score(MLScoreRequest(text="Traffic accident closed a major bridge"))

    assert overview["events"] == 3
    assert candidates
    assert score["category"] is not None

    api_ml_promote_term(
        PromoteTermRequest(
            source_id="dr-news",
            rule_group="category",
            term=candidates[0]["term"],
            category="transport",
            score=4,
        )
    )

    assert any(term["source"] == "reviewed" for term in api_ml_terms(source_id="dr-news"))


def test_settings_can_be_updated(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGUS_DB_PATH", str(tmp_path / "argus.db"))
    init_db()

    settings = api_update_settings(
        AppSettingsUpdate(
            public_base_url="https://argus.example.dk",
            path_prefix="/argus",
            trusted_hosts="argus.example.dk,localhost",
            proxy_headers=True,
            ntfy_enabled=True,
            ntfy_server_url="https://ntfy.example.dk",
            ntfy_topic="argus-alerts",
            ntfy_token="secret-token",
            ntfy_priority="high",
        )
    )

    assert settings.public_base_url == "https://argus.example.dk"
    assert settings.path_prefix == "/argus"
    assert settings.ntfy_enabled is True
    assert settings.ntfy_topic == "argus-alerts"
    assert settings.ntfy_priority == "high"
    assert api_get_settings().trusted_hosts == "argus.example.dk,localhost"


def test_sources_are_returned(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGUS_DB_PATH", str(tmp_path / "argus.db"))
    init_db()

    sources = api_list_sources()

    source_ids = {source.id for source in sources}
    police_source = next(source for source in sources if source.id == "police-ritzau-short-messages")
    assert source_ids >= {
        "dmi-metobs",
        "dr-news",
        "energidataservice-elspot",
        "greenpowerdenmark-incidents",
        "dma-news",
        "niord-messages",
        "trafikinfo-events",
        "health-alerts",
        "odin-incidents",
        "police-ritzau-short-messages",
    }
    assert police_source.name == "Police/Ritzau Short Messages"
    assert police_source.type == "emergency"
    assert police_source.cadence == "Every 10 minutes"
    assert all(source.status == "connected" for source in sources)


def test_location_aliases_are_database_managed(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGUS_DB_PATH", str(tmp_path / "argus.db"))
    init_db()

    assert get_location_alias("place", "Rømø") is None

    learn_test_location("place", "Rømø", 55.145, 8.552)
    learn_test_location("place", "Vejlefjordbroen", 55.708, 9.624)

    assert get_location_alias("place", "Rømø") == (55.145, 8.552)
    assert get_location_alias("place", "Vejlefjordbroen") == (55.708, 9.624)


def test_classification_terms_are_database_managed(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGUS_DB_PATH", str(tmp_path / "argus.db"))
    init_db()

    assert list_classification_terms("police-ritzau-short-messages", rule_group="event") == []

    learn_test_term(
        "police-ritzau-short-messages",
        "event",
        "færdselsuheld",
        category="transport",
        severity="high",
        score=5,
    )
    learn_test_term("health-alerts", "promote", "udbrud", category="health", severity="high")
    learn_test_term("trafikinfo-events", "severity", "uheld", category="transport", severity="high")

    police_terms = list_classification_terms(
        "police-ritzau-short-messages",
        rule_group="event",
    )
    health_terms = list_classification_terms("health-alerts", rule_group="promote")
    traffic_terms = list_classification_terms("trafikinfo-events", rule_group="severity")

    assert any(
        row["term"] == "færdselsuheld" and row["category"] == "transport"
        for row in police_terms
    )
    assert any(row["term"] == "udbrud" and row["severity"] == "high" for row in health_terms)
    assert any(row["term"] == "uheld" and row["severity"] == "high" for row in traffic_terms)


def test_raw_article_learning_records_term_candidates(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGUS_DB_PATH", str(tmp_path / "argus.db"))
    init_db()

    insert_raw_article(
        article_id="dr-news:learning-test",
        source_id="dr-news",
        title="Mystisk forsyningshændelse ved havnen",
        url="https://example.test/learning",
        published_at="2026-06-20T12:00:00+00:00",
        summary="Lokale myndigheder undersøger forsyningshændelse ved havnen.",
        payload="{}",
    )

    with connect() as connection:
        rows = connection.execute(
            """
            SELECT term, seen_count
            FROM classification_term_candidates
            WHERE source_id = 'dr-news'
              AND normalized_term = 'forsyningshaendelse'
            """
        ).fetchall()

    assert len(rows) == 1
    assert rows[0]["term"] == "forsyningshændelse"
    assert rows[0]["seen_count"] == 1


def test_raw_observation_learning_records_station_location(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGUS_DB_PATH", str(tmp_path / "argus.db"))
    init_db()

    insert_raw_observation(
        observation_id="learning-observation",
        source_id="dmi-metobs",
        observed_at="2026-06-20T15:00:00Z",
        parameter_id="temp_dry",
        station_id="09999",
        latitude=56.123,
        longitude=10.456,
        value=12.3,
        payload="{}",
    )

    assert get_location_alias("station", "09999") == (56.123, 10.456)


def test_dmi_sync_creates_weather_event(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGUS_DB_PATH", str(tmp_path / "argus.db"))
    init_db()

    def fake_fetch_observations(limit: int):
        assert limit == 500
        return [
            {
                "type": "Feature",
                "id": "test-gust",
                "geometry": {"type": "Point", "coordinates": [12.5, 55.7]},
                "properties": {
                    "parameterId": "wind_gust_always_past1h",
                    "value": 26.0,
                    "observed": "2026-06-20T15:00:00Z",
                    "stationId": "06123",
                },
            }
        ]

    monkeypatch.setattr("argus.ingest.dmi.fetch_observations", fake_fetch_observations)

    result = api_sync_dmi_metobs()

    assert result.observations_seen == 1
    assert result.events_created == 1
    assert any(event.source == "DMI metObs" for event in api_list_events())
    assert len(api_list_observations(source_id="dmi-metobs")) == 1


def test_observations_can_be_filtered_by_station(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGUS_DB_PATH", str(tmp_path / "argus.db"))
    init_db()

    def fake_fetch_observations(limit: int):
        return [
            {
                "type": "Feature",
                "id": "station-a-temp-1",
                "geometry": {"type": "Point", "coordinates": [12.5, 55.7]},
                "properties": {
                    "parameterId": "temp_dry",
                    "value": 12.0,
                    "observed": "2026-06-20T15:00:00Z",
                    "stationId": "06123",
                },
            },
            {
                "type": "Feature",
                "id": "station-a-temp-2",
                "geometry": {"type": "Point", "coordinates": [12.5, 55.7]},
                "properties": {
                    "parameterId": "temp_dry",
                    "value": 13.0,
                    "observed": "2026-06-20T15:10:00Z",
                    "stationId": "06123",
                },
            },
            {
                "type": "Feature",
                "id": "station-b-wind-1",
                "geometry": {"type": "Point", "coordinates": [12.1, 55.4]},
                "properties": {
                    "parameterId": "wind_speed",
                    "value": 7.0,
                    "observed": "2026-06-20T15:00:00Z",
                    "stationId": "06124",
                },
            },
        ]

    monkeypatch.setattr("argus.ingest.dmi.fetch_observations", fake_fetch_observations)

    api_sync_dmi_metobs()

    station_observations = api_list_observations(
        source_id="dmi-metobs",
        station_id="06123",
    )
    assert len(station_observations) == 2
    assert {item.station_id for item in station_observations} == {"06123"}
    assert [item.value for item in station_observations] == [13.0, 12.0]


def test_sensor_api_writes_to_web_owned_database(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGUS_DB_PATH", str(tmp_path / "argus.db"))
    init_db()

    api_sensor_source_status(
        SensorSourceStatusUpdate(
            source_id="dmi-metobs",
            status="connected",
            success=True,
        ),
        sensor_id="test-sensor",
    )
    observation_result = api_sensor_raw_observation(
        SensorRawObservation(
            observation_id="remote-sensor:06123:temp:1",
            source_id="dmi-metobs",
            observed_at="2026-06-22T09:00:00+00:00",
            parameter_id="temp_dry",
            station_id="06123",
            latitude=55.4,
            longitude=10.4,
            value=18.5,
            payload="{}",
        ),
        sensor_id="test-sensor",
    )
    event_result = api_sensor_event(
        EventCreate(
            title="Remote sensor test event",
            category="weather",
            severity="medium",
            status="current",
            source="Remote sensor",
            description="Remote sensor pushed this event to argus-web.",
            latitude=55.4,
            longitude=10.4,
            starts_at="2026-06-22T09:00:00+00:00",
            ends_at=None,
        ),
        sensor_id="test-sensor",
    )

    observations = api_list_observations(source_id="dmi-metobs", station_id="06123")
    events = api_list_events()
    source = next(item for item in api_list_sources() if item.id == "dmi-metobs")
    sensor = api_list_sensors()[0]

    assert observation_result == {"inserted": True}
    assert event_result["created"] is True
    assert len(observations) == 1
    assert observations[0].value == 18.5
    assert events[0].title == "Remote sensor test event"
    assert source.last_success is not None
    assert sensor.sensor_id == "test-sensor"
    assert sensor.total_posts == 3
    assert sensor.total_status_updates == 1
    assert sensor.total_observations == 1
    assert sensor.total_events == 1


def test_scheduler_jobs_are_returned(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGUS_DB_PATH", str(tmp_path / "argus.db"))
    init_db()
    jobs = api_scheduler_jobs()
    job_intervals = {job.id: job.interval_seconds for job in jobs}

    assert job_intervals["dmi-metobs"] == 600
    assert job_intervals["dr-news"] == 600
    assert job_intervals["energidataservice-elspot"] == 600
    assert job_intervals["greenpowerdenmark-incidents"] == 600
    assert job_intervals["dma-news"] == 600
    assert job_intervals["niord-messages"] == 600
    assert job_intervals["odin-incidents"] == 600
    assert job_intervals["police-ritzau-short-messages"] == 600
    assert job_intervals["trafikinfo-events"] == 600
    assert "health-alerts" in job_intervals
    assert all(job.paused is False for job in jobs)


def test_scheduler_job_can_be_paused_and_resumed(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGUS_DB_PATH", str(tmp_path / "argus.db"))
    init_db()
    paused = api_pause_scheduler_job("dmi-metobs")

    assert paused.id == "dmi-metobs"
    assert paused.paused is True
    assert paused.next_run_at is None
    assert next(job for job in api_scheduler_jobs() if job.id == "dmi-metobs").paused is True

    resumed = api_resume_scheduler_job("dmi-metobs")

    assert resumed.id == "dmi-metobs"
    assert resumed.paused is False


def test_scheduler_staggers_initial_next_runs(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGUS_DB_PATH", str(tmp_path / "argus.db"))
    monkeypatch.setenv("ARGUS_SCHEDULER_STARTUP_DELAY_SECONDS", "60")
    monkeypatch.setenv("ARGUS_SCHEDULER_STAGGER_SECONDS", "7")
    init_db()

    def handler() -> IngestResult:
        return IngestResult(
            source_id="test-source",
            observations_seen=0,
            observations_stored=0,
            events_created=0,
            events_updated=0,
            message="ok",
        )

    async def run_scheduler() -> list[object]:
        scheduler = PollScheduler(enabled=True)
        scheduler.register(PollJob("a", "source-a", "Source A", 600, handler))
        scheduler.register(PollJob("b", "source-b", "Source B", 600, handler))
        scheduler.register(PollJob("c", "source-c", "Source C", 600, handler))
        scheduler.start()
        await asyncio.sleep(0)
        snapshot = scheduler.snapshot()
        await scheduler.stop()
        return snapshot

    snapshot = asyncio.run(run_scheduler())
    first = snapshot[0]["next_run_at"]
    second = snapshot[1]["next_run_at"]
    third = snapshot[2]["next_run_at"]

    assert first is not None
    assert second is not None
    assert third is not None
    assert round((second - first).total_seconds()) == 7
    assert round((third - second).total_seconds()) == 7


def test_scheduler_keeps_polling_after_job_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGUS_DB_PATH", str(tmp_path / "argus.db"))
    init_db()
    calls = 0

    scheduler = PollScheduler(enabled=True)

    def handler() -> IngestResult:
        return IngestResult(
            source_id="source-a",
            observations_seen=1,
            observations_stored=1,
            events_created=0,
            events_updated=0,
            message="ok",
        )

    job = PollJob("a", "source-a", "Source A", 600, handler)

    async def fake_run_job(job: PollJob) -> IngestResult:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("temporary source failure")
        return IngestResult(
            source_id="source-a",
            observations_seen=1,
            observations_stored=1,
            events_created=0,
            events_updated=0,
            message="ok",
        )

    async def run_scheduled_job_twice() -> tuple[IngestResult | None, IngestResult | None]:
        scheduler._run_job = fake_run_job  # type: ignore[method-assign]
        first_result = await scheduler._run_scheduled_job(job)
        second_result = await scheduler._run_scheduled_job(job)
        return first_result, second_result

    first_result, second_result = asyncio.run(run_scheduled_job_twice())

    assert calls == 2
    assert first_result is None
    assert second_result is not None
    assert second_result.message == "ok"


def test_health_sync_creates_health_event(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGUS_DB_PATH", str(tmp_path / "argus.db"))
    init_db()
    learn_test_location("place", "health learned area", 55.676, 12.568)
    learn_test_term(
        "health-alerts",
        "promote",
        "alment farlig",
        category="health",
        severity="high",
    )

    def fake_fetch_health_articles(limit: int):
        assert limit == 25
        return [
            {
                "id": "nyheder:2026:test",
                "title": "Andes hantavirus er kategoriseret som alment farlig sygdom",
                "summary": "Sygdommen skal anmeldes af læger telefonisk og skriftligt.",
                "url": "https://www.sst.dk/nyheder/2026/test",
                "published_at": "2026-05-08T00:00:00+00:00",
            }
        ]

    monkeypatch.setattr("argus.ingest.health.fetch_health_articles", fake_fetch_health_articles)

    result = api_sync_health_alerts()

    assert result.observations_seen == 1
    assert result.events_created == 1
    assert any(event.source == "Sundhedsstyrelsen" for event in api_list_events())


def test_news_sync_creates_hazard_event(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGUS_DB_PATH", str(tmp_path / "argus.db"))
    init_db()
    learn_test_location("place", "news learned area", 55.676, 12.568)
    learn_test_term("dr-news", "category", "cyberangreb", category="hybrid", score=5)
    learn_test_term("dr-news", "impact", "kritisk", score=3)

    monkeypatch.setattr(
        "argus.ingest.news.fetch_news_articles",
        lambda limit: [
            {
                "id": "dr:test",
                "title": "Cyberangreb rammer kritisk infrastruktur",
                "summary": "Beredskab følger situationen tæt.",
                "url": "https://www.dr.dk/nyheder/test",
                "published_at": "2026-06-20T12:00:00+00:00",
            }
        ],
    )

    result = api_sync_news()

    assert result.observations_seen == 1
    assert result.events_created == 1
    assert any(event.source == "DR Nyheder" for event in api_list_events())


def test_news_evaluator_rejects_generic_substring_matches():
    assert evaluate_news_relevance("Pippi Langstrømpe vender tilbage i ny tv-serie") is None
    assert evaluate_news_relevance("Kongeparret deltog i indvielse af nyt kunstværk") is None
    assert evaluate_news_relevance("Volvo tilbagekalder hybrid-biler i Danmark") is None


def test_news_sync_purges_old_false_positive_events(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGUS_DB_PATH", str(tmp_path / "argus.db"))
    init_db()
    api_create_event(
        EventCreate.model_validate(
            {
                "title": "DR news signal: Pippi Langstrømpe vender tilbage i ny animeret tv-serie",
                "category": "electrical",
                "severity": "medium",
                "status": "monitoring",
                "source": "DR Nyheder",
                "description": "Previously misclassified generic news.",
                "latitude": 55.676,
                "longitude": 12.568,
                "starts_at": "2026-06-19T18:21:07+00:00",
                "ends_at": None,
            }
        )
    )
    monkeypatch.setattr(
        "argus.ingest.news.fetch_news_articles",
        lambda limit: [
            {
                "id": "dr:pippi",
                "title": "Pippi Langstrømpe vender tilbage i ny animeret tv-serie",
                "summary": "",
                "url": "https://www.dr.dk/nyheder/test",
                "published_at": "2026-06-19T18:21:07+00:00",
            }
        ],
    )

    result = api_sync_news()

    assert result.events_created == 0
    assert all(event.source != "DR Nyheder" for event in api_list_events())


def test_police_rss_parser_reads_items():
    items = parse_police_rss(
        """<?xml version="1.0" encoding="utf-8"?>
        <rss version="2.0"><channel>
          <item>
            <title>Færdselsuheld på Østjyske Motorvej syd for Vejlefjordbroen</title>
            <link>https://via.ritzau.dk/pressemeddelelse/15002803/faerdselsuheld?lang=da#sm-15002803</link>
            <pubDate>Sat, 20 Jun 2026 11:55:07 GMT</pubDate>
            <guid>https://via.ritzau.dk/pressemeddelelse/15002803/faerdselsuheld?lang=da#sm-15002803</guid>
          </item>
        </channel></rss>"""
    )

    assert len(items) == 1
    assert items[0]["title"].startswith("Færdselsuheld")
    assert items[0]["url"].endswith("#sm-15002803")
    assert items[0]["published_at"] == "2026-06-20T11:55:07+00:00"


def test_police_article_page_parser_reads_initial_state():
    state = {
        "release": {
            "15002803": {
                "items": [
                    {
                        "metadata": {
                            "id": "15002803",
                            "title": "Færdselsuheld på Østjyske Motorvej syd for Vejlefjordbroen",
                            "url": "/pressemeddelelse/15002803/faerdselsuheld?lang=da#sm-15002803",
                            "publicationDate": "2026-06-20T11:55:07Z",
                            "publisherName": "Sydøstjyllands Politi",
                            "publisher": {"city": "Horsens"},
                        },
                        "versions": [
                            {
                                "body": {
                                    "complete": "<p>Vi modtog en anmeldelse om et færdselsuheld.</p>"
                                }
                            }
                        ],
                    }
                ]
            }
        }
    }
    encoded = base64.b64encode(quote(json.dumps(state)).encode()).decode()

    article = parse_article_page(
        f"<script>window.__INITIAL_STATE__ = '{encoded}'</script>",
        {
            "id": "fallback",
            "title": "Fallback title",
            "url": "https://via.ritzau.dk/fallback",
            "published_at": None,
            "summary": "",
        },
    )

    assert article["id"] == "police-ritzau-short-messages:15002803"
    assert article["title"].startswith("Færdselsuheld")
    assert article["url"].startswith("https://via.ritzau.dk/pressemeddelelse/")
    assert article["published_at"] == "2026-06-20T11:55:07+00:00"
    assert article["summary"] == "Vi modtog en anmeldelse om et færdselsuheld."
    assert article["publisher"] == "Sydøstjyllands Politi"
    assert article["publisher_city"] == "Horsens"


def test_police_sync_crawls_links_and_creates_relevant_event(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGUS_DB_PATH", str(tmp_path / "argus.db"))
    init_db()
    learn_test_location("place", "Vejlefjordbroen", 55.708, 9.624)
    learn_test_term(
        "police-ritzau-short-messages",
        "event",
        "færdselsuheld",
        category="transport",
        severity="high",
        score=5,
    )

    rss_item = {
        "id": "police-ritzau-short-messages:15002803",
        "title": "Færdselsuheld på Østjyske Motorvej syd for Vejlefjordbroen",
        "url": "https://via.ritzau.dk/pressemeddelelse/15002803/faerdselsuheld?lang=da#sm-15002803",
        "published_at": "2026-06-20T11:55:07+00:00",
        "summary": "",
    }
    article = {
        **rss_item,
        "summary": "Vi modtog en anmeldelse om et færdselsuheld på motorvejen.",
        "publisher": "Sydøstjyllands Politi",
        "publisher_city": "Horsens",
    }
    monkeypatch.setattr("argus.ingest.police.fetch_police_rss", lambda limit: [rss_item])
    monkeypatch.setattr("argus.ingest.police.fetch_article_details", lambda items: [article])

    result = api_sync_police_short_messages()
    events = api_list_events()

    assert result.observations_seen == 1
    assert result.observations_stored == 1
    assert result.events_created == 1
    assert events[0].source == "Police/Ritzau Short Messages"
    assert events[0].category == "transport"
    assert events[0].severity == "high"
    assert events[0].title.startswith("Police: Færdselsuheld")


def test_police_sync_stores_generic_messages_without_event(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGUS_DB_PATH", str(tmp_path / "argus.db"))
    init_db()

    rss_item = {
        "id": "police-ritzau-short-messages:15001000",
        "title": "Grundlovsforhør ved Retten",
        "url": "https://via.ritzau.dk/pressemeddelelse/15001000/grundlovsforhor?lang=da",
        "published_at": "2026-06-20T08:00:00+00:00",
        "summary": "",
    }
    article = {
        **rss_item,
        "summary": "En person fremstilles i grundlovsforhør.",
        "publisher": "Københavns Politi",
        "publisher_city": "København",
    }
    monkeypatch.setattr("argus.ingest.police.fetch_police_rss", lambda limit: [rss_item])
    monkeypatch.setattr("argus.ingest.police.fetch_article_details", lambda items: [article])

    result = api_sync_police_short_messages()

    assert result.observations_seen == 1
    assert result.observations_stored == 1
    assert result.events_created == 0
    assert api_list_events() == []


def test_rebuild_events_recreates_police_events_from_raw_articles(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGUS_DB_PATH", str(tmp_path / "argus.db"))
    init_db()
    learn_test_location("place", "Vejlefjordbroen", 55.708, 9.624)
    learn_test_term(
        "police-ritzau-short-messages",
        "event",
        "færdselsuheld",
        category="transport",
        severity="high",
        score=5,
    )
    article = {
        "id": "police-ritzau-short-messages:rebuild-test",
        "title": "Færdselsuheld på Østjyske Motorvej syd for Vejlefjordbroen",
        "url": "https://via.ritzau.dk/pressemeddelelse/rebuild-test",
        "published_at": "2026-06-20T11:55:07+00:00",
        "summary": "Der er sket et færdselsuheld umiddelbart før Vejlefjordbroen.",
        "publisher": "Sydøstjyllands Politi",
        "publisher_city": "Horsens",
    }
    insert_raw_article(
        article_id=article["id"],
        source_id="police-ritzau-short-messages",
        title=article["title"],
        url=article["url"],
        published_at=article["published_at"],
        summary=article["summary"],
        payload=json.dumps(article),
    )

    result = rebuild_source(SOURCES["police-ritzau-short-messages"])
    events = api_list_events()

    assert result["raw_rows"] == 1
    assert result["created"] == 1
    assert events[0].source == "Police/Ritzau Short Messages"
    assert events[0].latitude == 55.708
    assert events[0].longitude == 9.624


def test_police_location_uses_incident_text_before_publisher_city(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGUS_DB_PATH", str(tmp_path / "argus.db"))
    init_db()
    learn_test_location("place", "Vejlefjordbroen", 55.708, 9.624)
    learn_test_location("place", "Horsens", 55.861, 9.85)

    location = police_location(
        {
            "title": "Færdselsuheld på Østjyske Motorvej",
            "summary": (
                "Vi modtog en anmeldelse om et færdselsuheld i Østjyske Motorvejs "
                "nordgående spor umiddelbart før Vejlefjordbroen."
            ),
            "publisher_city": "Horsens",
        }
    )

    assert location == (55.708, 9.624)


def test_police_location_finds_island_mentions_in_incident_text(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGUS_DB_PATH", str(tmp_path / "argus.db"))
    init_db()
    learn_test_location("place", "Rømø", 55.145, 8.552)
    learn_test_location("place", "Esbjerg", 55.476, 8.459)

    location = police_location(
        {
            "title": "Vi er til stede ved demonstration på Rømø",
            "summary": (
                "Syd- & Sønderjyllands Politi er til stede ved den igangværende "
                "demonstration på Rømø og opfordrer trafikanter i området til "
                "at væbne sig med tålmodighed."
            ),
            "publisher_city": "Esbjerg",
        }
    )

    assert location == (55.145, 8.552)


def test_police_location_falls_back_to_publisher_city(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGUS_DB_PATH", str(tmp_path / "argus.db"))
    init_db()
    learn_test_location("place", "Horsens", 55.861, 9.85)

    location = police_location(
        {
            "title": "Politiet er til stede",
            "summary": "Vi følger situationen på stedet.",
            "publisher_city": "Horsens",
        }
    )

    assert location == (55.861, 9.85)


def test_police_location_extracts_and_learns_incident_place(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGUS_DB_PATH", str(tmp_path / "argus.db"))
    init_db()
    learn_test_location("place", "Horsens", 55.861, 9.85)

    def fake_geocode(name: str) -> tuple[float, float] | None:
        return (55.699, 9.573) if name == "Vejlefjordbroen" else None

    monkeypatch.setattr("argus.ingest.police.geocode_danish_place", fake_geocode)

    location = police_location(
        {
            "title": "Færdselsuheld på Østjyske Motorvej syd for Vejlefjordbroen",
            "summary": (
                "Vi modtog kl. 1243 en anmeldelse om et færdselsuheld i Østjyske "
                "Motorvejs nordgående spor umiddelbart før Vejlefjordbroen."
            ),
            "publisher_city": "Horsens",
        }
    )

    assert location == (55.699, 9.573)
    assert get_location_alias("place", "Vejlefjordbroen") == (55.699, 9.573)


def test_police_location_records_unresolved_incident_candidates(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGUS_DB_PATH", str(tmp_path / "argus.db"))
    init_db()
    learn_test_location("place", "Esbjerg", 55.476, 8.459)
    monkeypatch.setattr("argus.ingest.police.geocode_danish_place", lambda name: None)

    location = police_location(
        {
            "title": "Politiet er til stede ved ukendt samlingssted",
            "summary": "Vi følger situationen på stedet.",
            "publisher_city": "Esbjerg",
        }
    )

    with connect() as connection:
        row = connection.execute(
            """
            SELECT name, seen_count
            FROM location_candidates
            WHERE source_id = 'police-ritzau-short-messages'
            """
        ).fetchone()

    assert location == (55.476, 8.459)
    assert row["name"] == "ukendt samlingssted"
    assert row["seen_count"] == 1


def test_police_location_candidate_parser_prioritizes_message_places():
    candidates = police_location_candidates(
        "Færdselsuheld",
        "Uheldet skete på Korsør Landevej vest for Boeslunde.",
    )

    assert "Korsør Landevej" in candidates
    assert "Boeslunde" in candidates


def test_electricity_sync_creates_market_stress_event(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGUS_DB_PATH", str(tmp_path / "argus.db"))
    init_db()
    learn_test_location("electricity_area", "DK2", 55.676, 12.568)

    monkeypatch.setattr(
        "argus.ingest.electricity.fetch_elspot_records",
        lambda limit: [
            {
                "HourUTC": "2026-06-20T13:00:00",
                "PriceArea": "DK2",
                "SpotPriceDKK": 3200,
            }
        ],
    )

    result = api_sync_electricity()

    assert result.observations_seen == 1
    assert result.events_created == 1
    assert any(event.source == "Energi Data Service" for event in api_list_events())
    assert len(api_list_observations(source_id="energidataservice-elspot")) == 1


def test_electricity_incidents_sync_creates_outage_event(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGUS_DB_PATH", str(tmp_path / "argus.db"))
    init_db()

    monkeypatch.setattr(
        "argus.ingest.electricity_incidents.fetch_electricity_incidents",
        lambda limit: [
            {
                "id": 180430,
                "created": "2026-06-20T08:16:13.65",
                "title": "Afbrud i Låsby",
                "comment": "",
                "cause": "Der er i øjeblikket strømafbrydelse pga. fejl i forsyningsnettet.",
                "incidentType": "Uvarslet",
                "incidentStatus": "Aktiv",
                "supplierName": "Dinel A/S",
                "effectedCustomers": 130,
                "startDate": "2026-06-20T10:00:00",
                "endDate": None,
                "expectedDowntime": "2026-06-20T13:00:00",
                "zipcodes": "8670",
                "centerLat": 56.168122372764941,
                "centerLng": 9.8471934125810616,
            }
        ],
    )

    result = api_sync_electricity_incidents()
    events = api_list_events()

    assert result.observations_seen == 1
    assert result.events_created == 1
    assert events[0].source == "Green Power Denmark Elnet"
    assert events[0].category == "electrical"
    assert events[0].severity == "medium"
    assert events[0].latitude == 56.168122372764941
    assert events[0].longitude == 9.8471934125810616


def test_electricity_incidents_sync_skips_small_planned_notices(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGUS_DB_PATH", str(tmp_path / "argus.db"))
    init_db()

    monkeypatch.setattr(
        "argus.ingest.electricity_incidents.fetch_electricity_incidents",
        lambda limit: [
            {
                "id": 180206,
                "created": "2026-06-17T08:14:05.473",
                "title": "Afbrud i Snedsted",
                "comment": "",
                "cause": "Vedligeholdelsesarbejde.",
                "incidentType": "Varslet",
                "incidentStatus": "Aktiv",
                "supplierName": "Netselskabet Elværk",
                "effectedCustomers": 5,
                "startDate": "2026-06-22T07:00:00",
                "endDate": None,
                "expectedDowntime": "2026-06-22T15:00:00",
                "zipcodes": "7752",
                "centerLat": 56.862580602,
                "centerLng": 8.432493606000001,
            }
        ],
    )

    result = api_sync_electricity_incidents()

    assert result.observations_seen == 1
    assert result.observations_stored == 1
    assert result.events_created == 0
    assert api_list_events() == []


def test_maritime_sync_creates_maritime_event(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGUS_DB_PATH", str(tmp_path / "argus.db"))
    init_db()
    learn_test_location("place", "maritime learned area", 55.9397, 10.515)
    learn_test_term("dma-news", "maritime", "navigation warning", category="maritime", score=5)

    monkeypatch.setattr(
        "argus.ingest.maritime.fetch_maritime_articles",
        lambda limit: [
            {
                "id": "dma:test",
                "title": "Navigation warning for Danish waters",
                "summary": "DMA news item listed in current archive",
                "url": "https://www.dma.dk/news/2026/test",
                "published_at": "2026-06-20T12:00:00+00:00",
            }
        ],
    )

    result = api_sync_maritime()

    assert result.observations_seen == 1
    assert result.events_created == 1
    assert any(event.category == "maritime" for event in api_list_events())


def test_niord_sync_creates_maritime_event(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGUS_DB_PATH", str(tmp_path / "argus.db"))
    init_db()

    monkeypatch.setattr(
        "argus.ingest.niord.fetch_niord_messages",
        lambda limit: [
            {
                "id": "niord-test",
                "shortId": "NW-001-26",
                "status": "PUBLISHED",
                "publishDateFrom": 1781946000000,
                "followUpDate": 1782032400000,
                "areas": [{"mrn": "urn:mrn:iho:country:dk", "descs": [{"lang": "da", "name": "Danmark"}]}],
                "parts": [
                    {
                        "geometry": {
                            "type": "FeatureCollection",
                            "features": [
                                {
                                    "type": "Feature",
                                    "geometry": {"type": "Point", "coordinates": [12.6, 55.7]},
                                }
                            ],
                        },
                        "descs": [
                            {
                                "lang": "da",
                                "subject": "Navigationsadvarsel",
                                "details": "<p>Område spærret for gennemsejling.</p>",
                            }
                        ],
                    }
                ],
                "descs": [{"lang": "da", "title": "Danmark. Øresund. Område spærret."}],
            }
        ],
    )

    result = api_sync_niord()
    events = api_list_events()

    assert result.observations_seen == 1
    assert result.events_created == 1
    assert events[0].source == "Niord Nautical Information"
    assert events[0].category == "maritime"
    assert events[0].latitude == 55.7
    assert events[0].longitude == 12.6


def test_niord_sync_skips_non_denmark_messages_without_geometry(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGUS_DB_PATH", str(tmp_path / "argus.db"))
    init_db()

    monkeypatch.setattr(
        "argus.ingest.niord.fetch_niord_messages",
        lambda limit: [
            {
                "id": "greenland-test",
                "shortId": "NM-001-26",
                "status": "PUBLISHED",
                "publishDateFrom": 1781946000000,
                "areas": [{"mrn": "urn:mrn:iho:country:gl", "descs": [{"lang": "da", "name": "Grønland"}]}],
                "parts": [{"descs": [{"lang": "da", "subject": "Fyr slukket", "details": "Fyr slukket."}]}],
                "descs": [{"lang": "da", "title": "Grønland. Fyr slukket."}],
            }
        ],
    )

    result = api_sync_niord()

    assert result.observations_seen == 1
    assert result.events_created == 0
    assert api_list_events() == []


def test_odin_sync_creates_emergency_event(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGUS_DB_PATH", str(tmp_path / "argus.db"))
    init_db()
    learn_test_location("station", "Hedensted", 55.77, 9.702)
    learn_test_term("odin-incidents", "severity", "brand", category="emergency", severity="medium")

    monkeypatch.setattr(
        "argus.ingest.odin.fetch_odin_incidents",
        lambda limit: [
            {
                "id": "odin-incidents:test",
                "title": "Sydøstjyllands Brandvæsen",
                "summary": "Førstemelding: Naturbrand-Mindre brand Station: Hedensted",
                "url": "http://www.odin.dk/112puls/",
                "published_at": "2026-06-20T17:05:41+00:00",
                "alarm_type": "Naturbrand-Mindre brand",
                "station": "Hedensted",
                "reported_at": "20-06-2026 19:05:41",
            }
        ],
    )

    result = api_sync_odin()
    events = api_list_events()

    assert result.observations_seen == 1
    assert result.events_created == 1
    assert events[0].source == "ODIN Beredskabsstyrelsen"
    assert events[0].category == "emergency"
    assert events[0].severity == "medium"
    assert events[0].latitude == 55.77
    assert events[0].longitude == 9.702


def test_odin_sync_falls_back_to_beredskab_location_when_station_is_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGUS_DB_PATH", str(tmp_path / "argus.db"))
    init_db()
    learn_test_location("beredskab", "Hovedstadens Beredskab", 55.676, 12.568)

    monkeypatch.setattr(
        "argus.ingest.odin.fetch_odin_incidents",
        lambda limit: [
            {
                "id": "odin-incidents:empty-station",
                "title": "Hovedstadens Beredskab",
                "summary": "Førstemelding: Brandalarm Station:",
                "url": "http://www.odin.dk/112puls/",
                "published_at": "2026-06-20T17:05:41+00:00",
                "alarm_type": "Brandalarm",
                "station": "",
                "reported_at": "20-06-2026 19:05:41",
            }
        ],
    )

    result = api_sync_odin()
    events = api_list_events()

    assert result.events_created == 1
    assert events[0].latitude == 55.676
    assert events[0].longitude == 12.568


def test_odin_rss_parser_uses_description_and_time_for_ids():
    incidents = parse_odin_rss(
        """<?xml version="1.0" encoding="utf-8"?>
        <rss version="2.0"><channel>
          <item>
            <title>Hovedstadens Beredskab</title>
            <description>Førstemelding: Brandalarm Station: Vesterbro</description>
            <comments>20-06-2026 17:20:25</comments>
            <pubDate>Sat, 20 Jun 2026 15:20:25 GMT</pubDate>
          </item>
          <item>
            <title>Hovedstadens Beredskab</title>
            <description>Førstemelding: Brandalarm Station: Christianshavn</description>
            <comments>20-06-2026 17:21:23</comments>
            <pubDate>Sat, 20 Jun 2026 15:21:23 GMT</pubDate>
          </item>
        </channel></rss>"""
    )

    assert len(incidents) == 2
    assert incidents[0]["id"] != incidents[1]["id"]
    assert incidents[0]["alarm_type"] == "Brandalarm"
    assert incidents[0]["station"] == "Vesterbro"


def test_odin_station_location_uses_station_or_city_names(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGUS_DB_PATH", str(tmp_path / "argus.db"))
    init_db()
    learn_test_location("station", "Vesterbro", 55.669, 12.544)
    learn_test_location("station", "Hillerød", 55.927, 12.301)
    learn_test_location("station", "Åsum - Odense", 55.396, 10.463)

    assert station_location("Hovedstadens Beredskab - Station Vesterbro") == (55.669, 12.544)
    assert station_location("Brandstation Hillerød") == (55.927, 12.301)
    assert station_location("Åsum - Odense") == (55.396, 10.463)
    assert station_location("Ukendt Station") is None


def test_odin_station_location_geocodes_and_caches_unknown_station(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGUS_DB_PATH", str(tmp_path / "argus.db"))
    init_db()
    monkeypatch.setattr("argus.ingest.odin.geocode_danish_place", lambda name: (55.666, 12.398))

    assert station_location("Glostrup") == (55.666, 12.398)
    assert get_location_alias("station", "Glostrup") == (55.666, 12.398)


def test_odin_station_geocode_queries_strip_dispatch_suffixes():
    assert "Herlufmagle" in station_geocode_queries(
        "St. Herlufmagle + Fu",
        "st herlufmagle + fu",
    )
    assert "Nykøbing Falster" in station_geocode_queries("Nyk. Falster", "nyk falster")


def test_geocoder_reads_nested_danish_place_coordinates():
    assert (
        coordinates_from_payload({"stednavn": {"visueltcenter": [12.398, 55.666]}})
        == (55.666, 12.398)
    )


def test_odin_beredskab_location_uses_agency_name_as_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGUS_DB_PATH", str(tmp_path / "argus.db"))
    init_db()
    learn_test_location("beredskab", "Hovedstadens Beredskab", 55.676, 12.568)
    learn_test_location("beredskab", "Beredskab 4K", 55.458, 12.182)

    assert beredskab_location("Hovedstadens Beredskab") == (55.676, 12.568)
    assert beredskab_location("Beredskab 4K") == (55.458, 12.182)
    assert beredskab_location("Ukendt Beredskab") is None
    assert (
        incident_location(
            {
                "title": "Beredskab 4K",
                "station": "",
            }
        )
        == (55.458, 12.182)
    )


def test_odin_unknown_locations_are_recorded_as_candidates(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGUS_DB_PATH", str(tmp_path / "argus.db"))
    init_db()

    location = incident_location(
        {
            "title": "Ukendt Beredskab",
            "summary": "Førstemelding: Brandalarm Station: Mystisk Station",
            "station": "Mystisk Station",
        }
    )

    assert location is None
    with connect() as connection:
        candidates = connection.execute(
            """
            SELECT kind, name, normalized_name, seen_count
            FROM location_candidates
            WHERE source_id = 'odin-incidents'
            ORDER BY kind
            """
        ).fetchall()

    assert [candidate["kind"] for candidate in candidates] == ["beredskab", "station"]
    assert {candidate["name"] for candidate in candidates} == {
        "Mystisk Station",
        "Ukendt Beredskab",
    }
    assert all(candidate["seen_count"] == 1 for candidate in candidates)


def test_traffic_sync_creates_transport_event(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGUS_DB_PATH", str(tmp_path / "argus.db"))
    init_db()

    monkeypatch.setattr(
        "argus.ingest.traffic.fetch_traffic_features",
        lambda limit: [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [12.596, 56.028]},
                "properties": {
                    "featureId": "traffic-test",
                    "title": "Uheld",
                    "header": "Uheld - E47 Helsingørmotorvejen",
                    "description": "<p>Uheld, spor spærret</p>",
                    "suspended": "false",
                    "future": "false",
                    "beginPeriod": "20-06-2026 kl. 16:41",
                },
            }
        ],
    )

    result = api_sync_traffic()

    assert result.observations_seen == 1
    assert result.events_created == 1
    assert any(event.source == "Vejdirektoratet Trafikinfo" for event in api_list_events())


def test_traffic_text_removes_junction_markers():
    assert (
        clean_traffic_text("Rute 21 Holbækmotorvejen mellem <13> Ringstedvej og <12> Roskilde S")
        == "Rute 21 Holbækmotorvejen mellem Ringstedvej og Roskilde S"
    )
    assert (
        clean_traffic_text("Rute 18 fra Vejle mod Herning mellem <3> Lindved og <6> Tørring")
        == "Rute 18 fra Vejle mod Herning mellem Lindved og Tørring"
    )
    assert (
        clean_traffic_text("E20 fra Køge mod Avedøre mellem <32> Køge og <31b> Køge N")
        == "E20 fra Køge mod Avedøre mellem Køge og Køge N"
    )


def test_traffic_sync_replaces_stale_uncleaned_events_and_reports(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGUS_DB_PATH", str(tmp_path / "argus.db"))
    init_db()
    api_create_event(
        EventCreate.model_validate(
            {
                "title": "Trafikinfo: Uheld - E20 mellem <32> Køge og <31b> Køge N",
                "category": "transport",
                "severity": "high",
                "status": "current",
                "source": "Vejdirektoratet Trafikinfo",
                "description": "Uheld mellem <32> Køge og <31b> Køge N",
                "latitude": 55.46,
                "longitude": 12.18,
                "starts_at": "2026-06-20T16:41:00+00:00",
                "ends_at": None,
            }
        )
    )
    insert_raw_article(
        article_id="trafikinfo-events:traffic-test",
        source_id="trafikinfo-events",
        title="Uheld - E20 mellem <32> Køge og <31b> Køge N",
        url="https://trafikkort.vejdirektoratet.dk/",
        published_at="2026-06-20T16:41:00+00:00",
        summary="Uheld mellem <32> Køge og <31b> Køge N",
        payload="{}",
    )
    monkeypatch.setattr(
        "argus.ingest.traffic.fetch_traffic_features",
        lambda limit: [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [12.18, 55.46]},
                "properties": {
                    "featureId": "traffic-test",
                    "header": "Uheld - E20 mellem <32> Køge og <31b> Køge N",
                    "description": "Uheld mellem <32> Køge og <31b> Køge N",
                    "suspended": "false",
                    "future": "false",
                    "beginPeriod": "20-06-2026 kl. 16:41",
                },
            }
        ],
    )

    result = api_sync_traffic()
    events = api_list_events()

    assert result.events_created == 1
    assert len(events) == 1
    assert events[0].title == "Trafikinfo: Uheld - E20 mellem Køge og Køge N"
    assert events[0].description == "Uheld mellem Køge og Køge N"
    with connect() as connection:
        article = connection.execute(
            "SELECT title, summary FROM raw_articles WHERE id = ?",
            ("trafikinfo-events:traffic-test",),
        ).fetchone()
    assert article["title"] == "Uheld - E20 mellem Køge og Køge N"
    assert article["summary"] == "Uheld mellem Køge og Køge N"
