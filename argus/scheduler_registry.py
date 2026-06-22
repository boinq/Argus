from __future__ import annotations

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
from argus.scheduler import PollJob, PollScheduler, env_bool, env_int


def create_scheduler(*, enabled: bool | None = None) -> PollScheduler:
    scheduler = PollScheduler(
        enabled=env_bool("ARGUS_SCHEDULER_ENABLED", True) if enabled is None else enabled,
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
            id="police-ritzau-short-messages",
            source_id="police-ritzau-short-messages",
            name="Police/Ritzau short messages",
            interval_seconds=max(60, env_int("ARGUS_POLICE_RSS_INTERVAL_SECONDS", 600)),
            handler=sync_police_short_messages,
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
    return scheduler
