"""
Deep analysis of relevant articles using Claude Sonnet.
"""

import os
from typing import Any

import anthropic


def analyze_articles(articles: list[dict[str, Any]], context: str) -> list[dict[str, Any]]:
    """
    Perform deep analysis on each relevant article using Claude Sonnet.
    """
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    analyzed = []
    for i, article in enumerate(articles):
        print(f"  Analyzing {i + 1}/{len(articles)}: {article['title'][:50]}...")
        analysis = analyze_single(client, article, context)
        if analysis:
            article.update(analysis)
            analyzed.append(article)

    return analyzed


def analyze_single(
    client: anthropic.Anthropic,
    article: dict[str, Any],
    context: str
) -> dict[str, str] | None:
    """Analyze a single article."""

    prompt = f"""You are a research assistant providing deep analysis of an article.

CONTEXT ABOUT THE USER:
{context}

ARTICLE TO ANALYZE:
Title: {article['title']}
Source: {article['source']}
URL: {article['url']}

Content:
{article['content']}

Provide analysis in this exact format:

SUMMARY: [2-3 sentence summary of the article]

KEY_INSIGHT: [The most important or contrarian idea from this article]

RELEVANCE: [Why this matters to the user's current work - be specific about connections to their drafts or ideas]

TAGS: [3-5 relevant tags, comma-separated, like: ai, productivity, local-first]

Be concise and specific. Focus on what makes this article valuable for the user."""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}]
        )

        response_text = response.content[0].text.strip()

        # Parse structured response
        analysis = {}
        current_field = None
        current_content = []

        for line in response_text.split("\n"):
            line = line.strip()
            if line.startswith("SUMMARY:"):
                if current_field:
                    analysis[current_field] = " ".join(current_content).strip()
                current_field = "summary"
                current_content = [line.replace("SUMMARY:", "").strip()]
            elif line.startswith("KEY_INSIGHT:"):
                if current_field:
                    analysis[current_field] = " ".join(current_content).strip()
                current_field = "key_insight"
                current_content = [line.replace("KEY_INSIGHT:", "").strip()]
            elif line.startswith("RELEVANCE:"):
                if current_field:
                    analysis[current_field] = " ".join(current_content).strip()
                current_field = "relevance"
                current_content = [line.replace("RELEVANCE:", "").strip()]
            elif line.startswith("TAGS:"):
                if current_field:
                    analysis[current_field] = " ".join(current_content).strip()
                current_field = "tags"
                current_content = [line.replace("TAGS:", "").strip()]
            elif current_field and line:
                current_content.append(line)

        if current_field:
            analysis[current_field] = " ".join(current_content).strip()

        return analysis

    except Exception as e:
        print(f"    Error analyzing article: {e}")
        return None
