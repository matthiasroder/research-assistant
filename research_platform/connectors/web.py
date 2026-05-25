"""Connector for normal web pages."""

from __future__ import annotations

import re
import urllib.request
from html.parser import HTMLParser
from typing import Iterable
from urllib.parse import urljoin, urlparse

from ..models import ResearchItem, Source, stable_id


class _ReadableHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        self._in_title = False
        self._skip_depth = 0
        self._parts: list[str] = []
        self.feed_links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {name.lower(): value or "" for name, value in attrs}
        if tag == "title":
            self._in_title = True
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1
        if tag == "link":
            rel = attrs_dict.get("rel", "").lower()
            kind = attrs_dict.get("type", "").lower()
            href = attrs_dict.get("href")
            if href and ("alternate" in rel or "rss" in kind or "atom" in kind):
                self.feed_links.append(href)
        if tag in {"p", "br", "li", "h1", "h2", "h3", "article", "section"}:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        if tag in {"script", "style", "noscript", "svg"} and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        cleaned = re.sub(r"\s+", " ", data).strip()
        if not cleaned:
            return
        if self._in_title:
            self.title = f"{self.title} {cleaned}".strip()
        elif self._skip_depth == 0:
            self._parts.append(cleaned)

    @property
    def text(self) -> str:
        return re.sub(r"\n{3,}", "\n\n", " ".join(self._parts)).strip()


class WebpageConnector:
    source_type = "webpage"

    def fetch(self, source: Source, limit_chars: int = 12000) -> list[ResearchItem]:
        if not source.url:
            return []

        request = urllib.request.Request(
            source.url,
            headers={
                "User-Agent": "research-platform/0.1 (+https://example.local)",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            content_type = response.headers.get("content-type", "")
            raw = response.read(2_000_000)

        text = raw.decode("utf-8", errors="replace")
        if "html" in content_type or "<html" in text[:500].lower():
            parser = _ReadableHtmlParser()
            parser.feed(text)
            title = parser.title or source.name
            body = parser.text[:limit_chars]
            feed_links = [urljoin(source.url, link) for link in parser.feed_links]
        else:
            title = source.name
            body = text[:limit_chars]
            feed_links = []

        item = ResearchItem(
            id=stable_id(source.id, source.url, title),
            source_id=source.id,
            source_type=source.type,
            title=title,
            url=source.url,
            text=body,
            metadata={"content_type": content_type, "feed_links": feed_links},
            provenance={"connector": "webpage", "retrieval": "urlopen"},
        )
        return [item]

    def discover_feed_urls(self, urls: Iterable[str]) -> list[str]:
        discovered: list[str] = []
        for url in urls:
            try:
                source = Source.from_url(url)
                items = self.fetch(source, limit_chars=1000)
            except Exception:
                continue
            for link in items[0].metadata.get("feed_links", []):
                if link not in discovered:
                    discovered.append(link)
            parsed = urlparse(url)
            if parsed.scheme and parsed.netloc:
                for suffix in ("/feed", "/rss", "/atom.xml", "/feed.xml"):
                    candidate = f"{parsed.scheme}://{parsed.netloc}{suffix}"
                    if candidate not in discovered:
                        discovered.append(candidate)
        return discovered

