"""Connector for RSS and Atom feeds."""

from __future__ import annotations

import re
import urllib.request
from typing import Any, Callable

import feedparser

from ..execution import ExecutionCallError, call_with_retries, stable_error_code
from ..models import ResearchItem, Source, SourceFetchOutcome, stable_id


class RssConnector:
    source_type = "rss"

    def __init__(
        self,
        opener: Callable[..., Any] = urllib.request.urlopen,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        self.opener = opener
        self.sleeper = sleeper

    def fetch(self, source: Source, limit_items: int = 20, limit_chars: int = 6000) -> list[ResearchItem]:
        items, _ = self.fetch_with_outcome(source, limit_items=limit_items, limit_chars=limit_chars)
        return items

    def fetch_with_outcome(
        self,
        source: Source,
        limit_items: int = 20,
        limit_chars: int = 6000,
        retry_config: dict[str, Any] | None = None,
        timeout_provider: Callable[[], float] | None = None,
    ) -> tuple[list[ResearchItem], SourceFetchOutcome]:
        if not source.url:
            return [], SourceFetchOutcome(source.id, source.type, "failed", "config_error", 0, attempts=0)

        retry_config = retry_config or {}
        request = urllib.request.Request(
            source.url,
            headers={
                "User-Agent": "research-platform/0.1",
                "Accept": "application/rss+xml,application/atom+xml,application/xml,text/xml,*/*;q=0.5",
            },
        )

        def retrieve() -> bytes:
            timeout = timeout_provider() if timeout_provider else float(
                retry_config.get("source_timeout_seconds", 20)
            )
            with self.opener(request, timeout=timeout) as response:
                return response.read(5_000_000)

        retry_kwargs = {
            "max_attempts": retry_config.get("max_attempts", 3),
            "initial_delay_seconds": retry_config.get("initial_delay_seconds", 0.5),
            "max_delay_seconds": retry_config.get("max_delay_seconds", 4.0),
        }
        if self.sleeper is not None:
            retry_kwargs["sleeper"] = self.sleeper
        try:
            raw, attempts = call_with_retries(retrieve, **retry_kwargs)
        except ExecutionCallError as exc:
            return [], SourceFetchOutcome(
                source.id,
                source.type,
                "failed",
                stable_error_code(exc.cause),
                0,
                attempts=exc.attempts,
            )

        parsed = feedparser.parse(raw)
        entries = list(parsed.entries[:limit_items])
        warnings = ["feed_parse_warning"] if getattr(parsed, "bozo", False) and entries else []
        if getattr(parsed, "bozo", False) and not entries:
            return [], SourceFetchOutcome(
                source.id, source.type, "failed", "invalid_feed", 0, attempts=attempts
            )
        if not entries:
            return [], SourceFetchOutcome(
                source.id, source.type, "empty", "empty_source", 0, attempts=attempts
            )

        items: list[ResearchItem] = []
        for entry in entries:
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
            entry_key = entry.get("id") or entry.get("guid") or url or title
            items.append(
                ResearchItem(
                    id=stable_id(source.id, str(entry_key)),
                    source_id=source.id,
                    source_type=source.type,
                    title=title,
                    url=url,
                    text=content[:limit_chars],
                    author=entry.get("author"),
                    published_at=entry.get("published"),
                    metadata={
                        "feed_title": parsed.feed.get("title", source.name),
                        "content_basis": "rss_entry",
                    },
                    access_rights={
                        "store_full_text": source.access.get("store_full_text", True),
                        "max_store_chars": source.access.get("max_store_chars", limit_chars),
                        "allow_external_processing": source.access.get("allow_external_processing", True),
                    },
                    provenance={
                        "connector": "rss",
                        "retrieval": "feedparser",
                        "content_basis": "rss_entry",
                        "linked_fetch_status": "not_requested",
                    },
                )
            )
        return items, SourceFetchOutcome(
            source.id,
            source.type,
            "succeeded",
            "ok",
            len(items),
            attempts=attempts,
            warnings=warnings,
        )
