---
name: research-platform
description: Run the local agentic research platform for topic research, URL analysis, and source monitoring.
---

# Research Platform Skill

Use this skill when the user asks to research a topic, analyze one or more URLs,
monitor sources, discover useful source URLs, or run the local agentic research
platform.

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
