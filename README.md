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
extractive heuristics — less clever, but everything still works, so you can
try it before configuring credentials.

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
contains a Claude-written synthesis of what's new, followed by every relevant
item with its score, summary, and key points. The workflow prunes run folders
older than 90 days so the repository doesn't grow without bound.

## CLI usage

Everything also runs locally. You need Python 3.10+ and:

```bash
pip install -r requirements.txt
```

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

- `findings.md` — the human-readable report: synthesis first, then ranked items.
- `brief.md` — the question the run answered.
- `sources.json` — where the platform looked.
- `items.json` — every normalized item that was fetched.
- `evaluated_items.json` — scores, summaries, key points, tags, rationale.
- `run.json` — a slim manifest (brief, counts, file list).

Because this repository is public, committed artifacts store only short
excerpts of fetched third-party text (configurable via
`storage.max_committed_item_text_chars`), never full content. Failed fetches
are reported in the findings rather than silently dropped, so a broken source
stays visible until you fix or remove it.

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

API-backed sources reference secrets by environment variable name in their
YAML config — never put keys in files.

## Agent skill

`skills/research-platform/SKILL.md` teaches coding agents (Claude Code, Codex)
how to drive the platform: which mode to pick, how to invoke the runner, and
how to report findings back. "Research this topic", "watch these sources",
and "what does this page say" all map onto the three modes.

## Tests

```bash
python -m unittest discover -s tests
```

Tests also run in CI on every push via `.github/workflows/tests.yml`.

## License

MIT — see LICENSE file.
