"""
Build context from repository content.
"""

from pathlib import Path


def build_context(drafts_dir: Path, ideas_path: Path) -> str:
    """
    Build a succinct context description from drafts and IDEAS.md.

    Returns a ~150 word summary of current focus.
    """
    context_parts = []

    # Read IDEAS.md
    if ideas_path.exists():
        ideas_content = ideas_path.read_text()
        # Extract first 500 chars as summary
        ideas_summary = ideas_content[:500].strip()
        context_parts.append(f"IDEAS AND INTERESTS:\n{ideas_summary}")

    # Read current drafts (just titles and first lines)
    if drafts_dir.exists():
        draft_summaries = []
        for draft_file in sorted(drafts_dir.glob("*.md"))[:5]:  # Limit to 5 most recent
            try:
                content = draft_file.read_text()
                lines = content.split("\n")
                title = lines[0].replace("#", "").strip() if lines else draft_file.stem
                # Get first non-empty line after title
                first_line = ""
                for line in lines[1:10]:
                    line = line.strip()
                    if line and not line.startswith("*") and not line.startswith("-"):
                        first_line = line[:100]
                        break
                draft_summaries.append(f"- {title}: {first_line}")
            except Exception:
                continue

        if draft_summaries:
            context_parts.append("CURRENT DRAFTS:\n" + "\n".join(draft_summaries))

    full_context = "\n\n".join(context_parts)

    # Create succinct version for filtering
    succinct = f"""Matthias writes about AI tools, personal productivity systems, and human-AI collaboration.

{full_context}

Focus areas: AI assistants, local-first software, data portability, creative workflows, agentic AI."""

    return succinct[:2000]  # Limit total context
