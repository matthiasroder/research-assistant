#!/usr/bin/env python3
"""
Research Assistant - Main Entry Point

Fetches RSS feeds, filters for relevance, analyzes with Claude,
and writes a personalized digest.
"""

import os
from datetime import datetime
from pathlib import Path

from .feeds import fetch_all_feeds
from .context import build_context
from .state import load_state, save_state
from .filter import filter_articles
from .analyze import analyze_articles
from .synthesize import synthesize_themes
from .output import write_digest


def main():
    """Run the research assistant pipeline."""
    print("=" * 60)
    print("Research Assistant Starting")
    print(f"Time: {datetime.now().isoformat()}")
    print("=" * 60)

    # Paths
    repo_root = Path(__file__).parent.parent.parent
    config_path = repo_root / "config" / "feeds.yaml"
    state_path = repo_root / "knowledge" / "feeds" / "state.json"
    output_dir = repo_root / "knowledge" / "feeds"
    drafts_dir = repo_root / "content" / "drafts"
    ideas_path = repo_root / "IDEAS.md"

    # Load state
    state = load_state(state_path)
    processed_urls = set(state.get("processed_urls", []))
    print(f"Previously processed: {len(processed_urls)} articles")

    # Fetch feeds
    print("\n--- Fetching Feeds ---")
    articles = fetch_all_feeds(config_path)
    print(f"Fetched: {len(articles)} total articles")

    # Filter out already processed
    new_articles = [a for a in articles if a["url"] not in processed_urls]
    print(f"New articles: {len(new_articles)}")

    if not new_articles:
        print("No new articles to process. Exiting.")
        return

    # Build context from drafts and ideas
    print("\n--- Building Context ---")
    context = build_context(drafts_dir, ideas_path)
    print(f"Context length: {len(context)} characters")

    # Filter for relevance (Haiku)
    print("\n--- Filtering for Relevance ---")
    relevant_articles = filter_articles(new_articles, context)
    print(f"Relevant articles: {len(relevant_articles)}")

    if not relevant_articles:
        print("No relevant articles found. Updating state and exiting.")
        # Still mark all as processed
        state["processed_urls"] = list(processed_urls | {a["url"] for a in new_articles})
        state["last_run"] = datetime.now().isoformat()
        save_state(state_path, state)
        return

    # Deep analysis (Sonnet)
    print("\n--- Deep Analysis ---")
    analyzed_articles = analyze_articles(relevant_articles, context)

    # Synthesize themes
    print("\n--- Synthesizing Themes ---")
    themes = synthesize_themes(analyzed_articles)

    # Write digest
    print("\n--- Writing Digest ---")
    today = datetime.now().strftime("%Y-%m-%d")
    output_path = output_dir / f"{today}.md"
    write_digest(output_path, analyzed_articles, themes, today)
    print(f"Digest written to: {output_path}")

    # Update state
    all_processed = processed_urls | {a["url"] for a in new_articles}
    state["processed_urls"] = list(all_processed)
    state["last_run"] = datetime.now().isoformat()
    save_state(state_path, state)
    print(f"State updated. Total processed: {len(all_processed)}")

    print("\n" + "=" * 60)
    print("Research Assistant Complete")
    print("=" * 60)


if __name__ == "__main__":
    main()
