from __future__ import annotations

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


def truncate_insights_so_far(content: str, max_lines: int = 3000) -> str:
    """Truncate insights_so_far to the last max_lines lines."""
    lines = content.split("\n")
    if len(lines) <= max_lines:
        return content
    return "\n".join(lines[-max_lines:])
