from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from rich.text import Text
from textual.widgets import Tree
from textual.widgets.tree import TreeNode

from orca.engine.types import EventLogEntry, Issue, State, StateMachineConfig
from orca.tui.messages import InsightsSelected, IssueSelected

# Braille dot spinner frames
_SPINNER = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

# Progress bar colors
_COLOR_DONE = "#8bc88b"
_COLOR_ACTIVE = "#d4a064"
_COLOR_FAILED = "#e06070"
_COLOR_PENDING = "#333333"


def _elapsed_str(started_at: str) -> str:
    """Format elapsed time since started_at."""
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
    """Format duration between two ISO timestamps."""
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


def _progress_bar_text(
    config: StateMachineConfig,
    visit_counts: dict[str, int],
    current_state: str,
    failed_states: set[str],
) -> Text | None:
    """Return a Rich Text with colored block segments for each non-terminal state."""
    non_terminal = list(config.root_type_def.states.keys())
    if not non_terminal:
        return None
    bar = Text()
    for name in non_terminal:
        segment = "▬▬▬"
        if name in failed_states:
            bar.append(segment, style=_COLOR_FAILED)
        elif name == current_state:
            bar.append(segment, style=_COLOR_ACTIVE)
        elif name in visit_counts:
            bar.append(segment, style=_COLOR_DONE)
        else:
            bar.append(segment, style=_COLOR_PENDING)
    return bar


def _pending_steps(config: StateMachineConfig, visit_counts: dict[str, int]) -> list[str]:
    """Return non-terminal states not yet visited."""
    return [name for name in config.root_type_def.states if name not in visit_counts]


def _extract_result_outcomes(event_log: list[EventLogEntry]) -> dict[str, str]:
    """Extract outcome for each worker_result event, keyed by state.

    Returns dict like {"planning": "ready", "scoping": "decompose"}.
    Multiple results for same state: last one wins.
    """
    outcomes: dict[str, str] = {}
    for entry in event_log:
        if entry.type == "worker_result":
            state = entry.data.get("state", "")
            outcome = entry.data.get("outcome", "")
            if state and outcome:
                outcomes[state] = outcome
    return outcomes


def _extract_failure_errors(event_log: list[EventLogEntry]) -> dict[str, str]:
    """Extract error for each worker_failed event, keyed by state.

    Returns dict like {"planning": "exit code 1"}.
    Multiple failures for same state: last one wins.
    """
    errors: dict[str, str] = {}
    for entry in event_log:
        if entry.type == "worker_failed":
            state = entry.data.get("state", "")
            error = entry.data.get("error", "")
            if state and error:
                errors[state] = error
    return errors


def _compute_failed_states(issue: Issue) -> set[str]:
    """States where the last event was worker_failed (retries exhausted)."""
    # Track per-state: was the last worker event a failure?
    last_event_type: dict[str, str] = {}
    for entry in issue.event_log:
        if entry.type in ("worker_result", "worker_failed"):
            state = entry.data.get("state", "")
            if state:
                last_event_type[state] = entry.type
    return {s for s, t in last_event_type.items() if t == "worker_failed"}


class IssueTree(Tree[str]):
    """Hierarchical tree view of issues with worker runs as children."""

    ICON_NODE = ""
    ICON_NODE_EXPANDED = ""

    DEFAULT_CSS = """
    IssueTree {
        width: 1fr;
        min-width: 40;
        max-width: 80;
        padding: 0 1;
    }
    IssueTree #issues-header {
        height: 1;
        color: #666666;
        text-style: bold;
        margin: 1 0 0 1;
    }
    """

    def __init__(
        self,
        config: StateMachineConfig | None = None,
        insights_enabled: bool = False,
    ) -> None:
        super().__init__("", id="issue-tree")
        self.show_root = False
        self.show_guides = False
        self._insights_enabled = insights_enabled
        self._sessions: list[dict[str, Any]] = []
        self._state: State | None = None
        self._tick: int = 0
        self._config = config

    def _issue_label(self, issue: Issue, failed_states: set[str] | None = None) -> Text:
        title = str(issue.fields.get("title", "untitled"))
        debug_paused = getattr(issue, "debug_pending", False)
        label = Text()
        if issue.failure_count > 0 and not issue.worker_active:
            label.append("• ", style="bold red")
            label.append(title)
        elif issue.state == "done":
            label.append("• ", style="bold green")
            label.append(title)
        elif debug_paused:
            # Distinct amber pause indicator + state tag so user sees the step
            # finished and is awaiting their review (not idle).
            label.append("⏸ ", style=f"bold {_COLOR_ACTIVE}")
            label.append(title)
            label.append(f" [{issue.state}]", style=_COLOR_ACTIVE)
            label.append(" paused for review", style=f"italic {_COLOR_ACTIVE}")
        else:
            label.append("• ", style="dim")
            label.append(title)
            label.append(f" [{issue.state}]", style="dim")
        # Progress bar inline after title
        if self._config is not None:
            bar = _progress_bar_text(self._config, issue.visit_counts, issue.state, failed_states or set())
            if bar is not None:
                label.append(" ")
                label.append_text(bar)
        return label

    def update_state(self, state: State, sessions: list[dict[str, Any]]) -> None:
        self._state = state
        self._sessions = sessions
        self._tick += 1

        # Remember cursor position
        cursor_data: str | None = None
        if self.cursor_node and self.cursor_node.data:
            cursor_data = self.cursor_node.data

        self.root.remove_children()

        roots = [(iid, issue) for iid, issue in state.issues.items() if issue.decomposed_from is None]
        for iid, issue in roots:
            self._add_issue_node(self.root, iid, issue, state)

        # Add insights entry if enabled
        if self._insights_enabled:
            insights_label = Text()
            insights_label.append("◆ ", style="bold cyan")
            insights_label.append("Insights", style="bold cyan")
            self.root.add(insights_label, data="insights")

        self.root.expand()

        # Restore cursor, or select first root issue on initial load.
        # Use move_cursor instead of select_node to avoid triggering
        # auto_expand which toggles (collapses) already-expanded nodes.
        if cursor_data:
            self._restore_cursor(cursor_data)
        elif roots:
            first_iid = roots[0][0]
            first_node = self._find_by_data(self.root, f"issue:{first_iid}")
            if first_node:
                self.move_cursor(first_node)

    def _add_issue_node(self, parent_node: TreeNode[str], issue_id: str, issue: Issue, state: State) -> None:
        failed_states = _compute_failed_states(issue)
        node = parent_node.add(self._issue_label(issue, failed_states), data=f"issue:{issue_id}")
        node.expand()

        # Add child issues (decomposed)
        children = [(iid, iss) for iid, iss in state.issues.items() if iss.decomposed_from == issue_id]
        for child_id, child_issue in children:
            self._add_issue_node(node, child_id, child_issue, state)

    def _restore_cursor(self, data: str) -> bool:
        found = self._find_by_data(self.root, data)
        if found:
            self.move_cursor(found)
            return True
        return False

    def _find_by_data(self, node: TreeNode[str], data: str) -> TreeNode[str] | None:
        if node.data == data:
            return node
        for child in node.children:
            found = self._find_by_data(child, data)
            if found:
                return found
        return None

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted[str]) -> None:
        """Auto-activate on highlight (no Enter needed)."""
        if not event.node.data:
            return
        data = event.node.data
        if data.startswith(("progress:", "pending:", "error:")):
            return
        if data.startswith("issue:"):
            self.post_message(IssueSelected(data[6:]))
        elif data == "insights":
            self.post_message(InsightsSelected())

    def refresh_tick(self) -> None:
        """Called by the app timer to advance the spinner."""
        self._tick += 1
