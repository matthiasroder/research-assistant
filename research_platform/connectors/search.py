"""Lightweight source discovery via public search result pages."""

from __future__ import annotations

import re
import urllib.parse
import urllib.request

from ..models import Source, stable_id


DUCKDUCKGO_HTML = "https://duckduckgo.com/html/?q={query}"


def discover_web_sources(query: str, max_sources: int = 8) -> list[Source]:
    """Return candidate webpage sources for a topic.

    This is intentionally conservative: it only discovers candidate URLs. The
    evaluation layer still decides whether fetched items matter.
    """

    url = DUCKDUCKGO_HTML.format(query=urllib.parse.quote_plus(query))
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "research-platform/0.1",
            "Accept": "text/html,*/*;q=0.8",
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        html = response.read(1_000_000).decode("utf-8", errors="replace")

    urls: list[str] = []
    for encoded in re.findall(r"uddg=([^&\"']+)", html):
        candidate = urllib.parse.unquote(encoded)
        if candidate.startswith("http") and candidate not in urls:
            urls.append(candidate)
        if len(urls) >= max_sources:
            break

    sources = []
    for candidate in urls:
        parsed = urllib.parse.urlparse(candidate)
        name = parsed.netloc.replace("www.", "") or candidate
        sources.append(
            Source(
                id=stable_id("webpage", candidate),
                type="webpage",
                name=name,
                url=candidate,
                metadata={"discovered_by": "duckduckgo_html", "query": query},
            )
        )
    return sources

