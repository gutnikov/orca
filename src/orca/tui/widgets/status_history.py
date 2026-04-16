from __future__ import annotations

from datetime import UTC, datetime

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static

from orca.engine.types import Issue, State


def _relative_time(timestamp: str) -> str:
    try:
        dt = datetime.fromisoformat(timestamp)
        now = datetime.now(UTC)
        delta = now - dt
        seconds = int(delta.total_seconds())
        if seconds < 60:
            return "now"
        if seconds < 3600:
            return f"{seconds // 60}m ago"
        if seconds < 86400:
            return f"{seconds // 3600}h ago"
        return f"{seconds // 86400}d ago"
    except (ValueError, TypeError):
        return ""


def build_timeline(issue: Issue) -> str:
    lines: list[str] = []
    states_seen: list[tuple[str, str, str | None]] = []

    for entry in issue.event_log:
        if entry.type == "created":
            state_name = entry.data.get("state", issue.state)
            states_seen.append((state_name, entry.timestamp, None))
        elif entry.type == "state_changed":
            outcome = entry.data.get("outcome")
            to_state = entry.data.get("to", "")
            if states_seen:
                prev = states_seen[-1]
                states_seen[-1] = (prev[0], prev[1], outcome)
            states_seen.append((to_state, entry.timestamp, None))

    if not states_seen:
        states_seen.append((issue.state, "", None))

    for i, (state_name, timestamp, outcome) in enumerate(states_seen):
        is_current = i == len(states_seen) - 1
        marker = "◉" if is_current else "●"
        time_str = _relative_time(timestamp) if timestamp else ""
        line = f"{marker} {state_name}"
        if time_str:
            line += f"  {time_str}"
        lines.append(line)
        if outcome:
            lines.append(f"  outcome: {outcome}")
        if not is_current:
            lines.append("    ↓")

    return "\n".join(lines)


class StatusHistory(VerticalScroll):
    """Right panel — shows state transition timeline for the selected issue."""

    DEFAULT_CSS = """
    StatusHistory {
        width: 3fr;
        padding: 1;
    }
    """

    def __init__(self) -> None:
        super().__init__(id="status-history")
        self._static = Static("", id="timeline-content")
        self._current_issue_id: str | None = None

    def compose(self) -> ComposeResult:
        yield self._static

    def show_issue(self, issue_id: str, state: State) -> None:
        issue = state.issues.get(issue_id)
        if issue is None:
            self._current_issue_id = None
            self._static.update("")
            return
        self._current_issue_id = issue_id
        self._static.update(build_timeline(issue))

    def clear(self) -> None:
        self._current_issue_id = None
        self._static.update("")
