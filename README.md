# Research Assistant

An AI-powered research assistant that runs while you sleep. It fetches RSS feeds, filters for relevance to *your* current work, and writes a personalized digest to your repo every morning.

## How It Works

```
5:00 AM → Fetch RSS feeds → Filter with Claude Haiku → Analyze with Claude Sonnet → Write digest → Commit
```

1. **Fetches** articles from RSS feeds you configure
2. **Reads** your drafts and IDEAS.md to understand your current focus
3. **Filters** articles for relevance (batch processing with Claude Haiku)
4. **Analyzes** relevant articles in depth (Claude Sonnet)
5. **Synthesizes** themes across articles
6. **Writes** a personalized digest to `knowledge/feeds/YYYY-MM-DD.md`
7. **Commits** and pushes automatically

## Quick Start

### 1. Fork this repo

Click "Use this template" or fork it.

### 2. Add your Anthropic API key

Go to **Settings → Secrets and variables → Actions → New repository secret**

- Name: `ANTHROPIC_API_KEY`
- Value: Your API key from [console.anthropic.com](https://console.anthropic.com)

### 3. Enable workflow permissions

Go to **Settings → Actions → General → Workflow permissions**

Select **"Read and write permissions"**

### 4. Configure your feeds

Edit `config/feeds.yaml`:

```yaml
feeds:
  - name: Simon Willison
    url: https://simonwillison.net/atom/everything/

  - name: Hacker News
    url: https://hnrss.org/frontpage

  # Add your favorite blogs and news sources
```

### 5. Add your context

Edit `IDEAS.md` with your current interests, projects, and goals. The assistant uses this to determine what's relevant to you.

Add drafts to `content/drafts/` - these are also used for context.

### 6. Run it

Go to **Actions → Research Assistant → Run workflow**

Or wait until 5am Berlin time (4am UTC) for the scheduled run.

## Output

Digests appear in `knowledge/feeds/`:

```markdown
# Research Digest: January 19, 2026

## Themes Today
- Three authors discussed agentic AI workflows
- Growing interest in local-first approaches

## Articles

### Simon Willison: "Building with Claude"
**Summary:** Explores patterns for building reliable AI applications...
**Key insight:** Context window management matters more than prompt engineering
**Relevance:** High - directly relates to your draft on AI workflows
**Tags:** #ai #engineering
```

## Configuration

### Schedule

Default: 5am Berlin time (4am UTC). Edit `.github/workflows/research-assistant.yml`:

```yaml
schedule:
  - cron: '0 4 * * *'  # Change this to your preferred time
```

### Model Selection

The assistant uses:
- **Claude Haiku** for filtering (fast, cheap)
- **Claude Sonnet** for analysis (thorough, nuanced)

Edit `scripts/research_assistant/filter.py` and `analyze.py` to change models.

## Cost

Estimated cost: **~$0.50/day** with typical usage (50 feeds, ~30 relevant articles).

- Haiku filtering: ~$0.02
- Sonnet analysis: ~$0.45
- Synthesis: ~$0.02

## The Origin Story

This tool was built in a single collaborative session between a human and Claude. Read the full conversation: [docs/how-it-was-built.md](docs/how-it-was-built.md)

## License

MIT - See LICENSE file
