"""CLI runner for the first research-platform slice."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from .connectors import ApiJsonConnector, RssConnector, WebpageConnector, XConnector
from .discovery import discover_sources, sources_from_urls
from .model_gateway import ModelGateway
from .models import ResearchBrief, ResearchItem, RunResult, Source
from .state import SeenStore


CONNECTORS = {
    "api_json": ApiJsonConnector(),
    "webpage": WebpageConnector(),
    "rss": RssConnector(),
    "x_post": XConnector(),
    "x_profile": XConnector(),
}


def load_config(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists():
        return {}
    with path.open() as handle:
        return yaml.safe_load(handle) or {}


def load_source_file(path: Path | None) -> list[Source]:
    if not path or not path.exists():
        return []
    with path.open() as handle:
        data = yaml.safe_load(handle) or {}
    sources = []
    for entry in data.get("sources", []):
        sources.append(
            Source(
                id=entry.get("id") or entry.get("name") or entry["url"],
                type=entry["type"],
                name=entry.get("name") or entry.get("url") or entry["type"],
                url=entry.get("url"),
                access=entry.get("access", {"method": "public"}),
                metadata=entry.get("metadata", {}),
            )
        )
    return sources


def fetch_items(sources: list, max_items_per_source: int = 20) -> list[ResearchItem]:
    items: list[ResearchItem] = []
    for source in sources:
        connector = CONNECTORS.get(source.type)
        if not connector:
            continue
        try:
            if source.type in {"api_json", "rss"}:
                fetched = connector.fetch(source, limit_items=max_items_per_source)
            else:
                fetched = connector.fetch(source)
            items.extend(fetched)
        except Exception as exc:
            items.append(
                ResearchItem(
                    id=f"error-{source.id}",
                    source_id=source.id,
                    source_type=source.type,
                    title=f"Failed to fetch {source.name}",
                    url=source.url,
                    text=f"Fetch error: {exc}",
                    metadata={"error": str(exc)},
                    access_rights={"store_full_text": False},
                    provenance={"connector": source.type, "retrieval": "failed"},
                )
            )
    return items


def run(
    brief: ResearchBrief,
    urls: list[str],
    config: dict[str, Any],
    repo_root: Path,
    max_sources: int = 8,
    max_items_per_source: int = 20,
    configured_sources: list[Source] | None = None,
) -> tuple[RunResult, Path]:
    run_id = make_run_id(brief.question)
    run_dir = repo_root / "runs" / run_id
    state_path = repo_root / "knowledge" / "platform_state.json"

    if configured_sources:
        sources = configured_sources + sources_from_urls(urls)
    elif brief.mode == "research-topic":
        sources = discover_sources(brief.question, seed_urls=urls, max_sources=max_sources)
    else:
        sources = sources_from_urls(urls)

    items = fetch_items(sources, max_items_per_source=max_items_per_source)
    seen_store = SeenStore(state_path)
    if brief.mode == "monitor-sources":
        items_to_evaluate = [item for item in items if not seen_store.has_seen(item.id)]
    else:
        items_to_evaluate = items

    gateway = ModelGateway(config.get("models", {}))
    evaluated = [gateway.evaluate(item, brief) for item in items_to_evaluate]
    evaluated = [item for item in evaluated if item.relevance_score >= config.get("min_relevance_score", 1)]
    findings = gateway.synthesize(evaluated, brief)

    result = RunResult(
        run_id=run_id,
        brief=brief,
        sources=sources,
        items=items,
        evaluated_items=evaluated,
        findings_markdown=findings,
    )
    write_run(run_dir, result)
    if brief.mode == "monitor-sources":
        seen_store.mark_seen([item.id for item in items])
        seen_store.save()
    return result, run_dir


def write_run(run_dir: Path, result: RunResult) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "brief.md").write_text(f"# Brief\n\n{result.brief.question}\n", encoding="utf-8")
    (run_dir / "sources.json").write_text(
        json.dumps([source.to_dict() for source in result.sources], indent=2),
        encoding="utf-8",
    )
    (run_dir / "items.json").write_text(
        json.dumps([item.to_dict() for item in result.items], indent=2),
        encoding="utf-8",
    )
    (run_dir / "evaluated_items.json").write_text(
        json.dumps([item.to_dict() for item in result.evaluated_items], indent=2),
        encoding="utf-8",
    )
    (run_dir / "findings.md").write_text(result.findings_markdown, encoding="utf-8")
    (run_dir / "run.json").write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")


def make_run_id(question: str) -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    slug = re.sub(r"[^a-z0-9]+", "-", question.lower()).strip("-")[:48] or "research-run"
    return f"{today}-{slug}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a small agentic research workflow.")
    parser.add_argument("mode", choices=["analyze-url", "research-topic", "monitor-sources"])
    parser.add_argument("--brief", required=True, help="Research question or monitoring intent.")
    parser.add_argument("--url", action="append", default=[], help="Source URL. Can be passed multiple times.")
    parser.add_argument("--config", default="config/research.yaml", help="Platform config path.")
    parser.add_argument("--source-file", help="YAML file with configured sources.")
    parser.add_argument("--max-sources", type=int, default=8)
    parser.add_argument("--max-items-per-source", type=int, default=20)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    repo_root = Path.cwd()
    config = load_config(repo_root / args.config)
    configured_sources = load_source_file(repo_root / args.source_file) if args.source_file else []
    brief = ResearchBrief(question=args.brief, mode=args.mode)
    result, run_dir = run(
        brief=brief,
        urls=args.url,
        config=config,
        repo_root=repo_root,
        max_sources=args.max_sources,
        max_items_per_source=args.max_items_per_source,
        configured_sources=configured_sources,
    )
    print(f"Run: {result.run_id}")
    print(f"Sources: {len(result.sources)}")
    print(f"Items: {len(result.items)}")
    print(f"Evaluated: {len(result.evaluated_items)}")
    print(f"Findings: {run_dir / 'findings.md'}")


if __name__ == "__main__":
    main()
