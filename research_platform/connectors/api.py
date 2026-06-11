"""Generic JSON API connector for licensed providers and catalogues."""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any

from ..models import ResearchItem, Source, stable_id


class ApiJsonConnector:
    source_type = "api_json"

    def fetch(self, source: Source, limit_items: int = 20, limit_chars: int = 8000) -> list[ResearchItem]:
        if not source.url:
            return []

        request = urllib.request.Request(source.url, headers=self._headers(source))
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read(5_000_000).decode("utf-8", errors="replace"))

        records = _items_at_path(payload, source.metadata.get("items_path"))
        if isinstance(records, dict):
            records = [records]
        if not isinstance(records, list):
            records = [payload]

        items: list[ResearchItem] = []
        for index, record in enumerate(records[:limit_items]):
            if not isinstance(record, dict):
                record = {"value": record}
            title = _first_value(record, source.metadata.get("title_fields", ["title", "name", "headline"])) or source.name
            url = _first_value(record, source.metadata.get("url_fields", ["url", "link", "web_url"])) or source.url
            text = "\n".join(
                value
                for value in (
                    _first_value(record, source.metadata.get("text_fields", ["description", "abstract", "summary", "content"])),
                    _first_value(record, source.metadata.get("extra_text_fields", [])),
                )
                if value
            )
            if not text:
                text = json.dumps(record, indent=2)[:limit_chars]
            store_full_text = bool(source.access.get("store_full_text", False))
            max_store_chars = int(source.access.get("max_store_chars", limit_chars if store_full_text else 1000))

            items.append(
                ResearchItem(
                    id=stable_id(source.id, url, title, str(index)),
                    source_id=source.id,
                    source_type=source.type,
                    title=title,
                    url=url,
                    text=text[:max_store_chars],
                    published_at=_first_value(record, source.metadata.get("published_fields", ["published_at", "date", "pubDate"])),
                    metadata={"provider_record": record} if source.access.get("store_raw_record", False) else {},
                    access_rights={
                        "store_full_text": store_full_text,
                        "max_store_chars": max_store_chars,
                        "license": source.access.get("license", "configured_provider"),
                    },
                    provenance={"connector": "api_json", "retrieval": "http_json"},
                )
            )
        return items

    def _headers(self, source: Source) -> dict[str, str]:
        headers = {"User-Agent": "research-platform/0.1", "Accept": "application/json"}
        access = source.access or {}
        for name, value in access.get("headers", {}).items():
            headers[name] = str(value)
        env_name = access.get("api_key_env")
        header_name = access.get("api_key_header", "Authorization")
        if env_name and os.environ.get(env_name):
            prefix = access.get("api_key_prefix", "")
            headers[header_name] = f"{prefix}{os.environ[env_name]}"
        return headers


def _items_at_path(payload: Any, path: str | None) -> Any:
    current = payload
    for part in (path or "").split("."):
        if not part:
            continue
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return current
    return current


def _first_value(record: dict[str, Any], fields: list[str]) -> str | None:
    for field in fields:
        value = record.get(field)
        if value is not None:
            return str(value)
    return None
