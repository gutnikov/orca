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
_BAR_CHAR = "━"
_PROGRESS_STALE_SECONDS = 60
_DEFAULT_BAR_WIDTH = 24


def _render_progress_bar(
    lines: Text,
    progress: int,
    fill_style: str,
    dim_style: str = "dim",
    bar_width: int = _DEFAULT_BAR_WIDTH,
) -> None:
    """Render a thin progress bar using ━ characters."""
    filled = int(bar_width * progress / 100)
    unfilled = bar_width - filled
    lines.append(f"  {_BAR_CHAR * filled}", style=fill_style)
    if unfilled > 0:
        lines.append(_BAR_CHAR * unfilled, style=dim_style)
    lines.append(f" {progress}%", style=f"bold {fill_style}" if progress < 100 else dim_style)


def _is_progress_stale(progress_updated_at: str | None) -> bool:
    """Return True if progress hasn't been updated in _PROGRESS_STALE_SECONDS."""
    if not progress_updated_at:
        return False
    try:
        updated = datetime.fromisoformat(progress_updated_at)
        elapsed = (datetime.now(UTC) - updated).total_seconds()
        return elapsed > _PROGRESS_STALE_SECONDS
    except (ValueError, TypeError):
        return False


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
        self._header = Static("WORKERS", id="phases-header")
        self._static = Static(_PLACEHOLDER)
        self._hint = Static("i  insights", id="phases-hint")
        self._sessions: list[dict[str, Any]] = []
        self._issue_id: str = ""
        self._tick: int = 0
        self._entry_map: list[dict[str, Any]] = []
        self._selected_session_id: str = ""
        self._outcomes: dict[str, str] = {}

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
        self._selected_session_id = ""
        self._static.update(_PLACEHOLDER)

    def refresh_tick(self, tick: int) -> None:
        """Advance the spinner for active phases."""
        self._tick = tick
        if self._sessions:
            self._render_phases()

    def on_click(self, event: Click) -> None:
        """Handle click on a phase entry — determine which entry by y offset."""
        widget = event.widget
        if widget is not self._static or not self._entry_map:
            return
        # Each entry is 3 lines (name, duration, arrow) except the last (2 lines)
        y = event.y
        entry_idx = y // 3
        if 0 <= entry_idx < len(self._entry_map):
            session = self._entry_map[entry_idx]
            session_id = str(session.get("session_id", ""))
            active = session.get("completed_at") is None
            if session_id:
                self._selected_session_id = session_id
                self._render_phases()
                self.post_message(
                    PhaseSelected(
                        session_id=session_id,
                        active=active,
                        issue_id=self._issue_id,
                    )
                )

    def set_outcomes(self, outcomes: dict[str, str]) -> None:
        """Set outcome values per session_id for display."""
        self._outcomes = outcomes
        if self._sessions:
            self._render_phases()

    def _render_phases(self) -> None:
        if not self._sessions:
            self._static.update(_PLACEHOLDER)
            return

        lines = Text()
        reversed_sessions = list(reversed(self._sessions))
        self._entry_map = reversed_sessions

        for i, session in enumerate(reversed_sessions):
            state_name = str(session.get("state", "unknown"))
            is_active = session.get("completed_at") is None
            session_id = str(session.get("session_id", ""))
            outcome = self._outcomes.get(session_id, "")
            is_selected = session_id == self._selected_session_id

            if is_active:
                is_waiting = bool(session.get("waiting", False))
                prefix = "→ " if is_selected else "  "
                lines.append(prefix)

                if is_waiting:
                    # gh#15 — distinguish HITL-paused sessions from active ones.
                    # No spinner, no progress bar (inactivity_timeout is paused),
                    # blue chosen for "waiting on you" vs yellow "in flight".
                    lines.append("⏸ ", style="bold blue")
                    lines.append(state_name, style="bold blue")
                    lines.append("  WAITING", style="bold blue")
                    elapsed = _elapsed_str(str(session.get("started_at", "")))
                    if elapsed:
                        lines.append(f"\n  paused for {elapsed}", style="dim blue")
                else:
                    frame = _SPINNER[self._tick % len(_SPINNER)]
                    lines.append(f"{frame} ", style="bold yellow")
                    lines.append(state_name, style="bold yellow")

                    progress = session.get("progress")
                    status_text = session.get("status")
                    progress_updated_at = session.get("progress_updated_at")
                    stale = _is_progress_stale(progress_updated_at)

                    if status_text and not stale:
                        lines.append(f"\n  {status_text}", style="dim")

                    if progress is not None and progress > 0 and not stale:
                        lines.append("\n")
                        _render_progress_bar(lines, progress, "yellow")

                    elapsed = _elapsed_str(str(session.get("started_at", "")))
                    if elapsed:
                        lines.append(f"\n  {elapsed}", style="dim")
            else:
                is_failed = session.get("failed", False)
                is_interrupted = session.get("interrupted", False)
                prefix = "→ " if is_selected else "  "
                lines.append(prefix)

                if is_failed:
                    lines.append("✗ ", style="bold red")
                    lines.append(state_name, style="bold red")
                    lines.append("  stopped", style="dim italic")
                elif is_interrupted:
                    lines.append("⏸ ", style="bold orange3")
                    lines.append(state_name, style="bold orange3")
                    lines.append("  interrupted", style="dim italic")
                else:
                    lines.append("✓ ", style="green")
                    lines.append(state_name, style="green")
                    if outcome:
                        lines.append(f"  {outcome}", style="dim italic")

                # Progress bar for completed/failed/interrupted
                progress = session.get("progress")
                if progress is not None:
                    if is_failed:
                        lines.append("\n")
                        _render_progress_bar(lines, progress, "red")
                    elif is_interrupted:
                        lines.append("\n")
                        _render_progress_bar(lines, progress, "orange3")
                    else:
                        lines.append("\n")
                        _render_progress_bar(lines, 100, "dim")

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
