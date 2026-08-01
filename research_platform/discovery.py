"""Source discovery helpers."""

from __future__ import annotations

import sys
from urllib.parse import urlparse

from .connectors.search import discover_web_sources
from .connectors.web import WebpageConnector
from .execution import stable_error_code
from .models import Source


def source_type_for_url(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    path = parsed.path.lower()
    if _is_x_or_twitter_host(host):
        return "x_post" if "/status/" in path else "x_profile"
    if (
        "rss" in host
        or url.endswith((".xml", ".rss", ".atom"))
        or "feed" in path
        or "atom" in path
    ):
        return "rss"
    return "webpage"


def _is_x_or_twitter_host(host: str) -> bool:
    return host in {"x.com", "twitter.com"} or host.endswith(".x.com") or host.endswith(".twitter.com")


def sources_from_urls(urls: list[str]) -> list[Source]:
    return [Source.from_url(url, source_type_for_url(url)) for url in urls]


def discover_sources(topic: str, seed_urls: list[str] | None = None, max_sources: int = 8) -> list[Source]:
    sources: list[Source] = []
    seen: set[str] = set()

    def add(source: Source) -> None:
        if source.id not in seen:
            sources.append(source)
            seen.add(source.id)

    for source in sources_from_urls(seed_urls or []):
        add(source)

    # Web search results come before guessed feed URLs so unverified
    # /feed, /rss guesses cannot crowd real results out of max_sources.
    try:
        for source in discover_web_sources(topic, max_sources=max_sources):
            add(source)
    except Exception as exc:
        print(f"Warning: web search discovery failed ({stable_error_code(exc)}).", file=sys.stderr)

    if seed_urls:
        for feed_url in WebpageConnector().discover_feed_urls(seed_urls):
            add(Source.from_url(feed_url, "rss"))

    return sources[:max_sources]
