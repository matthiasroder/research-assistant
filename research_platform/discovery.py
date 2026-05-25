"""Source discovery helpers."""

from __future__ import annotations

from urllib.parse import urlparse

from .connectors.search import discover_web_sources
from .connectors.web import WebpageConnector
from .models import Source


def source_type_for_url(url: str) -> str:
    host = urlparse(url).netloc.lower()
    path = urlparse(url).path.lower()
    if "twitter.com" in host or "x.com" in host:
        return "x_post" if "/status/" in url else "x_profile"
    if (
        "rss" in host
        or url.endswith((".xml", ".rss", ".atom"))
        or "feed" in path
        or "atom" in path
    ):
        return "rss"
    return "webpage"


def sources_from_urls(urls: list[str]) -> list[Source]:
    return [Source.from_url(url, source_type_for_url(url)) for url in urls]


def discover_sources(topic: str, seed_urls: list[str] | None = None, max_sources: int = 8) -> list[Source]:
    sources: list[Source] = []
    seen: set[str] = set()

    for source in sources_from_urls(seed_urls or []):
        if source.id not in seen:
            sources.append(source)
            seen.add(source.id)

    if seed_urls:
        for feed_url in WebpageConnector().discover_feed_urls(seed_urls):
            source = Source.from_url(feed_url, "rss")
            if source.id not in seen:
                sources.append(source)
                seen.add(source.id)

    try:
        for source in discover_web_sources(topic, max_sources=max_sources):
            if source.id not in seen:
                sources.append(source)
                seen.add(source.id)
    except Exception:
        pass

    return sources[:max_sources]
