# Research Assistant

An agentic research platform that runs while you sleep. Give it a research
brief and a set of sources — web pages, RSS feeds, JSON APIs — and it fetches
what's new, evaluates every item against your brief with Claude, and writes a
findings report you can read over coffee. Every run is recorded as a
self-contained, auditable folder.

```text
source discovery -> source connectors -> normalized ResearchItems
-> evaluation/model gateway -> findings/output -> run folder
```

Evaluation and synthesis run through Claude (Haiku by default) when
`ANTHROPIC_API_KEY` is set. Without a key, the platform falls back to local
extractive heuristics. That fallback is explicitly marked as degraded, so a
production delivery gate cannot mistake it for a healthy Claude-backed run.

## Quick Start: scheduled monitoring in your fork

The main way to use this repo is to fork it and let GitHub Actions run the
monitor for you every morning.

### 1. Fork this repo

Fork it on GitHub. If your research interests are sensitive, make the fork
**private** — the workflow commits findings back to the repository.

### 2. Add your Anthropic API key

Go to **Settings → Secrets and variables → Actions → New repository secret**

- Name: `ANTHROPIC_API_KEY`
- Value: your API key from [console.anthropic.com](https://console.anthropic.com)

### 3. Enable workflow permissions

Go to **Settings → Actions → General → Workflow permissions** and select
**"Read and write permissions"** so the workflow can commit findings.

### 4. Configure your brief and sources

Everything the scheduled monitor needs lives in one file,
`config/monitor-sources.yaml`:

```yaml
brief: >
  Watch the configured sources for developments in agentic AI systems,
  research automation, and AI-assisted knowledge work.

sources:
  - id: hacker-news-front-page
    type: rss
    name: Hacker News Front Page
    url: https://hnrss.org/frontpage
    access:
      method: public
```

The brief is the standing description of what you care about; every fetched
item is scored against it. Add the feeds, pages, and APIs you want watched
(see `config/sources.example.yaml` for all source types).

### 5. Enable and run

GitHub disables workflows in forks by default — open the **Actions** tab once
and enable them. The monitor then runs daily at 04:30 UTC (GitHub may delay
scheduled runs) and can be triggered manually via **Run workflow**.

Each morning you'll find a new folder under `runs/` whose `findings.md`
contains a deterministic, privacy-bounded rendering of the exact evidence
retained for relevant items. The workflow prunes run folders older than 90
days so the repository doesn't grow without bound.

## CLI usage

Everything also runs locally. For the reproducible environment used by the
test suite, use Python 3.11 and install the fully pinned dependency set:

```bash
python -m pip install -r requirements.lock
```

`requirements.txt` lists only the direct, permissive dependency ranges and is
the input for future lock refreshes. `requirements.lock` records the exact
direct and transitive versions verified together on Python 3.11.

Three modes:

```bash
# What does this page say about my question?
python3 -m research_platform.runner analyze-url \
  --brief "What does this say about agentic research platforms?" \
  --url "https://example.com"

# Research a topic from scratch — discovers sources via web search.
python3 -m research_platform.runner research-topic \
  --brief "agentic research platforms for enterprise knowledge work"

# Check configured sources for new items (brief comes from the source file).
python3 -m research_platform.runner monitor-sources \
  --source-file config/monitor-sources.yaml
```

Pass `--url` multiple times for several URLs. `--brief` always overrides the
source file's standing brief.

## What a run produces

Every invocation writes `runs/<date>-<brief-slug>/` containing:

- `findings.md` — a human-readable report rebuilt from committed artifact rows.
- `brief.md` — the question the run answered.
- `sources.json` — where the platform looked.
- `items.json` — normalized metadata plus exact retained-evidence bundles.
- `evaluated_items.json` — evaluations with claims provable from `items.json`.
- `run.json` — a slim manifest (brief, counts, file list).

Artifacts use schema version 2. Every substantive claim carries an exact
source-text excerpt of at most 300 characters. `items.json` stores only a
deterministic bundle of retained excerpts; evidence ranges and hashes are
rewritten against that committed bundle, and the nested item in
`evaluated_items.json` is identical to its `items.json` row. Claims that cannot
fit the configured caps are omitted. If a substantive evaluated item loses all
committed proof, run health fails with `committed_evidence_unavailable`.
Provider-authored rationale, uncertainty, and tag prose is not committed.
`run.json` records source outcomes, sanitized provider execution, total-budget
usage, run health, and acknowledgment state.

Because this repository is public, committed artifacts store only exact
evidence excerpts within `storage.max_committed_item_text_chars`, never full
content or surrounding context. Failed fetches remain observable through the
source outcomes and run health in `run.json`.

## Source types

| Type | What it does |
|---|---|
| `rss` | RSS/Atom feeds via feedparser |
| `webpage` | Fetches a page and extracts readable article text |
| `api_json` | Configurable JSON APIs (licensed news, catalogues); field mapping and API keys via environment variables — see `config/sources.example.yaml` |
| `x_post` / `x_profile` | Normalizes X/Twitter URLs as research items (placeholder until an authenticated connector exists) |

## Configuration

`config/research.yaml` holds platform settings:

- `models.evaluation` — provider (`anthropic` or `local`) and model for
  per-item scoring.
- `models.synthesis` — optional separate settings for the findings synthesis;
  defaults to the evaluation settings.
- `min_relevance_score` — items below this score (1–5) stay out of findings.
- `storage.max_committed_item_text_chars` — excerpt cap for committed artifacts.
- `storage.max_committed_evidence_chars_per_item` — collective evidence cap.
- `execution.retries` — at most three attempts, only for transient timeout,
  connection, HTTP 408/429, and 5xx failures; source and model request
  timeouts are bounded by the remaining elapsed-time budget.
- `execution.budgets` — optional total source, item, provider-attempt, input,
  output, and elapsed-time limits. Exhaustion is observable and fails the run.
- `execution.acknowledgment_mode` — `after_run` for the public legacy workflow,
  or `external` when a downstream sender acknowledges only after delivery.

API-backed sources reference secrets by environment variable name in their
YAML config — never put keys in files.

### Health, fallback, and acknowledgment

Provider and source failures use stable codes; raw exception strings and raw
model responses are not committed. Public/demo configuration may keep local
fallback, but fallback is always `degraded` and monitor items are not marked
seen. A strict consumer should configure:

```yaml
models:
  evaluation:
    provider: anthropic
    on_missing_credentials: fail
    on_error: fail
  synthesis:
    provider: anthropic
    on_error: fail
execution:
  acknowledgment_mode: external
  require_total_limits: true
```

External processing is source-specific. Set
`access.allow_external_processing: true` only when sending that source's text
to the configured external model is permitted. `api_json` defaults to false;
public webpage and RSS sources default to true.

RSS evaluation is grounded only in exact RSS entry text. Linked articles are
not fetched. Provenance labels the basis as `rss_entry`, and valid empty feeds
are distinct from failed feeds.

In `external` mode, `run.json` contains eligible item IDs but leaves
`committed` false. After a healthy run is delivered, a downstream caller can
invoke `research_platform.runner.acknowledge_run` with the run directory and
`knowledge/platform_state.json`. State writes are atomic and corrupt state
fails closed instead of resetting silently. Before changing seen-state, the
acknowledgment gate reloads `items.json` and `evaluated_items.json`, validates
their manifest hashes and counts, rechecks every evidence reference, and
requires manifest eligibility to exactly match successful committed
evaluations. Failed or degraded runs expose no eligible IDs.

## Agent skill

`skills/research-platform/SKILL.md` teaches coding agents (Claude Code, Codex)
how to drive the platform: which mode to pick, how to invoke the runner, and
how to report findings back. "Research this topic", "watch these sources",
and "what does this page say" all map onto the three modes.

## Tests

```bash
python -m unittest discover -s tests -v
```

Tests also run in CI on every push via `.github/workflows/tests.yml`.

## License

MIT — see LICENSE file.
