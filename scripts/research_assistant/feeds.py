"""
Fetch and parse RSS feeds.
"""

from pathlib import Path
from typing import Any

import feedparser
import yaml


def load_feed_config(config_path: Path) -> list[dict[str, str]]:
    """Load feed configuration from YAML file."""
    with open(config_path) as f:
        config = yaml.safe_load(f)
    return config.get("feeds", [])


def fetch_feed(feed_config: dict[str, str]) -> list[dict[str, Any]]:
    """Fetch and parse a single RSS feed."""
    name = feed_config["name"]
    url = feed_config["url"]

    try:
        parsed = feedparser.parse(url)

        if parsed.bozo and not parsed.entries:
            print(f"  Warning: Failed to parse {name}: {parsed.bozo_exception}")
            return []

        articles = []
        for entry in parsed.entries:
            # Extract content or summary
            content = ""
            if hasattr(entry, "content") and entry.content:
                content = entry.content[0].get("value", "")
            elif hasattr(entry, "summary"):
                content = entry.summary
            elif hasattr(entry, "description"):
                content = entry.description

            # Clean HTML (basic)
            import re
            content = re.sub(r"<[^>]+>", "", content)
            content = content.strip()

            articles.append({
                "source": name,
                "title": entry.get("title", "Untitled"),
                "url": entry.get("link", ""),
                "content": content[:2000],  # Limit content length
                "published": entry.get("published", ""),
            })

        print(f"  {name}: {len(articles)} articles")
        return articles

    except Exception as e:
        print(f"  Error fetching {name}: {e}")
        return []


def fetch_all_feeds(config_path: Path) -> list[dict[str, Any]]:
    """Fetch all configured RSS feeds."""
    feeds = load_feed_config(config_path)
    all_articles = []

    for feed in feeds:
        articles = fetch_feed(feed)
        all_articles.extend(articles)

    return all_articles
