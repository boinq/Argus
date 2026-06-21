from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from html import unescape
from typing import Any

import httpx

from argus.ingest.common import clean_html
from argus.ingest.evaluator import evaluate_maritime_relevance
from argus.models import EventCreate, IngestResult
from argus.repository import (
    delete_events_by_source,
    get_fallback_location,
    insert_raw_article,
    update_source_status,
    upsert_event,
)


SOURCE_ID = "dma-news"
DMA_BASE_URL = "https://www.dma.dk"
ENDPOINT = "https://www.dma.dk/news"


def sync_maritime(limit: int = 30) -> IngestResult:
    try:
        articles = fetch_maritime_articles(limit=limit)
    except httpx.HTTPError as error:
        update_source_status(SOURCE_ID, "error", last_error=str(error))
        return IngestResult(
            source_id=SOURCE_ID,
            observations_seen=0,
            observations_stored=0,
            events_created=0,
            events_updated=0,
            message=f"DMA news request failed: {error}",
        )

    stored = 0
    created = 0
    updated = 0
    delete_events_by_source("Danish Maritime Authority")
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
        message="Danish Maritime Authority news synced.",
    )


def fetch_maritime_articles(limit: int) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)
    month_url = f"{ENDPOINT}/{now.year}/{now.strftime('%B').lower()}"
    with httpx.Client(timeout=20.0, follow_redirects=True) as client:
        response = client.get(month_url)
        response.raise_for_status()
    return parse_maritime_archive(response.text, month_url, now)[:limit]


def parse_maritime_archive(html: str, archive_url: str, now: datetime) -> list[dict[str, Any]]:
    articles: list[dict[str, Any]] = []
    seen: set[str] = set()
    pattern = re.compile(r'<a href="(?P<href>/news/\d{4}/[a-z]+/[^"]+)"[^>]*>(?P<title>.*?)</a>')
    for match in pattern.finditer(html):
        href = unescape(match.group("href"))
        title = clean_html(match.group("title"))
        if not title or href in seen:
            continue
        seen.add(href)
        articles.append(
            {
                "id": href.strip("/").replace("/", ":"),
                "title": title,
                "summary": f"DMA news item listed in {archive_url}",
                "url": f"{DMA_BASE_URL}{href}",
                "published_at": now.isoformat(),
            }
        )
    return articles


def event_from_article(article: dict[str, Any]) -> EventCreate | None:
    evaluation = evaluate_maritime_relevance(article["title"], article.get("summary", ""))
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
        title=f"DMA maritime notice: {article['title']}"[:140],
        category="maritime",
        severity=evaluation.severity,
        status="monitoring",
        source="Danish Maritime Authority",
        description=(article.get("summary") or article["url"])[:1000],
        latitude=latitude,
        longitude=longitude,
        starts_at=starts_at,
        ends_at=None,
    )
