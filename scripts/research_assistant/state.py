"""
State management for tracking processed articles.
"""

import json
from pathlib import Path
from typing import Any


def load_state(state_path: Path) -> dict[str, Any]:
    """Load state from JSON file."""
    if state_path.exists():
        try:
            with open(state_path) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {"processed_urls": [], "last_run": None}
    return {"processed_urls": [], "last_run": None}


def save_state(state_path: Path, state: dict[str, Any]) -> None:
    """Save state to JSON file."""
    # Ensure directory exists
    state_path.parent.mkdir(parents=True, exist_ok=True)

    # Keep only last 1000 URLs to prevent unbounded growth
    if len(state.get("processed_urls", [])) > 1000:
        state["processed_urls"] = state["processed_urls"][-1000:]

    with open(state_path, "w") as f:
        json.dump(state, f, indent=2)
