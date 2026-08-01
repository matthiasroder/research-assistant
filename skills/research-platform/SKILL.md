---
name: research-platform
description: Run the local agentic research platform for topic research, URL analysis, and source monitoring.
---

# Research Platform Skill

Use this skill when the user asks to research a topic, analyze one or more URLs,
monitor sources, discover useful source URLs, or run the local agentic research
platform. Also use it when the user asks to schedule, automate, or deploy
periodic research monitoring through GitHub Actions.

## Workflow

1. Determine the mode:
   - `analyze-url` for one or more explicit URLs.
   - `research-topic` for a topic or question where sources should be discovered.
   - `monitor-sources` for repeated checks against known URLs.
2. Run the platform from the repository root:

   ```bash
   python3 -m research_platform.runner <mode> --brief "<brief>" --url "<url>"
   ```

   Pass `--url` multiple times when the user provides several URLs. For a topic
   without URLs, omit `--url`. For configured public, social, paywalled, or
   catalogue/API sources, pass `--source-file <path-to-yaml>`.
3. Read `runs/<run-id>/findings.md` and summarize the result to the user.
4. Mention the run folder path so the user can inspect `brief.md`,
   `sources.json`, `items.json`, `evaluated_items.json`, `findings.md`, and
   `run.json` (a slim manifest with the brief, counts, and file list).
5. Check `run.json.health.status` before presenting or delivering the result.
   `degraded` means a configured fallback was used; `failed` means a source,
   model, grounding, state, or budget gate failed.

## Scheduling With GitHub Actions

When the user asks to schedule or deploy periodic monitoring:

1. Add or update `.github/workflows/research-platform-monitor.yml`.
2. Add or update `config/monitor-sources.yaml` unless the user names a different
   source file.
3. Keep `workflow_dispatch` enabled so the monitor can be run manually.
4. Use a `schedule` cron trigger for unattended runs.
5. Ensure the workflow installs the fully pinned `requirements.lock` from the
   repository root. Refresh it only from a tested Python 3.11 environment when
   direct dependencies change.
6. Run:

   ```bash
   python -m research_platform.runner monitor-sources \
     --source-file config/monitor-sources.yaml \
     --max-items-per-source 20
   ```

   The standing brief comes from the `brief:` key in the source file; an
   explicit `--brief` overrides it.

7. Commit monitor artifacts back to the private repository:
   - `runs/`
   - `knowledge/platform_state.json`
8. Keep secrets in GitHub Actions secrets or environment variables, never in
   YAML source files.

## Notes

- The platform normalizes heterogeneous sources into `ResearchItem`s. RSS is only
  one connector.
- X/Twitter URLs are normalized today, while full timeline/search retrieval needs
  a configured authenticated connector.
- API-backed licensed providers and catalogues can be configured with
  `type: api_json`; secrets must be referenced by environment variable name.
- Source files may define a top-level `brief:` as the standing research
  intent for monitoring; `--brief` on the command line takes precedence.
- Model selection lives in `config/research.yaml`. The default provider is
  `anthropic` (Claude-backed evaluation when `ANTHROPIC_API_KEY` is set); the
  public gateway can fall back to local extractive evaluation when the key is
  missing, but that outcome is explicitly degraded and is never eligible for
  monitor acknowledgment. Strict consumers must set evaluation and synthesis
  failure policies to `fail`.
- Schema-v2 substantive claims include exact evidence excerpts (maximum 300
  characters). Committed item text is an excerpt-only bundle; evidence ranges
  and hashes are rewritten against that bundle, and evaluations without
  committed proof are omitted. RSS claims are grounded in RSS entry text;
  linked article retrieval is not performed.
- Use `execution.acknowledgment_mode: external` when delivery happens after the
  run. A downstream sender acknowledges eligible IDs only after the same
  healthy run is delivered. The acknowledgment gate revalidates committed
  artifact hashes, exact evidence, and derived eligibility before seen-state
  changes; failed or degraded runs have no eligible IDs.
- Total limits live under `execution.budgets`; exhaustion blocks
  acknowledgment. Retries are bounded to three transient attempts.
- The repository is PUBLIC. Run artifacts are committed, but item text contains
  only the exact retained-evidence bundle bounded by
  `storage.max_committed_item_text_chars` in `config/research.yaml`, so full
  third-party content and surrounding context are never republished.
  Never commit API keys or provider material that is restricted by license
  terms, and keep personal context out of committed files.
