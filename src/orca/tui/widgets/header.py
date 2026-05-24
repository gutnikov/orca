from __future__ import annotations

from typing import Any

from textual.widgets import Static

from orca.engine.types import State, StateMachineConfig


def _format_elapsed(seconds: float) -> str:
    """Format elapsed seconds as a human-readable string."""
    if seconds < 0:
        return "0s"
    total = int(seconds)
    if total < 60:
        return f"{total}s"
    minutes = total // 60
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    remaining_minutes = minutes % 60
    return f"{hours}h{remaining_minutes:02d}m"


class OrcaHeader(Static):
    """Custom header bar showing run stats in a single line."""

    DEFAULT_CSS = """
    OrcaHeader {
        dock: top;
        height: 1;
        background: #252540;
        color: white;
        text-style: bold;
    }
    """

    def __init__(
        self,
        branch_name: str,
        config: StateMachineConfig | None = None,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self._branch_name = branch_name
        self._config = config
        self._state: State | None = None
        self._sessions: list[dict[str, Any]] = []
        self._active_workers: int = 0
        self._paused_workers: int = 0

    def on_mount(self) -> None:
        self.update(self.render_text())

    def update_state(
        self,
        state: State,
        sessions: list[dict[str, Any]],
        active_workers: int | None = None,
    ) -> None:
        """Update header with current state and sessions."""
        self._state = state
        self._sessions = sessions
        if active_workers is not None:
            self._active_workers = active_workers
        else:
            self._active_workers = sum(1 for issue in state.issues.values() if issue.worker_active)
        # Debug-mode pauses: worker completed and is waiting for human review
        # before transitioning. Counted distinctly from active workers so the
        # user sees "step finished, your move" rather than mistaking it for idle.
        self._paused_workers = sum(1 for issue in state.issues.values() if getattr(issue, "debug_pending", False))
        self.update(self.render_text())

    def render_text(self) -> str:
        """Render the header text. Public for testability."""
        if self._state is None:
            return f"  {self._branch_name} \u2502 waiting\u2026"

        # Check if all issues are in terminal states
        all_terminal = self._all_terminal()
        has_failures = any(issue.failure_count > 0 for issue in self._state.issues.values())

        if all_terminal:
            left = f"  \u2713 {self._branch_name} \u2502 completed"
        else:
            # Status dot: red if failures, amber if paused for debug review,
            # green otherwise. Paused is between healthy and broken \u2014 the run
            # IS healthy, it just needs the user's attention.
            if has_failures:
                dot = "[red]\u25cf[/red]"
            elif self._paused_workers > 0:
                dot = "[#d4a064]\u25cf[/#d4a064]"
            else:
                dot = "[green]\u25cf[/green]"

            parts: list[str] = [f"  {dot} {self._branch_name}"]

            # Workers N \u00b7 \u23f8 M paused (debug)
            workers_text = f"Workers {self._active_workers}"
            if self._paused_workers > 0:
                paused_label = "paused" if self._paused_workers == 1 else "paused"
                workers_text += f" \u00b7 [#d4a064]\u23f8 {self._paused_workers} {paused_label} (debug)[/#d4a064]"
            parts.append(workers_text)

            # Failures (conditional)
            total_failures = sum(issue.failure_count for issue in self._state.issues.values())
            if total_failures > 0:
                parts.append(f"[red]{total_failures} failed[/red]")

            left = " \u2502 ".join(parts)

        # Elapsed time on the right
        elapsed_text = self._elapsed_text()
        if elapsed_text:
            return f"{left}[right]{elapsed_text}  [/right]"
        return left

    def _all_terminal(self) -> bool:
        """Check if all issues are in terminal states."""
        if self._state is None:
            return False
        return all(issue.state == "done" for issue in self._state.issues.values())

    def _step_text(self) -> str | None:
        """Calculate step N/M for the root issue."""
        if self._state is None or self._config is None:
            return None

        root = self._find_root()
        if root is None:
            return None

        root_issue = self._state.issues[root]
        non_terminal_states = list(self._config.root_type_def.states.keys())
        total_steps = len(non_terminal_states)
        if total_steps == 0:
            return None

        # Count unique non-terminal states visited (present in visit_counts)
        visited = sum(1 for s in non_terminal_states if root_issue.visit_counts.get(s, 0) > 0)
        # Cap at total
        visited = min(visited, total_steps)

        return f"Step {visited}/{total_steps}"

    def _elapsed_text(self) -> str | None:
        """Calculate elapsed time from first session's started_at."""
        if not self._sessions:
            return None

        # Find the earliest started_at
        import time

        earliest: float | None = None
        for session in self._sessions:
            started_at = session.get("started_at")
            if (
                started_at is not None
                and isinstance(started_at, int | float)
                and (earliest is None or started_at < earliest)
            ):
                earliest = float(started_at)

        if earliest is None:
            return None

        elapsed = time.time() - earliest
        return _format_elapsed(elapsed)

    def _find_root(self) -> str | None:
        """Find the root issue (decomposed_from is None)."""
        if self._state is None:
            return None
        for iid, issue in self._state.issues.items():
            if issue.decomposed_from is None:
                return iid
        return None
