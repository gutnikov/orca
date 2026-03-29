from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.events import Click
from textual.widgets import Static

from orca.tui.messages import PhaseSelected

_SPINNER = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
_PLACEHOLDER = "*Select an issue to view phases*"


class PhasesPanel(VerticalScroll):
    """Scrollable list of worker phases for the selected issue."""

    DEFAULT_CSS = """
    PhasesPanel {
        height: 1fr;
        min-height: 10;
        border-top: solid #333333;
        padding: 1;
    }
    PhasesPanel Static {
        width: 1fr;
    }
    PhasesPanel #phases-header {
        height: 1;
        color: #666666;
        text-style: bold;
    }
    PhasesPanel #phases-hint {
        dock: bottom;
        height: 1;
        color: #444444;
    }
    """

    def __init__(self) -> None:
        super().__init__(id="phases-panel")
        self._header = Static("PHASES", id="phases-header")
        self._static = Static(_PLACEHOLDER)
        self._hint = Static("i  insights", id="phases-hint")
        self._sessions: list[dict[str, Any]] = []
        self._issue_id: str = ""
        self._tick: int = 0

    def compose(self) -> ComposeResult:
        yield self._header
        yield self._static
        yield self._hint

    def show_phases(self, issue_id: str, sessions: list[dict[str, Any]]) -> None:
        """Display phases for the given issue."""
        self._issue_id = issue_id
        self._sessions = [s for s in sessions if s.get("issue_id") == issue_id]
        self._render_phases()

    def clear(self) -> None:
        self._issue_id = ""
        self._sessions = []
        self._static.update(_PLACEHOLDER)

    def refresh_tick(self, tick: int) -> None:
        """Advance the spinner for active phases."""
        self._tick = tick
        if self._sessions:
            self._render_phases()

    def on_click(self, event: Click) -> None:
        """Handle click on a phase entry."""
        widget = event.widget
        if widget is self._static and self._sessions:
            for session in reversed(self._sessions):
                session_id = str(session.get("session_id", ""))
                active = session.get("completed_at") is None
                if session_id:
                    self.post_message(
                        PhaseSelected(
                            session_id=session_id,
                            active=active,
                            issue_id=self._issue_id,
                        )
                    )
                    break

    def _render_phases(self) -> None:
        if not self._sessions:
            self._static.update(_PLACEHOLDER)
            return

        lines = Text()
        reversed_sessions = list(reversed(self._sessions))

        for i, session in enumerate(reversed_sessions):
            state_name = str(session.get("state", "unknown"))
            is_active = session.get("completed_at") is None

            if is_active:
                frame = _SPINNER[self._tick % len(_SPINNER)]
                lines.append(f"{frame} ", style="bold yellow")
                lines.append(state_name, style="bold yellow")
                elapsed = _elapsed_str(str(session.get("started_at", "")))
                if elapsed:
                    lines.append(f"\n  {elapsed}", style="dim")
            else:
                lines.append("✓ ", style="green")
                lines.append(state_name, style="green")
                duration = _duration_str(
                    str(session.get("started_at", "")),
                    str(session.get("completed_at", "")),
                )
                if duration:
                    lines.append(f"\n  {duration}", style="dim")

            if i < len(reversed_sessions) - 1:
                lines.append("\n  ↑\n", style="dim")
            else:
                lines.append("\n")

        with contextlib.suppress(Exception):
            self._static.update(lines)


def _elapsed_str(started_at: str) -> str:
    try:
        dt = datetime.fromisoformat(started_at)
        delta = datetime.now(UTC) - dt
        total = int(delta.total_seconds())
        if total < 0:
            total = 0
        minutes, seconds = divmod(total, 60)
        if minutes > 0:
            return f"{minutes}m {seconds:02d}s"
        return f"{seconds}s"
    except (ValueError, TypeError):
        return ""


def _duration_str(started_at: str, completed_at: str) -> str:
    try:
        start = datetime.fromisoformat(started_at)
        end = datetime.fromisoformat(completed_at)
        total = int((end - start).total_seconds())
        if total < 0:
            total = 0
        minutes, seconds = divmod(total, 60)
        if minutes > 0:
            return f"{minutes}m {seconds:02d}s"
        return f"{seconds}s"
    except (ValueError, TypeError):
        return ""
