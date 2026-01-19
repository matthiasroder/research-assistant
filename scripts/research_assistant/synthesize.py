"""
Synthesize themes across articles using Claude Sonnet.
"""

import os
from typing import Any

import anthropic


def synthesize_themes(articles: list[dict[str, Any]]) -> str:
    """
    Identify cross-article themes and patterns.
    """
    if not articles:
        return "No articles to synthesize."

    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    # Build summary of all articles
    article_summaries = []
    for article in articles:
        summary = article.get("summary", article["title"])
        source = article["source"]
        article_summaries.append(f"- {source}: {summary}")

    articles_text = "\n".join(article_summaries)

    prompt = f"""You are a research assistant identifying patterns across today's articles.

TODAY'S RELEVANT ARTICLES:
{articles_text}

Identify 2-4 themes or patterns you notice:
- What topics are multiple authors discussing?
- Are there contrasting viewpoints on the same issue?
- What trends or shifts do you notice?

Be concise. Write 2-4 bullet points, each 1-2 sentences.
Format as a simple bulleted list starting with "- "."""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}]
        )

        return response.content[0].text.strip()

    except Exception as e:
        print(f"  Error synthesizing themes: {e}")
        return "Could not synthesize themes."
