"""CLI runner for the research platform."""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

from .connectors import ApiJsonConnector, RssConnector, WebpageConnector, XConnector
from .discovery import discover_sources, sources_from_urls
from .execution import (
    BudgetExhausted,
    BudgetTracker,
    ExecutionCallError,
    call_with_retries,
    stable_error_code,
)
from .model_gateway import ModelGateway
from .models import (
    EvaluatedItem,
    ResearchBrief,
    ResearchItem,
    RunHealth,
    RunResult,
    Source,
    SourceFetchOutcome,
    stable_id,
    utc_now,
)
from .sanitization import sanitize_artifact_data, sanitize_text_urls, sanitize_url
from .state import SeenStore, StateCorruptionError


CONNECTORS = {
    "api_json": ApiJsonConnector(),
    "webpage": WebpageConnector(),
    "rss": RssConnector(),
    "x_post": XConnector(),
    "x_profile": XConnector(),
}


class DiscoveryError(RuntimeError):
    """Raised when source discovery cannot produce a usable research run."""


@dataclass
class FetchBatch:
    items: list[ResearchItem]
    outcomes: list[SourceFetchOutcome]


def _load_yaml(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists():
        return {}
    with path.open() as handle:
        return yaml.safe_load(handle) or {}


def load_config(path: Path | None) -> dict[str, Any]:
    return _load_yaml(path)


def load_source_brief(path: Path | None) -> str | None:
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


def _failure_item(source: Source, code: str) -> ResearchItem:
    return ResearchItem(
        id=f"error-{source.id}",
        source_id=source.id,
        source_type=source.type,
        title=f"Failed to fetch {source.name}",
        url=source.url,
        text=f"Source fetch failed ({code}).",
        metadata={"error_code": code},
        access_rights={"store_full_text": False, "allow_external_processing": False},
        provenance={"connector": source.type, "retrieval": "failed", "error_code": code},
    )


def fetch_items_with_outcomes(
    sources: list[Source],
    max_items_per_source: int = 20,
    *,
    retry_config: dict[str, Any] | None = None,
    budget: BudgetTracker | None = None,
) -> FetchBatch:
    items: list[ResearchItem] = []
    outcomes: list[SourceFetchOutcome] = []
    retry_config = retry_config or {}
    for source in sources:
        connector = CONNECTORS.get(source.type)
        if not connector:
            code = "config_error"
            print(
                f"Warning: no connector for source type '{source.type}' ({source.id}); skipping.",
                file=sys.stderr,
            )
            outcomes.append(SourceFetchOutcome(source.id, source.type, "failed", code, 0, attempts=0))
            items.append(_failure_item(source, code))
            continue
        if not source.url:
            code = "config_error"
            outcomes.append(
                SourceFetchOutcome(source.id, source.type, "failed", code, 0, attempts=0)
            )
            items.append(_failure_item(source, code))
            continue
        if source.type == "rss" and hasattr(connector, "fetch_with_outcome"):
            configured_timeout = float(retry_config.get("source_timeout_seconds", 20))
            fetched, outcome = connector.fetch_with_outcome(
                source,
                limit_items=max_items_per_source,
                retry_config=retry_config,
                timeout_provider=(
                    lambda: budget.bounded_timeout(configured_timeout) if budget else configured_timeout
                ),
            )
            items.extend(fetched)
            outcomes.append(outcome)
            if outcome.status == "failed":
                items.append(_failure_item(source, outcome.outcome_code))
            continue

        def operation() -> list[ResearchItem]:
            configured_timeout = float(retry_config.get("source_timeout_seconds", 30))
            timeout = budget.bounded_timeout(configured_timeout) if budget else configured_timeout
            if source.type == "api_json":
                return connector.fetch(
                    source, limit_items=max_items_per_source, timeout=timeout
                )
            if source.type == "webpage":
                return connector.fetch(source, timeout=timeout)
            return connector.fetch(source)

        retry_kwargs: dict[str, Any] = {
            "max_attempts": retry_config.get("max_attempts", 3),
            "initial_delay_seconds": retry_config.get("initial_delay_seconds", 0.5),
            "max_delay_seconds": retry_config.get("max_delay_seconds", 4.0),
        }
        if budget:
            retry_kwargs["before_attempt"] = budget.check_elapsed
        try:
            fetched, attempts = call_with_retries(operation, **retry_kwargs)
            items.extend(fetched)
            status = "succeeded" if fetched else "empty"
            code = "ok" if fetched else "empty_source"
            outcomes.append(
                SourceFetchOutcome(
                    source.id, source.type, status, code, len(fetched), attempts=attempts
                )
            )
        except ExecutionCallError as exc:
            code = stable_error_code(exc.cause)
            outcomes.append(
                SourceFetchOutcome(
                    source.id, source.type, "failed", code, 0, attempts=exc.attempts
                )
            )
            items.append(_failure_item(source, code))
    return FetchBatch(items, outcomes)


def fetch_items(sources: list[Source], max_items_per_source: int = 20) -> list[ResearchItem]:
    """Legacy wrapper returning normalized items only."""

    return fetch_items_with_outcomes(sources, max_items_per_source).items


def run(
    brief: ResearchBrief,
    urls: list[str],
    config: dict[str, Any],
    repo_root: Path,
    max_sources: int = 8,
    max_items_per_source: int = 20,
    configured_sources: list[Source] | None = None,
) -> tuple[RunResult, Path]:
    execution_config = config.get("execution", {})
    timezone_name = execution_config.get("timezone", "Europe/Vienna")
    runs_root = repo_root / "runs"
    run_id = make_run_id(brief.question, runs_root=runs_root, timezone_name=timezone_name)
    run_dir = runs_root / run_id
    state_path = repo_root / "knowledge" / "platform_state.json"
    budget = BudgetTracker(execution_config.get("budgets", {}))

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

    blocking_codes: list[str] = []
    degraded_codes: list[str] = []
    required_limits_missing = execution_config.get("require_total_limits", False) and any(
        limit is None for limit in budget.limits.values()
    )
    if required_limits_missing:
        batch = FetchBatch(
            [],
            [
                SourceFetchOutcome(
                    source.id, source.type, "failed", "config_error", 0, attempts=0
                )
                for source in sources
            ],
        )
        blocking_codes.append("config_error")
    else:
        try:
            budget.consume("max_sources_total", len(sources))
            batch = fetch_items_with_outcomes(
                sources,
                max_items_per_source=max_items_per_source,
                retry_config=execution_config.get("retries", {}),
                budget=budget,
            )
            budget.consume("max_items_total", len(batch.items))
        except BudgetExhausted:
            batch = FetchBatch(
                [],
                [
                    SourceFetchOutcome(
                        source.id, source.type, "failed", "budget_exhausted", 0, attempts=0
                    )
                    for source in sources
                ],
            )
            blocking_codes.append("budget_exhausted")

    seen_store: SeenStore | None = None
    try:
        seen_store = SeenStore(state_path)
    except StateCorruptionError:
        blocking_codes.append("state_corrupt")

    if brief.mode == "monitor-sources" and seen_store:
        items_to_evaluate = [item for item in batch.items if not seen_store.has_seen(item.id)]
    else:
        items_to_evaluate = batch.items
    if budget.status == "exhausted":
        items_to_evaluate = []

    gateway = ModelGateway(
        config.get("models", {}),
        execution_config=execution_config,
        budget=budget,
    )
    all_evaluated = [gateway.evaluate(item, brief) for item in items_to_evaluate]
    min_score = int(config.get("min_relevance_score", 1))
    reportable = [
        evaluated
        for evaluated in all_evaluated
        if evaluated.relevance_score >= min_score or _fetch_failed(evaluated.item)
    ]
    synthesis_result = gateway.synthesize_result(reportable, brief)

    try:
        budget.check_elapsed()
    except BudgetExhausted:
        blocking_codes.append("budget_exhausted")

    for outcome in batch.outcomes:
        if outcome.status == "failed":
            blocking_codes.append(outcome.outcome_code)
    for evaluated in all_evaluated:
        execution = evaluated.execution
        if not execution:
            blocking_codes.append("missing_execution_metadata")
        elif execution.status == "failed":
            blocking_codes.append(execution.outcome_code)
        elif execution.status == "degraded":
            degraded_codes.append(execution.outcome_code)
        elif execution.status == "skipped" and execution.outcome_code != "ok":
            blocking_codes.append(execution.outcome_code)
    if synthesis_result.execution.status == "failed":
        blocking_codes.append(synthesis_result.execution.outcome_code)
    elif synthesis_result.execution.status == "degraded":
        degraded_codes.append(synthesis_result.execution.outcome_code)
    if budget.status == "exhausted":
        blocking_codes.append("budget_exhausted")

    acknowledgment_mode = execution_config.get("acknowledgment_mode", "after_run")
    if acknowledgment_mode not in {"after_run", "external"}:
        blocking_codes.append("config_error")
    blocking_codes = list(dict.fromkeys(blocking_codes))
    degraded_codes = list(dict.fromkeys(degraded_codes))
    health_status = "failed" if blocking_codes else "degraded" if degraded_codes else "healthy"
    health = RunHealth(
        run_id=run_id,
        status=health_status,
        blocking_codes=blocking_codes or degraded_codes,
    )
    eligible_item_ids = []
    if health_status == "healthy":
        eligible_item_ids = [
            evaluated.item.id
            for evaluated in all_evaluated
            if evaluated.execution
            and evaluated.execution.status == "succeeded"
            and evaluated.execution.outcome_code == "ok"
            and not _fetch_failed(evaluated.item)
        ]

    acknowledgment = {
        "mode": acknowledgment_mode,
        "eligible_item_ids": eligible_item_ids,
        "committed": False,
        "committed_at": None,
    }
    result = RunResult(
        run_id=run_id,
        brief=brief,
        sources=sources,
        items=batch.items,
        evaluated_items=all_evaluated,
        findings_markdown=synthesis_result.markdown,
        source_outcomes=batch.outcomes,
        synthesis_execution=synthesis_result.execution,
        budget=budget.snapshot(),
        health=health,
        acknowledgment=acknowledgment,
    )
    storage_config = config.get("storage", {})
    max_text_chars = int(storage_config.get("max_committed_item_text_chars", 700))
    max_evidence_chars = int(storage_config.get("max_committed_evidence_chars_per_item", 700))
    write_run(
        run_dir,
        result,
        max_item_text_chars=max_text_chars,
        max_evidence_chars=max_evidence_chars,
        findings_item_ids={evaluated.item.id for evaluated in reportable},
    )

    if (
        brief.mode == "monitor-sources"
        and acknowledgment_mode == "after_run"
        and result.health
        and result.health.status == "healthy"
    ):
        if seen_store is None:
            result.health = RunHealth(run_id, "failed", ["state_corrupt"])
        else:
            try:
                seen_store.acknowledge(eligible_item_ids, run_id=run_id)
                seen_store.save()
                result.acknowledgment["committed"] = True
                result.acknowledgment["committed_at"] = utc_now()
            except (OSError, StateCorruptionError):
                result.health = RunHealth(run_id, "failed", ["state_write_failed"])
        _write_manifest(run_dir, result)
    elif brief.mode != "monitor-sources":
        result.acknowledgment["committed"] = True
        result.acknowledgment["committed_at"] = utc_now()
        _write_manifest(run_dir, result)
    return result, run_dir


def acknowledge_run(run_dir: Path, state_path: Path) -> None:
    """Commit an externally delivered healthy run to seen state."""

    manifest_path = run_dir / "run.json"
    manifest = _load_json_object_strict(manifest_path, "run manifest")
    if manifest.get("schema_version") != 2:
        raise ValueError("run manifest must use schema version 2")
    health = manifest.get("health") or {}
    acknowledgment = manifest.get("acknowledgment") or {}
    manifest_run_id = manifest.get("run_id")
    health_run_id = health.get("run_id")
    if (
        not isinstance(manifest_run_id, str)
        or not manifest_run_id.strip()
        or not isinstance(health_run_id, str)
        or not health_run_id.strip()
        or health_run_id != manifest_run_id
        or health.get("status") != "healthy"
    ):
        raise ValueError("only the same healthy run can be acknowledged")
    if acknowledgment.get("mode") != "external":
        raise ValueError("run does not use external acknowledgment")
    item_ids = acknowledgment.get("eligible_item_ids")
    if not isinstance(item_ids, list) or not all(isinstance(item_id, str) for item_id in item_ids):
        raise ValueError("eligible_item_ids must be a list of strings")

    item_path = run_dir / "items.json"
    evaluated_path = run_dir / "evaluated_items.json"
    item_rows = _load_json_array_strict(item_path, "items.json")
    evaluated_rows = _load_json_array_strict(evaluated_path, "evaluated_items.json")
    validate_evaluated_items(item_rows, evaluated_rows)
    _verify_artifact_manifest_binding(
        manifest,
        item_path=item_path,
        evaluated_path=evaluated_path,
        item_rows=item_rows,
        evaluated_rows=evaluated_rows,
    )
    expected_item_ids = _eligible_item_ids_from_committed(evaluated_rows)
    if item_ids != expected_item_ids:
        raise ValueError("manifest eligibility does not match committed evaluations")

    store = SeenStore(state_path)
    if acknowledgment.get("committed"):
        if not all(store.has_seen(item_id) for item_id in item_ids):
            raise ValueError("committed acknowledgment is not reflected in seen state")
        return
    store.acknowledge(item_ids, run_id=manifest_run_id)
    store.save()
    acknowledgment["committed"] = True
    acknowledgment["committed_at"] = utc_now()
    manifest["acknowledgment"] = acknowledgment
    _atomic_write_json(manifest_path, manifest)


def _fetch_failed(item: ResearchItem) -> bool:
    return item.provenance.get("retrieval") == "failed"


def write_run(
    run_dir: Path,
    result: RunResult,
    max_item_text_chars: int = 700,
    max_evidence_chars: int = 700,
    findings_item_ids: set[str] | None = None,
) -> None:
    """Write privacy-bounded, schema-versioned run artifacts."""

    run_dir.mkdir(parents=True, exist_ok=True)
    safe_question = sanitize_text_urls(result.brief.question)
    (run_dir / "brief.md").write_text(
        f"# Brief\n\n{safe_question}\n", encoding="utf-8"
    )
    (run_dir / "sources.json").write_text(
        json.dumps([_artifact_source_dict(source) for source in result.sources], indent=2),
        encoding="utf-8",
    )
    item_dicts, evaluated_dicts = _build_committed_artifacts(
        result.items,
        result.evaluated_items,
        max_item_text_chars=max_item_text_chars,
        max_evidence_chars=max_evidence_chars,
    )
    validate_evaluated_items(item_dicts, evaluated_dicts)
    intended_substantive_ids = {
        evaluated.item.id
        for evaluated in result.evaluated_items
        if evaluated.grounded_claims
    }
    retained_item_ids = {row["item"]["id"] for row in evaluated_dicts}
    if intended_substantive_ids - retained_item_ids:
        _mark_committed_evidence_unavailable(result)
    (run_dir / "items.json").write_text(
        json.dumps(item_dicts, indent=2), encoding="utf-8"
    )
    (run_dir / "evaluated_items.json").write_text(
        json.dumps(evaluated_dicts, indent=2), encoding="utf-8"
    )
    findings = _artifact_findings_markdown(
        safe_question,
        evaluated_dicts,
        findings_item_ids=findings_item_ids,
        health=result.health,
    )
    (run_dir / "findings.md").write_text(findings, encoding="utf-8")
    result.findings_markdown = findings
    if result.health and result.health.status == "healthy":
        result.acknowledgment["eligible_item_ids"] = _eligible_item_ids_from_committed(
            evaluated_dicts
        )
    else:
        result.acknowledgment["eligible_item_ids"] = []
    _write_manifest(run_dir, result)


def _mark_committed_evidence_unavailable(result: RunResult) -> None:
    code = "committed_evidence_unavailable"
    if result.health is None:
        result.health = RunHealth(result.run_id, "failed", [code])
        return
    result.health.status = "failed"
    if code not in result.health.blocking_codes:
        result.health.blocking_codes.append(code)


def _write_manifest(run_dir: Path, result: RunResult) -> None:
    artifact_items = _load_json_array_strict(run_dir / "items.json", "items.json")
    artifact_evaluated = _load_json_array_strict(
        run_dir / "evaluated_items.json", "evaluated_items.json"
    )
    validate_evaluated_items(artifact_items, artifact_evaluated)
    manifest = {
        "schema_version": 2,
        "run_id": result.run_id,
        "brief": sanitize_artifact_data(result.brief.to_dict()),
        "created_at": result.created_at,
        "counts": {
            "sources": len(result.sources),
            "items": len(artifact_items),
            "evaluated_items": len(artifact_evaluated),
            "grounded_claims": sum(
                len(row.get("grounded_claims", [])) for row in artifact_evaluated
            ),
        },
        "source_outcomes": [asdict(outcome) for outcome in result.source_outcomes],
        "synthesis_execution": asdict(result.synthesis_execution) if result.synthesis_execution else None,
        "budget": asdict(result.budget) if result.budget else None,
        "health": asdict(result.health) if result.health else None,
        "acknowledgment": result.acknowledgment,
        "artifact_sha256": {
            "items.json": _file_sha256(run_dir / "items.json"),
            "evaluated_items.json": _file_sha256(run_dir / "evaluated_items.json"),
        },
        "files": [
            "brief.md",
            "sources.json",
            "items.json",
            "evaluated_items.json",
            "findings.md",
        ],
    }
    _atomic_write_json(run_dir / "run.json", manifest)
def _load_json_object_strict(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"{label} is missing")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is unreadable") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _load_json_array_strict(path: Path, label: str) -> list[dict[str, Any]]:
    if not path.is_file():
        raise ValueError(f"{label} is missing")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is unreadable") from exc
    if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
        raise ValueError(f"{label} must be a list of objects")
    return value


def _file_sha256(path: Path) -> str:
    try:
        return sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise ValueError(f"required artifact is missing: {path.name}") from exc


def _verify_artifact_manifest_binding(
    manifest: dict[str, Any],
    *,
    item_path: Path,
    evaluated_path: Path,
    item_rows: list[dict[str, Any]],
    evaluated_rows: list[dict[str, Any]],
) -> None:
    hashes = manifest.get("artifact_sha256")
    if not isinstance(hashes, dict):
        raise ValueError("run manifest is missing artifact hashes")
    expected_hashes = {
        "items.json": _file_sha256(item_path),
        "evaluated_items.json": _file_sha256(evaluated_path),
    }
    if any(hashes.get(name) != digest for name, digest in expected_hashes.items()):
        raise ValueError("committed artifact hash does not match run manifest")

    counts = manifest.get("counts")
    expected_counts = {
        "items": len(item_rows),
        "evaluated_items": len(evaluated_rows),
        "grounded_claims": sum(
            len(row.get("grounded_claims", [])) for row in evaluated_rows
        ),
    }
    if not isinstance(counts, dict) or any(
        counts.get(name) != count for name, count in expected_counts.items()
    ):
        raise ValueError("committed artifact counts do not match run manifest")


def _eligible_item_ids_from_committed(
    evaluated_rows: list[dict[str, Any]],
) -> list[str]:
    eligible: list[str] = []
    for evaluated in evaluated_rows:
        execution = evaluated.get("execution")
        item = evaluated.get("item")
        if not isinstance(execution, dict) or not isinstance(item, dict):
            continue
        provenance = item.get("provenance")
        retrieval = provenance.get("retrieval") if isinstance(provenance, dict) else None
        item_id = item.get("id")
        if (
            execution.get("status") == "succeeded"
            and execution.get("outcome_code") == "ok"
            and retrieval != "failed"
            and isinstance(item_id, str)
            and item_id not in eligible
        ):
            eligible.append(item_id)
    return eligible


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _build_committed_artifacts(
    items: list[ResearchItem],
    evaluated_items: list[EvaluatedItem],
    *,
    max_item_text_chars: int,
    max_evidence_chars: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    evaluations_by_item: dict[str, list[EvaluatedItem]] = {}
    for evaluated in evaluated_items:
        evaluations_by_item.setdefault(evaluated.item.id, []).append(evaluated)

    item_dicts: list[dict[str, Any]] = []
    committed_by_id: dict[str, dict[str, Any]] = {}
    positions_by_id: dict[str, dict[str, tuple[int, int]]] = {}
    original_by_id: dict[str, ResearchItem] = {}
    for item in items:
        if item.id in original_by_id:
            continue
        original_by_id[item.id] = item
        bundle, positions = _committed_evidence_bundle(
            item,
            evaluations_by_item.get(item.id, []),
            max_item_text_chars=max_item_text_chars,
            max_evidence_chars=max_evidence_chars,
        )
        committed = _committed_item_dict(item, bundle)
        item_dicts.append(committed)
        committed_by_id[item.id] = committed
        positions_by_id[item.id] = positions

    evaluated_dicts: list[dict[str, Any]] = []
    for evaluated in evaluated_items:
        original = original_by_id.get(evaluated.item.id)
        committed = committed_by_id.get(evaluated.item.id)
        if original is None or committed is None:
            continue
        artifact = _artifact_evaluated_dict(
            evaluated,
            original,
            committed,
            positions_by_id[evaluated.item.id],
        )
        if artifact is not None:
            evaluated_dicts.append(artifact)
    return item_dicts, evaluated_dicts


def _committed_evidence_bundle(
    item: ResearchItem,
    evaluated_items: list[EvaluatedItem],
    *,
    max_item_text_chars: int,
    max_evidence_chars: int,
) -> tuple[str, dict[str, tuple[int, int]]]:
    item_limit = max(0, _artifact_text_limit(item, max_item_text_chars))
    evidence_limit = max(0, int(max_evidence_chars))
    if item_limit == 0 or evidence_limit == 0:
        return "", {}

    parts: list[str] = []
    positions: dict[str, tuple[int, int]] = {}
    committed_length = 0
    evidence_chars = 0
    for evaluated in evaluated_items:
        for claim in evaluated.grounded_claims:
            excerpt = _validated_original_excerpt(item, claim)
            if excerpt is None or excerpt in positions:
                continue
            separator = "" if not parts else "\n"
            if evidence_chars + len(excerpt) > evidence_limit:
                continue
            if committed_length + len(separator) + len(excerpt) > item_limit:
                continue
            start = committed_length + len(separator)
            end = start + len(excerpt)
            parts.extend([separator, excerpt] if separator else [excerpt])
            positions[excerpt] = (start, end)
            committed_length = end
            evidence_chars += len(excerpt)
    return "".join(parts), positions


def _validated_original_excerpt(item: ResearchItem, claim: Any) -> str | None:
    evidence_refs = getattr(claim, "evidence", None)
    if not isinstance(evidence_refs, list) or not evidence_refs:
        return None
    evidence = evidence_refs[0]
    excerpt = getattr(evidence, "excerpt", None)
    start = getattr(evidence, "start", None)
    end = getattr(evidence, "end", None)
    if not isinstance(excerpt, str) or not excerpt or len(excerpt) > 300:
        return None
    if sanitize_text_urls(excerpt) != excerpt:
        return None
    if (
        isinstance(start, bool)
        or isinstance(end, bool)
        or not isinstance(start, int)
        or not isinstance(end, int)
        or start < 0
        or end < start
        or item.text[start:end] != excerpt
    ):
        return None
    if getattr(evidence, "item_id", None) != item.id:
        return None
    if getattr(evidence, "text_sha256", None) != sha256(item.text.encode("utf-8")).hexdigest():
        return None
    if getattr(evidence, "excerpt_sha256", None) != sha256(excerpt.encode("utf-8")).hexdigest():
        return None
    return excerpt


def _artifact_evaluated_dict(
    evaluated: EvaluatedItem,
    original_item: ResearchItem,
    committed_item: dict[str, Any],
    positions: dict[str, tuple[int, int]],
) -> dict[str, Any] | None:
    data = evaluated.to_dict()
    data["item"] = copy.deepcopy(committed_item)
    retained_claims: list[dict[str, Any]] = []
    seen_excerpts: set[str] = set()
    committed_text = str(committed_item.get("text", ""))
    committed_hash = sha256(committed_text.encode("utf-8")).hexdigest()
    for claim in evaluated.grounded_claims:
        excerpt = _validated_original_excerpt(original_item, claim)
        if excerpt is None or excerpt in seen_excerpts or excerpt not in positions:
            continue
        seen_excerpts.add(excerpt)
        start, end = positions[excerpt]
        retained_claims.append(
            {
                "id": stable_id(original_item.id, excerpt),
                "text": excerpt,
                "evidence": [
                    {
                        "item_id": original_item.id,
                        "excerpt": excerpt,
                        "start": start,
                        "end": end,
                        "text_sha256": committed_hash,
                        "excerpt_sha256": sha256(excerpt.encode("utf-8")).hexdigest(),
                    }
                ],
            }
        )
    if not retained_claims:
        return None
    data["grounded_claims"] = retained_claims
    data["key_points"] = [claim["text"][:300] for claim in retained_claims[:4]]
    data["summary"] = " ".join(claim["text"] for claim in retained_claims[:2])[:700]
    # These fields can contain unconstrained provider prose in legacy or
    # caller-constructed objects. Artifact diagnostics are rebuilt solely from
    # controlled execution metadata.
    data["tags"] = []
    data["uncertainties"] = []
    data["rationale"] = "Evaluation retained with exact committed evidence."
    return data


def _committed_item_dict(item: ResearchItem, committed_text: str) -> dict[str, Any]:
    data = item.to_dict()
    data.pop("text", None)
    raw_metadata = data.get("metadata", {})
    data = sanitize_artifact_data(data)
    data["url"] = sanitize_url(data.get("url"))
    data["text"] = committed_text
    data["metadata"] = _artifact_metadata(raw_metadata)
    data["access_rights"] = sanitize_artifact_data(data.get("access_rights", {}))
    data["provenance"] = sanitize_artifact_data(data.get("provenance", {}))
    return data


def _artifact_source_dict(source: Source) -> dict[str, Any]:
    data = sanitize_artifact_data(source.to_dict())
    data["url"] = sanitize_url(data.get("url"))
    return data


def _artifact_findings_markdown(
    safe_question: str,
    evaluated_rows: list[dict[str, Any]],
    *,
    findings_item_ids: set[str] | None = None,
    health: RunHealth | None = None,
) -> str:
    """Render findings only from the exact rows that were safe to persist."""

    included = [
        row
        for row in evaluated_rows
        if findings_item_ids is None or (row.get("item") or {}).get("id") in findings_item_ids
    ]
    ranked = sorted(
        included,
        key=lambda row: int(row.get("relevance_score", 0)),
        reverse=True,
    )
    lines = [
        f"# Findings: {safe_question}",
        "",
    ]
    if health and health.status == "failed":
        codes = ", ".join(health.blocking_codes) or "unknown"
        lines.extend([f"> Run status: failed ({codes}).", ""])
    lines.extend(
        [
            "## Summary",
            "",
            f"Reviewed {len(ranked)} item(s). Highest-scoring material is listed first.",
            "",
            "## Relevant Items",
            "",
        ]
    )
    for evaluated in ranked:
        item = evaluated.get("item") or {}
        title = sanitize_text_urls(str(item.get("title") or "Untitled item"))
        lines.append(f"### {title}")
        url = sanitize_url(item.get("url"))
        if url:
            lines.append(f"- URL: {url}")
        lines.append(f"- Source type: {item.get('source_type', 'unknown')}")
        lines.append(f"- Relevance: {int(evaluated.get('relevance_score', 0))}/5")
        summary = str(evaluated.get("summary") or "")
        if summary:
            lines.append(f"- Summary: {sanitize_text_urls(summary)}")
        claims = evaluated.get("grounded_claims") or []
        if claims:
            lines.append("- Grounded claims:")
            for claim in claims[:4]:
                evidence = (claim.get("evidence") or [{}])[0]
                excerpt = sanitize_text_urls(str(evidence.get("excerpt") or ""))
                if not excerpt:
                    continue
                lines.append(f"  - {excerpt} [claim:{claim.get('id', 'unknown')}]")
                lines.append(f'    - Evidence: "{excerpt}"')
        execution = evaluated.get("execution") or {}
        if execution.get("status") != "succeeded":
            lines.append(
                f"- Evaluation status: {execution.get('outcome_code', 'unknown')}"
            )
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _artifact_text_limit(item: ResearchItem, default_max_chars: int) -> int:
    limits = [max(0, int(default_max_chars))]
    if not item.access_rights.get("store_full_text", True):
        try:
            item_max_chars = int(item.access_rights.get("max_store_chars", 0))
        except (TypeError, ValueError):
            item_max_chars = 0
        limits.append(max(0, item_max_chars))
    return max(0, min(limits) if limits else default_max_chars)


def validate_evaluated_items(
    item_rows: list[dict[str, Any]], evaluated_rows: list[dict[str, Any]]
) -> None:
    """Verify every evaluation solely against its committed item artifact."""

    items_by_id: dict[str, dict[str, Any]] = {}
    for item in item_rows:
        item_id = item.get("id")
        if not isinstance(item_id, str) or not item_id or item_id in items_by_id:
            raise ValueError("committed item IDs must be unique non-empty strings")
        if not isinstance(item.get("text"), str):
            raise ValueError("committed item text must be a string")
        items_by_id[item_id] = item

    for evaluated in evaluated_rows:
        nested_item = evaluated.get("item")
        if not isinstance(nested_item, dict):
            raise ValueError("evaluated item must contain a committed item object")
        item_id = nested_item.get("id")
        committed_item = items_by_id.get(item_id)
        if committed_item is None or nested_item != committed_item:
            raise ValueError("evaluated item does not match items.json")
        claims = evaluated.get("grounded_claims")
        if not isinstance(claims, list) or not claims:
            raise ValueError("committed evaluations require grounded claims")
        committed_text = committed_item["text"]
        committed_hash = sha256(committed_text.encode("utf-8")).hexdigest()
        for claim in claims:
            evidence_refs = claim.get("evidence") if isinstance(claim, dict) else None
            if not isinstance(evidence_refs, list) or len(evidence_refs) != 1:
                raise ValueError("each committed claim requires one evidence reference")
            evidence = evidence_refs[0]
            excerpt = evidence.get("excerpt") if isinstance(evidence, dict) else None
            start = evidence.get("start") if isinstance(evidence, dict) else None
            end = evidence.get("end") if isinstance(evidence, dict) else None
            if (
                not isinstance(excerpt, str)
                or not excerpt
                or isinstance(start, bool)
                or isinstance(end, bool)
                or not isinstance(start, int)
                or not isinstance(end, int)
                or start < 0
                or end < start
                or committed_text[start:end] != excerpt
                or claim.get("text") != excerpt
                or evidence.get("item_id") != item_id
                or evidence.get("text_sha256") != committed_hash
                or evidence.get("excerpt_sha256")
                != sha256(excerpt.encode("utf-8")).hexdigest()
            ):
                raise ValueError("committed evidence validation failed")


def _artifact_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    source = metadata if isinstance(metadata, dict) else {}
    data = sanitize_artifact_data(source)
    if "provider_record" in source:
        data["provider_record_redacted"] = True
    return data


def make_run_id(
    question: str,
    runs_root: Path | None = None,
    timezone_name: str = "Europe/Vienna",
) -> str:
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("unknown execution timezone") from exc
    now = datetime.now(timezone)
    today = now.strftime("%Y-%m-%d")
    safe_question = sanitize_text_urls(question)
    slug = re.sub(r"[^a-z0-9]+", "-", safe_question.lower())[:48].strip("-") or "research-run"
    run_id = f"{today}-{slug}"
    if runs_root is not None and (runs_root / run_id).exists():
        run_id = f"{run_id}-{now.strftime('%H%M%S')}"
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
    print(f"Health: {result.health.status if result.health else 'unknown'}")
    print(f"Sources: {len(result.sources)}")
    print(f"Items: {len(result.items)}")
    print(f"Evaluated: {len(result.evaluated_items)}")
    print(f"Findings: {run_dir / 'findings.md'}")


if __name__ == "__main__":
    main()
