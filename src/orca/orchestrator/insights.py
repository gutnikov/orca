from __future__ import annotations

from pathlib import Path
from typing import Any

from orca.engine.types import State


def serialize_state_for_insights(state: State) -> dict[str, Any]:
    """Serialize engine state into a dict suitable for the insights prompt."""
    issues: dict[str, Any] = {}
    for issue_id, issue in state.issues.items():
        issues[issue_id] = {
            "fields": dict(issue.fields),
            "state": issue.state,
            "worker_active": issue.worker_active,
            "failure_count": issue.failure_count,
            "decomposed_from": issue.decomposed_from,
            "depends_on": list(issue.depends_on),
            "event_log": [{"timestamp": e.timestamp, "type": e.type, "data": dict(e.data)} for e in issue.event_log],
        }
    return {"issues": issues}


def gather_transcripts(
    transcripts_dir: Path,
    sessions: list[dict[str, Any]],
    max_lines_per_transcript: int = 200,
    global_budget: int = 3000,
) -> dict[str, str]:
    """Read rendered transcript .md files, truncated to budget.

    Skips sessions with issue_id == "__insights__".
    Returns a dict mapping session_id to truncated transcript content.
    """
    result: dict[str, str] = {}
    total_lines = 0

    for session in sessions:
        if session.get("issue_id") == "__insights__":
            continue

        session_id = session.get("session_id", "")
        md_path = transcripts_dir / f"{session_id}.md"
        if not md_path.exists():
            continue

        content = md_path.read_text()
        lines = content.split("\n")

        # Per-transcript cap
        if len(lines) > max_lines_per_transcript:
            lines = lines[-max_lines_per_transcript:]

        # Global budget cap
        remaining = global_budget - total_lines
        if remaining <= 0:
            break
        if len(lines) > remaining:
            lines = lines[-remaining:]

        total_lines += len(lines)
        result[session_id] = "\n".join(lines)

    return result


def truncate_insights_so_far(content: str, max_lines: int = 3000) -> str:
    """Truncate insights_so_far to the last max_lines lines."""
    lines = content.split("\n")
    if len(lines) <= max_lines:
        return content
    return "\n".join(lines[-max_lines:])
