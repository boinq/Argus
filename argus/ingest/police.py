from __future__ import annotations

import base64
import binascii
import json
import re
from datetime import datetime, timedelta, timezone
from html import unescape
from typing import Any
from urllib.parse import unquote, urljoin
from xml.etree import ElementTree

import httpx

from argus.ingest.common import (
    DENMARK_CENTER,
    clean_html,
    clean_id,
    parse_feed_datetime,
    parse_iso_datetime,
)
from argus.ingest.odin import station_location
from argus.models import EventCreate, IngestResult
from argus.repository import delete_events_by_source, insert_raw_article, update_source_status, upsert_event


SOURCE_ID = "police-ritzau-short-messages"
SOURCE_NAME = "Police/Ritzau Short Messages"
LEGACY_SOURCE_NAMES = ("Danish Police via Ritzau",)
ENDPOINT = "https://via.ritzau.dk/rss/short-messages/latest"
BASE_URL = "https://via.ritzau.dk"

EVENT_TERMS: tuple[tuple[str, str, str, int], ...] = (
    ("faerdselsuheld", "transport", "high", 5),
    ("færdselsuheld", "transport", "high", 5),
    ("uheld", "transport", "medium", 3),
    ("motorvej", "transport", "medium", 3),
    ("spærret", "transport", "high", 4),
    ("spaerret", "transport", "high", 4),
    ("brand", "emergency", "medium", 4),
    ("ildspåsættelse", "emergency", "medium", 4),
    ("ildspaasaettelse", "emergency", "medium", 4),
    ("evakuering", "emergency", "high", 5),
    ("eksplosion", "emergency", "high", 5),
    ("sprængstof", "hybrid", "high", 5),
    ("spraengstof", "hybrid", "high", 5),
    ("demonstration", "emergency", "low", 2),
    ("til stede", "emergency", "low", 2),
    ("personpåkørsel", "transport", "high", 5),
    ("personpaakorsel", "transport", "high", 5),
    ("togtrafik", "transport", "medium", 3),
    ("sikkerhedslanding", "transport", "medium", 4),
)


def sync_police_short_messages(limit: int = 30) -> IngestResult:
    try:
        rss_items = fetch_police_rss(limit=limit)
        articles = fetch_article_details(rss_items)
    except httpx.HTTPError as error:
        update_source_status(SOURCE_ID, "error", last_error=str(error))
        return IngestResult(
            source_id=SOURCE_ID,
            observations_seen=0,
            observations_stored=0,
            events_created=0,
            events_updated=0,
            message=f"Police/Ritzau request failed: {error}",
        )

    delete_events_by_source(SOURCE_NAME)
    for legacy_source_name in LEGACY_SOURCE_NAMES:
        delete_events_by_source(legacy_source_name)
    stored = 0
    created = 0
    updated = 0
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
        observations_seen=len(rss_items),
        observations_stored=stored,
        events_created=created,
        events_updated=updated,
        message="Police/Ritzau short messages synced.",
    )


def fetch_police_rss(limit: int) -> list[dict[str, Any]]:
    with httpx.Client(timeout=20.0, follow_redirects=True) as client:
        response = client.get(ENDPOINT)
        response.raise_for_status()
    return parse_police_rss(response.text)[:limit]


def fetch_article_details(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    articles: list[dict[str, Any]] = []
    with httpx.Client(timeout=20.0, follow_redirects=True) as client:
        for item in items:
            response = client.get(item["url"])
            response.raise_for_status()
            details = parse_article_page(response.text, item)
            articles.append(details)
    return articles


def parse_police_rss(xml_text: str) -> list[dict[str, Any]]:
    root = ElementTree.fromstring(xml_text.lstrip("\ufeff"))
    items: list[dict[str, Any]] = []
    for item in root.findall(".//item"):
        title = clean_html(item.findtext("title") or "")
        url = clean_html(item.findtext("link") or item.findtext("guid") or "")
        published = parse_feed_datetime(item.findtext("pubDate"))
        if not title or not url:
            continue
        items.append(
            {
                "id": f"{SOURCE_ID}:{clean_id(url)}",
                "title": title,
                "url": url,
                "published_at": published.isoformat() if published else None,
                "summary": clean_html(item.findtext("description") or ""),
            }
        )
    return items


def parse_article_page(html: str, fallback: dict[str, Any]) -> dict[str, Any]:
    state = parse_initial_state(html)
    release_item = first_release_item(state)
    if release_item:
        metadata = release_item.get("metadata") or {}
        version = (release_item.get("versions") or [{}])[0]
        body = ((version.get("body") or {}).get("complete") or "")
        text = clean_html(body)
        url = urljoin(BASE_URL, metadata.get("url") or fallback["url"])
        published = parse_iso_datetime(metadata.get("publicationDate"))
        return {
            "id": f"{SOURCE_ID}:{metadata.get('id') or clean_id(fallback['url'])}",
            "title": clean_html(metadata.get("title") or fallback["title"]),
            "url": url,
            "published_at": published.isoformat() if published else fallback.get("published_at"),
            "summary": text or clean_html(metadata.get("metadescription") or fallback.get("summary", "")),
            "publisher": clean_html(metadata.get("publisherName") or ""),
            "publisher_city": clean_html(((metadata.get("publisher") or {}).get("city")) or ""),
        }

    title = meta_content(html, "og:title") or fallback["title"]
    summary = meta_content(html, "og:description") or fallback.get("summary", "")
    return {
        **fallback,
        "title": clean_html(title.split("|")[0]),
        "summary": clean_html(summary),
        "publisher": "",
        "publisher_city": "",
    }


def parse_initial_state(html: str) -> dict[str, Any]:
    match = re.search(r"window\.__INITIAL_STATE__\s*=\s*'(?P<value>[^']+)'", html)
    if not match:
        return {}
    try:
        decoded = base64.b64decode(match.group("value")).decode("utf-8")
        return json.loads(unquote(decoded))
    except (binascii.Error, ValueError, json.JSONDecodeError):
        return {}


def first_release_item(state: dict[str, Any]) -> dict[str, Any] | None:
    releases = state.get("release") or {}
    for release in releases.values():
        items = release.get("items") or []
        if items:
            return items[0]
    return None


def event_from_article(article: dict[str, Any]) -> EventCreate | None:
    evaluation = evaluate_police_message(article["title"], article.get("summary", ""))
    if evaluation is None:
        return None

    latitude, longitude = police_location(article)
    starts_at = (
        datetime.fromisoformat(article["published_at"])
        if article.get("published_at")
        else datetime.now(timezone.utc)
    )
    return EventCreate(
        title=f"Police: {article['title']}"[:140],
        category=evaluation["category"],
        severity=evaluation["severity"],
        status="current",
        source=SOURCE_NAME,
        description=article.get("summary") or article["title"],
        latitude=latitude,
        longitude=longitude,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=6),
    )


def evaluate_police_message(title: str, summary: str) -> dict[str, str] | None:
    normalized = normalize(f"{title} {summary}")
    best: tuple[str, str, int] | None = None
    for term, category, severity, score in EVENT_TERMS:
        if term in normalized and (best is None or score > best[2]):
            best = (category, severity, score)
    if best is None:
        return None
    return {"category": best[0], "severity": best[1]}


def police_location(article: dict[str, Any]) -> tuple[float, float]:
    text = " ".join(
        part
        for part in (
            article.get("title", ""),
            article.get("summary", ""),
            article.get("publisher_city", ""),
        )
        if part
    )
    location = station_location(text)
    return location if location != DENMARK_CENTER else DENMARK_CENTER


def meta_content(html: str, property_name: str) -> str:
    match = re.search(
        rf'<meta[^>]+property=["\']{re.escape(property_name)}["\'][^>]+content=["\'](?P<value>[^"\']*)["\']',
        html,
    )
    return unescape(match.group("value")) if match else ""


def normalize(value: str) -> str:
    normalized = value.lower()
    replacements = {
        "æ": "ae",
        "ø": "o",
        "å": "aa",
        "é": "e",
    }
    for source, target in replacements.items():
        normalized = normalized.replace(source, target)
    return re.sub(r"\s+", " ", normalized)
