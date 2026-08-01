"""Connectors for social sources.

The first slice can normalize X/Twitter URLs. Authenticated timeline/search
retrieval belongs behind this connector later.
"""

from __future__ import annotations

import re

from ..models import ResearchItem, Source, stable_id


X_STATUS_RE = re.compile(r"https?://(?:www\.)?(?:x|twitter)\.com/([^/]+)/status/(\d+)")


class XConnector:
    source_type = "x"

    def fetch(self, source: Source) -> list[ResearchItem]:
        if not source.url:
            return []

        match = X_STATUS_RE.search(source.url)
        author = match.group(1) if match else _handle_from_url(source.url)
        status_id = match.group(2) if match else None
        title = f"X post by @{author}" if status_id and author else f"X profile @{author}" if author else "X/Twitter URL"
        text = _placeholder_text(source.type)
        return [
            ResearchItem(
                id=stable_id(source.id, source.url, status_id),
                source_id=source.id,
                source_type=source.type,
                title=title,
                url=source.url,
                text=text,
                author=author,
                metadata={"status_id": status_id, "requires_authenticated_retrieval": True},
                access_rights={
                    "store_full_text": False,
                    "allow_external_processing": False,
                    "reason": "social/auth connector not configured",
                },
                provenance={"connector": source.type, "retrieval": "url_normalization"},
            )
        ]


def _handle_from_url(url: str) -> str | None:
    parts = url.rstrip("/").split("/")
    if len(parts) >= 4 and ("x.com" in parts[2] or "twitter.com" in parts[2]):
        handle = parts[3]
        if handle and handle not in {"home", "explore", "search"}:
            return handle
    return None


def _placeholder_text(source_type: str) -> str:
    if source_type == "x_profile":
        return (
            "X/Twitter profile metadata placeholder. Configure an authenticated X API, "
            "browser-session, export, or list connector to retrieve timeline items."
        )
    return (
        "X/Twitter post metadata placeholder. Configure an authenticated X API, "
        "browser-session, or export connector to retrieve full post text."
    )
