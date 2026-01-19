"""
Write the research digest to markdown.
"""

from datetime import datetime
from pathlib import Path
from typing import Any


def write_digest(
    output_path: Path,
    articles: list[dict[str, Any]],
    themes: str,
    date: str
) -> None:
    """Write the research digest to a markdown file."""

    # Ensure directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Format date nicely
    try:
        date_obj = datetime.strptime(date, "%Y-%m-%d")
        formatted_date = date_obj.strftime("%B %d, %Y")
    except ValueError:
        formatted_date = date

    # Build markdown content
    lines = [
        f"# Research Digest: {formatted_date}",
        "",
        f"*Generated at {datetime.now().strftime('%H:%M')} by Research Assistant*",
        "",
        "---",
        "",
        "## Themes Today",
        "",
        themes,
        "",
        "---",
        "",
        "## Articles",
        "",
    ]

    for article in articles:
        title = article.get("title", "Untitled")
        source = article.get("source", "Unknown")
        url = article.get("url", "")
        summary = article.get("summary", "No summary available.")
        key_insight = article.get("key_insight", "")
        relevance = article.get("relevance", "")
        tags = article.get("tags", "")

        lines.append(f"### {source}: [{title}]({url})")
        lines.append("")
        lines.append(f"**Summary:** {summary}")
        lines.append("")

        if key_insight:
            lines.append(f"**Key insight:** {key_insight}")
            lines.append("")

        if relevance:
            lines.append(f"**Relevance:** {relevance}")
            lines.append("")

        if tags:
            # Format tags as hashtags
            tag_list = [f"#{t.strip()}" for t in tags.split(",")]
            lines.append(f"**Tags:** {' '.join(tag_list)}")
            lines.append("")

        lines.append("---")
        lines.append("")

    # Write file
    content = "\n".join(lines)
    output_path.write_text(content)
