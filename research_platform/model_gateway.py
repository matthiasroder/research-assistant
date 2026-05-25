"""Small model gateway with provider routing and deterministic fallback."""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from typing import Any

from .models import EvaluatedItem, ResearchBrief, ResearchItem


class ModelGateway:
    """Route model work through configured providers.

    The first provider implementation is Anthropic because the existing project
    already depends on it. If no key exists, the gateway falls back to extractive
    local heuristics so the platform still runs.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}

    def evaluate(self, item: ResearchItem, brief: ResearchBrief) -> EvaluatedItem:
        provider = self.config.get("evaluation", {}).get("provider", "local")
        if provider == "anthropic" and os.environ.get("ANTHROPIC_API_KEY"):
            try:
                return self._evaluate_with_anthropic(item, brief)
            except Exception as exc:
                fallback = self._evaluate_locally(item, brief)
                fallback.rationale = f"Anthropic evaluation failed; local fallback used: {exc}"
                return fallback
        return self._evaluate_locally(item, brief)

    def synthesize(self, evaluated_items: list[EvaluatedItem], brief: ResearchBrief) -> str:
        if not evaluated_items:
            return "No relevant items were found."
        top = sorted(evaluated_items, key=lambda item: item.relevance_score, reverse=True)
        lines = [
            f"# Findings: {brief.question}",
            "",
            "## Summary",
            "",
            f"Reviewed {len(evaluated_items)} item(s). Highest-scoring material is listed first.",
            "",
            "## Relevant Items",
            "",
        ]
        for evaluated in top:
            item = evaluated.item
            lines.append(f"### {item.title}")
            if item.url:
                lines.append(f"- URL: {item.url}")
            lines.append(f"- Source type: {item.source_type}")
            lines.append(f"- Relevance: {evaluated.relevance_score}/5")
            if evaluated.summary:
                lines.append(f"- Summary: {evaluated.summary}")
            if evaluated.key_points:
                lines.append("- Key points:")
                for point in evaluated.key_points[:4]:
                    lines.append(f"  - {point}")
            if evaluated.tags:
                lines.append(f"- Tags: {', '.join(evaluated.tags)}")
            if evaluated.rationale:
                lines.append(f"- Rationale: {evaluated.rationale}")
            lines.append("")
        return "\n".join(lines).strip() + "\n"

    def _evaluate_with_anthropic(self, item: ResearchItem, brief: ResearchBrief) -> EvaluatedItem:
        import anthropic

        model = self.config.get("evaluation", {}).get("model", "claude-haiku-4-5-20251001")
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        prompt = f"""Evaluate this research item for the brief.

BRIEF:
{brief.question}

ITEM:
Title: {item.title}
URL: {item.url}
Source type: {item.source_type}
Text:
{item.text[:8000]}

Return strict JSON with these keys:
relevance_score: integer 1-5
summary: one concise paragraph
key_points: array of strings
tags: array of short strings
rationale: concise reason for the score
"""
        response = client.messages.create(
            model=model,
            max_tokens=700,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        start = text.find("{")
        end = text.rfind("}") + 1
        data = json.loads(text[start:end])
        return EvaluatedItem(
            item=item,
            relevance_score=int(data.get("relevance_score", 1)),
            summary=str(data.get("summary", "")),
            key_points=[str(point) for point in data.get("key_points", [])],
            tags=[str(tag) for tag in data.get("tags", [])],
            rationale=str(data.get("rationale", "")),
        )

    def _evaluate_locally(self, item: ResearchItem, brief: ResearchBrief) -> EvaluatedItem:
        query_terms = _important_terms(brief.question)
        text = f"{item.title}\n{item.text}".lower()
        hits = [term for term in query_terms if term in text]
        score = min(5, max(1, 1 + len(set(hits))))
        sentences = _sentences(item.text)
        summary = " ".join(sentences[:2]) if sentences else item.title
        key_points = sentences[:4]
        tags = [term for term, _ in Counter(hits).most_common(6)]
        rationale = (
            f"Matched query terms: {', '.join(sorted(set(hits)))}"
            if hits
            else "No strong lexical overlap with the brief."
        )
        return EvaluatedItem(
            item=item,
            relevance_score=score,
            summary=summary[:700],
            key_points=[point[:300] for point in key_points],
            tags=tags,
            rationale=rationale,
        )


STOPWORDS = {
    "about",
    "after",
    "again",
    "against",
    "also",
    "and",
    "are",
    "can",
    "for",
    "from",
    "how",
    "into",
    "its",
    "our",
    "research",
    "that",
    "the",
    "this",
    "what",
    "with",
}


def _important_terms(text: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-zA-Z][a-zA-Z0-9-]{2,}", text.lower())
        if token not in STOPWORDS
    ][:30]


def _sentences(text: str) -> list[str]:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return []
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", cleaned) if len(part.strip()) > 20]

