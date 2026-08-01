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
class EvidenceRef:
    """An exact, bounded excerpt supporting a claim."""

    item_id: str
    excerpt: str
    start: int
    end: int
    text_sha256: str
    excerpt_sha256: str


@dataclass
class GroundedClaim:
    """A substantive claim with exact evidence in its ResearchItem text."""

    id: str
    text: str
    evidence: list[EvidenceRef] = field(default_factory=list)


@dataclass
class ProviderExecution:
    """Sanitized, serializable metadata for one model operation."""

    operation: str
    status: str
    outcome_code: str
    requested_provider: str | None = None
    used_provider: str | None = None
    model: str | None = None
    attempts: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost_usd: str | None = None
    fallback_reason_code: str | None = None
    error_code: str | None = None


@dataclass
class SourceFetchOutcome:
    """Observable result of fetching one configured source."""

    source_id: str
    source_type: str
    status: str
    outcome_code: str
    item_count: int
    attempts: int = 1
    warnings: list[str] = field(default_factory=list)


@dataclass
class BudgetUsage:
    """Run-level limits and consumption."""

    limits: dict[str, Any] = field(default_factory=dict)
    used: dict[str, Any] = field(default_factory=dict)
    status: str = "within_limit"
    exhausted_limit: str | None = None


@dataclass
class RunHealth:
    """Same-run health contract for downstream delivery gates."""

    run_id: str
    status: str
    blocking_codes: list[str] = field(default_factory=list)
    checked_at: str = field(default_factory=utc_now)


@dataclass
class EvaluatedItem:
    """A research item plus the platform's judgment about it."""

    item: ResearchItem
    relevance_score: int
    summary: str
    key_points: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    rationale: str = ""
    grounded_claims: list[GroundedClaim] = field(default_factory=list)
    uncertainties: list[str] = field(default_factory=list)
    execution: ProviderExecution | None = None
    schema_version: int = 2

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
    source_outcomes: list[SourceFetchOutcome] = field(default_factory=list)
    synthesis_execution: ProviderExecution | None = None
    budget: BudgetUsage | None = None
    health: RunHealth | None = None
    acknowledgment: dict[str, Any] = field(default_factory=dict)
    schema_version: int = 2

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "brief": self.brief.to_dict(),
            "sources": [source.to_dict() for source in self.sources],
            "items": [item.to_dict() for item in self.items],
            "evaluated_items": [item.to_dict() for item in self.evaluated_items],
            "findings_markdown": self.findings_markdown,
            "created_at": self.created_at,
            "source_outcomes": [asdict(outcome) for outcome in self.source_outcomes],
            "synthesis_execution": asdict(self.synthesis_execution) if self.synthesis_execution else None,
            "budget": asdict(self.budget) if self.budget else None,
            "health": asdict(self.health) if self.health else None,
            "acknowledgment": self.acknowledgment,
            "schema_version": self.schema_version,
        }
