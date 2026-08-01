"""Durable, backward-compatible state for monitoring runs."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .models import utc_now


class StateCorruptionError(RuntimeError):
    """Raised instead of silently replacing unreadable monitoring state."""


class SeenStore:
    """Tracks acknowledged item IDs in insertion order.

    Version-one files containing only ``seen_item_ids`` load without a write.
    Version two retains that list for legacy readers and adds auditable status.
    """

    def __init__(self, path: Path, max_ids: int = 5000) -> None:
        self.path = path
        self.max_ids = max(1, int(max_ids))
        self.data = self._load()
        self._ordered = list(dict.fromkeys(self.data.get("seen_item_ids", [])))
        self._seen = set(self._ordered)
        self._item_status = dict(self.data.get("item_status", {}))

    def has_seen(self, item_id: str) -> bool:
        return item_id in self._seen

    def record_attempt(
        self,
        item_id: str,
        *,
        source_id: str,
        run_id: str,
        outcome_code: str,
    ) -> None:
        previous = self._item_status.get(item_id, {})
        self._item_status[item_id] = {
            **previous,
            "status": previous.get("status", "attempted"),
            "source_id": source_id,
            "run_id": run_id,
            "attempt_count": int(previous.get("attempt_count", 0)) + 1,
            "last_attempt_at": utc_now(),
            "last_outcome_code": outcome_code,
        }

    def acknowledge(self, item_ids: list[str], run_id: str | None = None) -> None:
        acknowledged_at = utc_now()
        for item_id in item_ids:
            if item_id not in self._seen:
                self._seen.add(item_id)
                self._ordered.append(item_id)
            previous = self._item_status.get(item_id, {})
            self._item_status[item_id] = {
                **previous,
                "status": "acknowledged",
                "run_id": run_id or previous.get("run_id"),
                "acknowledged_at": previous.get("acknowledged_at", acknowledged_at),
            }

    def mark_seen(self, item_ids: list[str]) -> None:
        """Legacy alias for acknowledge."""

        self.acknowledge(item_ids)

    def save(self) -> None:
        self._ordered = self._ordered[-self.max_ids :]
        self._seen = set(self._ordered)
        retained = set(self._ordered)
        self._item_status = {
            item_id: status
            for item_id, status in self._item_status.items()
            if item_id in retained or status.get("status") != "acknowledged"
        }
        payload = {
            "schema_version": 2,
            "seen_item_ids": self._ordered,
            "item_status": self._item_status,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self.path)
        finally:
            if temporary_path.exists():
                temporary_path.unlink()
        self.data = payload

    def _load(self) -> dict:
        if not self.path.exists():
            return {"schema_version": 2, "seen_item_ids": [], "item_status": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise StateCorruptionError("monitoring state is unreadable") from exc
        if not isinstance(data, dict):
            raise StateCorruptionError("monitoring state must be an object")
        seen = data.get("seen_item_ids", [])
        if not isinstance(seen, list) or not all(isinstance(item_id, str) for item_id in seen):
            raise StateCorruptionError("seen_item_ids must be a list of strings")
        schema_version = data.get("schema_version", 1)
        if schema_version not in {1, 2}:
            raise StateCorruptionError("unsupported monitoring state schema")
        item_status = data.get("item_status", {})
        if not isinstance(item_status, dict):
            raise StateCorruptionError("item_status must be an object")
        self._validate_item_status(item_status)
        return {
            "schema_version": schema_version,
            "seen_item_ids": seen,
            "item_status": item_status,
        }

    @staticmethod
    def _validate_item_status(item_status: dict) -> None:
        allowed_fields = {
            "status",
            "source_id",
            "run_id",
            "attempt_count",
            "last_attempt_at",
            "last_outcome_code",
            "acknowledged_at",
        }
        string_or_none_fields = {
            "source_id",
            "run_id",
            "last_attempt_at",
            "last_outcome_code",
            "acknowledged_at",
        }
        for item_id, status in item_status.items():
            if not isinstance(item_id, str) or not isinstance(status, dict):
                raise StateCorruptionError("item_status entries must map string IDs to objects")
            unknown = set(status) - allowed_fields
            if unknown:
                raise StateCorruptionError("item_status contains unsupported fields")
            if status.get("status") not in {"attempted", "acknowledged"}:
                raise StateCorruptionError("item_status status is invalid")
            attempt_count = status.get("attempt_count")
            if attempt_count is not None and (
                isinstance(attempt_count, bool)
                or not isinstance(attempt_count, int)
                or attempt_count < 0
            ):
                raise StateCorruptionError("item_status attempt_count is invalid")
            for field in string_or_none_fields:
                value = status.get(field)
                if value is not None and not isinstance(value, str):
                    raise StateCorruptionError(f"item_status {field} is invalid")
