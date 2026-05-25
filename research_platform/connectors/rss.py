"""Connector for RSS and Atom feeds."""

from __future__ import annotations

import re

import feedparser

from ..models import ResearchItem, Source, stable_id


class RssConnector:
    source_type = "rss"

    def fetch(self, source: Source, limit_items: int = 20, limit_chars: int = 6000) -> list[ResearchItem]:
        if not source.url:
            return []

        parsed = feedparser.parse(source.url)
        items: list[ResearchItem] = []
        for entry in parsed.entries[:limit_items]:
            content = ""
            if hasattr(entry, "content") and entry.content:
                content = entry.content[0].get("value", "")
            elif hasattr(entry, "summary"):
                content = entry.summary
            elif hasattr(entry, "description"):
                content = entry.description
            content = re.sub(r"<[^>]+>", "", content).strip()
            url = entry.get("link", "")
            title = entry.get("title", "Untitled")
            items.append(
                ResearchItem(
                    id=stable_id(source.id, url, title),
                    source_id=source.id,
                    source_type=source.type,
                    title=title,
                    url=url,
                    text=content[:limit_chars],
                    author=entry.get("author"),
                    published_at=entry.get("published"),
                    metadata={"feed_title": parsed.feed.get("title", source.name)},
                    provenance={"connector": "rss", "retrieval": "feedparser"},
                )
            )
        return items

