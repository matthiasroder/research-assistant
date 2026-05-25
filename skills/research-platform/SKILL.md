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
   `run.json`.

## Scheduling With GitHub Actions

When the user asks to schedule or deploy periodic monitoring:

1. Add or update `.github/workflows/research-platform-monitor.yml`.
2. Add or update `config/monitor-sources.yaml` unless the user names a different
   source file.
3. Keep `workflow_dispatch` enabled so the monitor can be run manually.
4. Use a `schedule` cron trigger for unattended runs.
5. Ensure the workflow installs `scripts/research_assistant/requirements.txt`.
6. Run:

   ```bash
   python -m research_platform.runner monitor-sources \
     --brief "Monitor configured research sources" \
     --source-file config/monitor-sources.yaml \
     --max-items-per-source 20
   ```

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
- Model selection lives in `config/research.yaml`. The default provider is local
  extractive evaluation so the platform runs without API keys. Set
  `models.evaluation.provider: anthropic` and provide `ANTHROPIC_API_KEY` for
  Claude-backed evaluation.
- The repository is private, so generated run artifacts may be committed. Still
  avoid committing API keys or provider material that is explicitly restricted by
  license terms.
