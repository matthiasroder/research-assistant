"""CLI runner for the first research-platform slice."""

from __future__ import annotations

import argparse
import json
import re
import sys
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


class DiscoveryError(RuntimeError):
    """Raised when source discovery cannot produce a usable research run."""


def _load_yaml(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists():
        return {}
    with path.open() as handle:
        return yaml.safe_load(handle) or {}


def load_config(path: Path | None) -> dict[str, Any]:
    return _load_yaml(path)


def load_source_brief(path: Path | None) -> str | None:
    """Return the standing research brief defined in a source file, if any."""
    brief = _load_yaml(path).get("brief")
    if brief is None:
        return None
    text = str(brief).strip()
    return text or None


def load_source_file(path: Path | None) -> list[Source]:
    data = _load_yaml(path)
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
            print(
                f"Warning: no connector for source type '{source.type}' ({source.id}); skipping.",
                file=sys.stderr,
            )
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
    runs_root = repo_root / "runs"
    run_id = make_run_id(brief.question, runs_root=runs_root)
    run_dir = runs_root / run_id
    state_path = repo_root / "knowledge" / "platform_state.json"

    if configured_sources:
        sources = configured_sources + sources_from_urls(urls)
    elif brief.mode == "research-topic":
        sources = discover_sources(brief.question, seed_urls=urls, max_sources=max_sources)
    else:
        sources = sources_from_urls(urls)
    if brief.mode == "research-topic" and not sources:
        raise DiscoveryError(
            "No sources were discovered for research-topic. Provide one or more --url seed sources "
            "or configure a stable search provider before running this mode."
        )

    items = fetch_items(sources, max_items_per_source=max_items_per_source)
    seen_store = SeenStore(state_path)
    if brief.mode == "monitor-sources":
        items_to_evaluate = [item for item in items if not seen_store.has_seen(item.id)]
    else:
        items_to_evaluate = items

    gateway = ModelGateway(config.get("models", {}))
    evaluated = [gateway.evaluate(item, brief) for item in items_to_evaluate]
    min_score = config.get("min_relevance_score", 1)
    # Failed fetches stay in the findings regardless of score so broken
    # sources remain visible.
    evaluated = [
        item
        for item in evaluated
        if item.relevance_score >= min_score or _fetch_failed(item.item)
    ]
    findings = gateway.synthesize(evaluated, brief)

    result = RunResult(
        run_id=run_id,
        brief=brief,
        sources=sources,
        items=items,
        evaluated_items=evaluated,
        findings_markdown=findings,
    )
    max_text_chars = int(config.get("storage", {}).get("max_committed_item_text_chars", 700))
    write_run(run_dir, result, max_item_text_chars=max_text_chars)
    if brief.mode == "monitor-sources":
        # Failed fetches are never marked seen, so a source that keeps
        # failing keeps surfacing in every run.
        seen_store.mark_seen([item.id for item in items if not _fetch_failed(item)])
        seen_store.save()
    return result, run_dir


def _fetch_failed(item: ResearchItem) -> bool:
    return item.provenance.get("retrieval") == "failed"


def write_run(run_dir: Path, result: RunResult, max_item_text_chars: int = 700) -> None:
    """Write run artifacts.

    Item text is truncated to a short excerpt in the committed artifacts: the
    repository is public, so full third-party text must not be republished.
    Evaluation always runs on the full in-memory text before this point.
    """
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "brief.md").write_text(f"# Brief\n\n{result.brief.question}\n", encoding="utf-8")
    (run_dir / "sources.json").write_text(
        json.dumps([source.to_dict() for source in result.sources], indent=2),
        encoding="utf-8",
    )
    (run_dir / "items.json").write_text(
        json.dumps(
            [_excerpted_item_dict(item, max_item_text_chars) for item in result.items],
            indent=2,
        ),
        encoding="utf-8",
    )
    evaluated_dicts = []
    for evaluated in result.evaluated_items:
        data = evaluated.to_dict()
        data["item"] = _excerpted_item_dict(evaluated.item, max_item_text_chars)
        evaluated_dicts.append(data)
    (run_dir / "evaluated_items.json").write_text(
        json.dumps(evaluated_dicts, indent=2),
        encoding="utf-8",
    )
    (run_dir / "findings.md").write_text(result.findings_markdown, encoding="utf-8")
    manifest = {
        "run_id": result.run_id,
        "brief": result.brief.to_dict(),
        "created_at": result.created_at,
        "counts": {
            "sources": len(result.sources),
            "items": len(result.items),
            "evaluated_items": len(result.evaluated_items),
        },
        "files": [
            "brief.md",
            "sources.json",
            "items.json",
            "evaluated_items.json",
            "findings.md",
        ],
    }
    (run_dir / "run.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def _excerpted_item_dict(item: ResearchItem, max_chars: int) -> dict[str, Any]:
    data = item.to_dict()
    artifact_max_chars = _artifact_text_limit(item, max_chars)
    if artifact_max_chars > 0 and len(data.get("text", "")) > artifact_max_chars:
        data["text"] = data["text"][:artifact_max_chars] + " …[truncated for committed artifact]"
    data["metadata"] = _artifact_metadata(data.get("metadata", {}))
    return data


def _artifact_text_limit(item: ResearchItem, default_max_chars: int) -> int:
    limits = [default_max_chars] if default_max_chars > 0 else []
    if not item.access_rights.get("store_full_text", True):
        try:
            item_max_chars = int(item.access_rights.get("max_store_chars", 0))
        except (TypeError, ValueError):
            item_max_chars = 0
        if item_max_chars > 0:
            limits.append(item_max_chars)
    return min(limits) if limits else default_max_chars


def _artifact_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    data = dict(metadata) if isinstance(metadata, dict) else {}
    if "provider_record" in data:
        data.pop("provider_record")
        data["provider_record_redacted"] = True
    return data


def make_run_id(question: str, runs_root: Path | None = None) -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    slug = re.sub(r"[^a-z0-9]+", "-", question.lower())[:48].strip("-") or "research-run"
    run_id = f"{today}-{slug}"
    if runs_root is not None and (runs_root / run_id).exists():
        run_id = f"{run_id}-{datetime.now().strftime('%H%M%S')}"
    return run_id


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a small agentic research workflow.")
    parser.add_argument("mode", choices=["analyze-url", "research-topic", "monitor-sources"])
    parser.add_argument(
        "--brief",
        help="Research question or monitoring intent. Optional when the source file defines a top-level 'brief:'.",
    )
    parser.add_argument("--url", action="append", default=[], help="Source URL. Can be passed multiple times.")
    parser.add_argument("--config", default="config/research.yaml", help="Platform config path.")
    parser.add_argument("--source-file", help="YAML file with configured sources and an optional standing brief.")
    parser.add_argument("--max-sources", type=int, default=8)
    parser.add_argument("--max-items-per-source", type=int, default=20)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    repo_root = Path.cwd()
    config = load_config(repo_root / args.config)
    source_path = repo_root / args.source_file if args.source_file else None
    configured_sources = load_source_file(source_path)
    # An explicit --brief wins; otherwise fall back to the standing brief in
    # the source file so scheduled monitoring is configured in one place.
    brief_text = args.brief or load_source_brief(source_path)
    if not brief_text:
        parser.error("Provide --brief or define a top-level 'brief:' in the source file.")
    brief = ResearchBrief(question=brief_text, mode=args.mode)
    try:
        result, run_dir = run(
            brief=brief,
            urls=args.url,
            config=config,
            repo_root=repo_root,
            max_sources=args.max_sources,
            max_items_per_source=args.max_items_per_source,
            configured_sources=configured_sources,
        )
    except DiscoveryError as exc:
        parser.error(str(exc))
    print(f"Run: {result.run_id}")
    print(f"Sources: {len(result.sources)}")
    print(f"Items: {len(result.items)}")
    print(f"Evaluated: {len(result.evaluated_items)}")
    print(f"Findings: {run_dir / 'findings.md'}")


if __name__ == "__main__":
    main()
