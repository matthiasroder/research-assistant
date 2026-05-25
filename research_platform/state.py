"""State for runs and monitoring."""

from __future__ import annotations

import json
from pathlib import Path


class SeenStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.data = self._load()
        self.seen_ids = set(self.data.get("seen_item_ids", []))

    def has_seen(self, item_id: str) -> bool:
        return item_id in self.seen_ids

    def mark_seen(self, item_ids: list[str]) -> None:
        self.seen_ids.update(item_ids)
        self.data["seen_item_ids"] = sorted(self.seen_ids)[-5000:]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")

    def _load(self) -> dict:
        if not self.path.exists():
            return {"seen_item_ids": []}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"seen_item_ids": []}

