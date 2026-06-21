from __future__ import annotations

import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from typing import Any
from xml.etree import ElementTree


def clean_html(value: str | None) -> str:
    if not value:
        return ""
    text = re.sub(r"<[^>]+>", " ", value)
    text = unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def parse_rss_items(xml_text: str) -> list[dict[str, Any]]:
    root = ElementTree.fromstring(xml_text)
    items: list[dict[str, Any]] = []
    for item in root.findall(".//item"):
        title = item.findtext("title") or ""
        link = item.findtext("link") or ""
        description = item.findtext("description") or ""
        published = parse_feed_datetime(item.findtext("pubDate"))
        guid = item.findtext("guid") or link or title
        if not title:
            continue
        items.append(
            {
                "id": clean_id(guid),
                "title": clean_html(title),
                "summary": clean_html(description),
                "url": link.strip(),
                "published_at": published.isoformat() if published else None,
            }
        )
    return items


def parse_feed_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return parse_iso_datetime(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def clean_id(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_.:-]+", ":", value.strip())
    return normalized.strip(":")[:240] or "item"
