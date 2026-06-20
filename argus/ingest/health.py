from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from html import unescape
from typing import Any

import httpx

from argus.models import EventCreate, IngestResult
from argus.repository import (
    delete_events_by_source,
    insert_raw_article,
    update_source_status,
    upsert_event,
)


SOURCE_ID = "health-alerts"
ENDPOINT = "https://www.sst.dk/nyheder"
SST_BASE_URL = "https://www.sst.dk"
HEALTH_KEYWORDS = (
    "alment farlig",
    "anbefalinger til rejsende",
    "beredskab",
    "hantavirus",
    "influenza",
    "kritiske infrastruktur",
    "opioid",
    "rs-virus",
    "smitsomme sygdomme",
    "udbrud",
    "vaccin",
)


def sync_health_alerts(limit: int = 25) -> IngestResult:
    try:
        articles = fetch_health_articles(limit=limit)
    except httpx.HTTPError as error:
        update_source_status(SOURCE_ID, "error", last_error=str(error))
        return IngestResult(
            source_id=SOURCE_ID,
            observations_seen=0,
            observations_stored=0,
            events_created=0,
            events_updated=0,
            message=f"SST request failed: {error}",
        )

    stored = 0
    created = 0
    updated = 0
    delete_events_by_source("Sundhedsstyrelsen")
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
        message="Danish health alerts synced.",
    )


def fetch_health_articles(limit: int) -> list[dict[str, Any]]:
    with httpx.Client(timeout=20.0, follow_redirects=True) as client:
        response = client.get(ENDPOINT)
        response.raise_for_status()
    return parse_health_articles(response.text)[:limit]


def parse_health_articles(html: str) -> list[dict[str, Any]]:
    articles: list[dict[str, Any]] = []
    seen: set[str] = set()
    href_pattern = re.compile(r'\\"href\\":\\"(?P<href>/nyheder/[^\\"]+)\\"')
    for match in href_pattern.finditer(html):
        href = unescape(match.group("href").replace("\\u002F", "/"))
        if href in seen:
            continue
        seen.add(href)
        window = html[match.end() : match.end() + 2600]
        title = first_match(
            window,
            r'\\"className\\":\\"mb-2 body-md[^\\"]*\\".*?\\"children\\":\\"(?P<value>[^\\"]+)\\"',
        )
        if not title:
            continue
        summary = first_match(
            window,
            r'\\"className\\":\\"mb-6 body-sm[^\\"]*\\".*?\\"children\\":\\"(?P<value>[^\\"]*)\\"',
        ) or ""
        published = first_match(window, r'\\"dateTime\\":\\"(?P<value>[^\\"]+)\\"')
        articles.append(
            {
                "id": href.strip("/").replace("/", ":"),
                "title": clean_text(title),
                "summary": clean_text(summary),
                "url": f"{SST_BASE_URL}{href}",
                "published_at": parse_danish_date(published),
            }
        )
    return articles


def first_match(text: str, pattern: str) -> str | None:
    match = re.search(pattern, text)
    return match.group("value") if match else None


def clean_text(value: str) -> str:
    return unescape(value).replace('\\"', '"').strip()


def parse_danish_date(value: str | None) -> str | None:
    if not value:
        return None
    months = {
        "januar": 1,
        "februar": 2,
        "marts": 3,
        "april": 4,
        "maj": 5,
        "juni": 6,
        "juli": 7,
        "august": 8,
        "september": 9,
        "oktober": 10,
        "november": 11,
        "december": 12,
    }
    match = re.search(r"(?P<day>\d{1,2})\.\s+(?P<month>\w+)\s+(?P<year>\d{4})", value)
    if not match:
        return None
    month = months.get(match.group("month").lower())
    if month is None:
        return None
    return datetime(
        int(match.group("year")),
        month,
        int(match.group("day")),
        tzinfo=timezone.utc,
    ).isoformat()


def event_from_article(article: dict[str, Any]) -> EventCreate | None:
    haystack = f"{article['title']} {article.get('summary', '')}".lower()
    if not any(keyword in haystack for keyword in HEALTH_KEYWORDS):
        return None

    severity = "high" if any(word in haystack for word in ("alment farlig", "udbrud", "kritiske")) else "medium"
    starts_at = (
        datetime.fromisoformat(article["published_at"])
        if article.get("published_at")
        else datetime.now(timezone.utc)
    )
    return EventCreate(
        title=f"SST health notice: {article['title']}"[:140],
        category="health",
        severity=severity,
        status="monitoring",
        source="Sundhedsstyrelsen",
        description=(article.get("summary") or article["url"])[:1000],
        latitude=55.676,
        longitude=12.568,
        starts_at=starts_at,
        ends_at=None,
    )
