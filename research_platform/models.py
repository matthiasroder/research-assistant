"""Shared data contracts for research workflows."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_id(*parts: str | None) -> str:
    raw = "|".join(part or "" for part in parts)
    return sha256(raw.encode("utf-8")).hexdigest()[:16]


@dataclass
class ResearchBrief:
    """A user's research intent for one run."""

    question: str
    mode: str
    topics: list[str] = field(default_factory=list)
    constraints: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Source:
    """A place the platform can query, monitor, or fetch from."""

    id: str
    type: str
    name: str
    url: str | None = None
    access: dict[str, Any] = field(default_factory=lambda: {"method": "public"})
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_url(cls, url: str, source_type: str = "webpage", name: str | None = None) -> "Source":
        return cls(
            id=stable_id(source_type, url),
            type=source_type,
            name=name or url,
            url=url,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ResearchItem:
    """A normalized unit of evidence, independent of source type."""

    id: str
    source_id: str
    source_type: str
    title: str
    url: str | None
    text: str
    author: str | None = None
    published_at: str | None = None
    retrieved_at: str = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)
    access_rights: dict[str, Any] = field(default_factory=lambda: {"store_full_text": True})
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EvaluatedItem:
    """A research item plus the platform's judgment about it."""

    item: ResearchItem
    relevance_score: int
    summary: str
    key_points: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["item"] = self.item.to_dict()
        return data


@dataclass
class RunResult:
    """Serializable result for one platform run."""

    run_id: str
    brief: ResearchBrief
    sources: list[Source]
    items: list[ResearchItem]
    evaluated_items: list[EvaluatedItem]
    findings_markdown: str
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "brief": self.brief.to_dict(),
            "sources": [source.to_dict() for source in self.sources],
            "items": [item.to_dict() for item in self.items],
            "evaluated_items": [item.to_dict() for item in self.evaluated_items],
            "findings_markdown": self.findings_markdown,
            "created_at": self.created_at,
        }

