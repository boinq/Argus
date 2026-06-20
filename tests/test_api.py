from __future__ import annotations

from argus.database import connect, init_db
from argus.ingest.evaluator import evaluate_news_relevance
from argus.ingest.odin import parse_odin_rss
from argus.ingest.traffic import clean_traffic_text
from argus.main import (
    api_create_event,
    api_get_settings,
    api_list_events,
    api_list_observations,
    api_list_sources,
    api_scheduler_jobs,
    api_sync_electricity,
    api_sync_electricity_incidents,
    api_sync_health_alerts,
    api_sync_maritime,
    api_sync_news,
    api_sync_dmi_metobs,
    api_sync_niord,
    api_sync_odin,
    api_sync_traffic,
    api_update_settings,
    health,
)
from argus.models import AppSettingsUpdate, EventCreate
from argus.repository import insert_raw_article


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
    }
    assert all(source.status == "connected" for source in sources)


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


def test_scheduler_jobs_are_returned():
    jobs = api_scheduler_jobs()
    job_intervals = {job.id: job.interval_seconds for job in jobs}

    assert job_intervals["dmi-metobs"] == 600
    assert job_intervals["dr-news"] == 600
    assert job_intervals["energidataservice-elspot"] == 600
    assert job_intervals["greenpowerdenmark-incidents"] == 600
    assert job_intervals["dma-news"] == 600
    assert job_intervals["niord-messages"] == 600
    assert job_intervals["odin-incidents"] == 600
    assert job_intervals["trafikinfo-events"] == 600
    assert "health-alerts" in job_intervals


def test_health_sync_creates_health_event(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGUS_DB_PATH", str(tmp_path / "argus.db"))
    init_db()

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


def test_electricity_sync_creates_market_stress_event(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGUS_DB_PATH", str(tmp_path / "argus.db"))
    init_db()

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
