"""State for runs and monitoring."""

from __future__ import annotations

import json
from pathlib import Path


class SeenStore:
    """Tracks already-seen item IDs in insertion order.

    Eviction drops the oldest IDs first. (Earlier versions sorted the IDs,
    which evicted essentially at random once the cap was hit.)
    """

    def __init__(self, path: Path, max_ids: int = 5000) -> None:
        self.path = path
        self.max_ids = max_ids
        self.data = self._load()
        self._ordered = list(dict.fromkeys(self.data.get("seen_item_ids", [])))
        self._seen = set(self._ordered)

    def has_seen(self, item_id: str) -> bool:
        return item_id in self._seen

    def mark_seen(self, item_ids: list[str]) -> None:
        for item_id in item_ids:
            if item_id not in self._seen:
                self._seen.add(item_id)
                self._ordered.append(item_id)

    def save(self) -> None:
        self._ordered = self._ordered[-self.max_ids:]
        self._seen = set(self._ordered)
        self.data["seen_item_ids"] = self._ordered
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")

    def _load(self) -> dict:
        if not self.path.exists():
            return {"seen_item_ids": []}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"seen_item_ids": []}
