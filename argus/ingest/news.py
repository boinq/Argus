from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import httpx

from argus.ingest.common import parse_rss_items
from argus.ingest.evaluator import evaluate_news_relevance
from argus.models import EventCreate, IngestResult
from argus.repository import (
    delete_events_by_source,
    get_fallback_location,
    insert_raw_article,
    update_source_status,
    upsert_event,
)


SOURCE_ID = "dr-news"
ENDPOINT = "https://www.dr.dk/nyheder/service/feeds/indland"


def sync_news(limit: int = 40) -> IngestResult:
    try:
        articles = fetch_news_articles(limit=limit)
    except httpx.HTTPError as error:
        update_source_status(SOURCE_ID, "error", last_error=str(error))
        return IngestResult(
            source_id=SOURCE_ID,
            observations_seen=0,
            observations_stored=0,
            events_created=0,
            events_updated=0,
            message=f"DR news request failed: {error}",
        )

    stored = 0
    created = 0
    updated = 0
    delete_events_by_source("DR Nyheder")
    for article in articles:
        if insert_raw_article(
            article_id=article["id"],
            source_id=SOURCE_ID,
            title=article["title"],
            url=article["url"],
            published_at=article.get("published_at"),
            summary=article.get("summary", ""),
            payload=json.dumps(article, ensure_ascii=False),
        ):
            stored += 1

        event = event_from_article(article)
        if event is None:
            continue
        _, was_created = upsert_event(event)
        if was_created:
            created += 1
        else:
            updated += 1

    update_source_status(SOURCE_ID, "connected", success=True)
    return IngestResult(
        source_id=SOURCE_ID,
        observations_seen=len(articles),
        observations_stored=stored,
        events_created=created,
        events_updated=updated,
        message="DR news synced.",
    )


def fetch_news_articles(limit: int) -> list[dict[str, Any]]:
    with httpx.Client(timeout=20.0, follow_redirects=True) as client:
        response = client.get(ENDPOINT)
        response.raise_for_status()
    return parse_rss_items(response.text)[:limit]


def event_from_article(article: dict[str, Any]) -> EventCreate | None:
    evaluation = evaluate_news_relevance(article["title"], article.get("summary", ""))
    if evaluation is None:
        return None

    starts_at = (
        datetime.fromisoformat(article["published_at"])
        if article.get("published_at")
        else datetime.now(timezone.utc)
    )
    location = get_fallback_location()
    if location is None:
        return None
    latitude, longitude = location
    return EventCreate(
        title=f"DR news signal: {article['title']}"[:140],
        category=evaluation.category,
        severity=evaluation.severity,
        status="monitoring",
        source="DR Nyheder",
        description=(article.get("summary") or article["url"])[:1000],
        latitude=latitude,
        longitude=longitude,
        starts_at=starts_at,
        ends_at=None,
    )
