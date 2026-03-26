from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rich.text import Text
from textual.widgets import Tree
from textual.widgets.tree import TreeNode

from orca.engine.types import EventLogEntry, Issue, State, StateMachineConfig
from orca.tui.messages import InsightsSelected, IssueSelected, WorkerRunSelected

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
    non_terminal = [name for name, sdef in config.states.items() if not sdef.terminal]
    if not non_terminal:
        return None
    bar = Text()
    for name in non_terminal:
        if name in failed_states:
            bar.append("█", style=_COLOR_FAILED)
        elif name == current_state:
            bar.append("█", style=_COLOR_ACTIVE)
        elif name in visit_counts:
            bar.append("█", style=_COLOR_DONE)
        else:
            bar.append("█", style=_COLOR_PENDING)
    return bar


def _pending_steps(config: StateMachineConfig, visit_counts: dict[str, int]) -> list[str]:
    """Return non-terminal states not yet visited."""
    return [name for name, sdef in config.states.items() if not sdef.terminal and name not in visit_counts]


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
        padding: 1;
    }
    """

    def __init__(
        self,
        insights_enabled: bool = False,
        config: StateMachineConfig | None = None,
        run_dir: Path | None = None,
    ) -> None:
        super().__init__("", id="issue-tree")
        self.show_root = False
        self.show_guides = False
        self._sessions: list[dict[str, Any]] = []
        self._state: State | None = None
        self._tick: int = 0
        self._insights_enabled = insights_enabled
        self._config = config
        self._run_dir = run_dir

    def _read_insights(self) -> list[dict[str, Any]]:
        if self._run_dir is None:
            return []
        p = self._run_dir / "insights.json"
        if not p.exists():
            return []
        try:
            data: list[dict[str, Any]] = json.loads(p.read_text())
            return data
        except (json.JSONDecodeError, OSError):
            return []

    def _issue_label(self, issue: Issue, failed_states: set[str] | None = None) -> Text:
        title = str(issue.fields.get("title", "untitled"))
        label = Text()
        if issue.failure_count > 0 and not issue.worker_active:
            label.append("• ", style="bold red")
            label.append(title)
        elif issue.state == "done":
            label.append("• ", style="bold green")
            label.append(title)
        else:
            label.append("• ", style="dim")
            label.append(title)
            label.append(f" [{issue.state}]", style="dim")
        # Inline progress bar
        if self._config is not None:
            bar = _progress_bar_text(self._config, issue.visit_counts, issue.state, failed_states or set())
            if bar is not None:
                label.append(" ")
                label.append_text(bar)
        return label

    def _worker_run_label(
        self,
        state_name: str,
        session: dict[str, Any],
        *,
        result_outcomes: dict[str, str] | None = None,
        failure_errors: dict[str, str] | None = None,
        visit_counts: dict[str, int] | None = None,
        is_last_for_state: bool = True,
        failed_states: set[str] | None = None,
    ) -> Text:
        label = Text()
        is_active = session.get("completed_at") is None
        # A completed session is failed only if it's the LAST session for this
        # state AND the state is in the failed set (last worker event was failure).
        is_failed = not is_active and is_last_for_state and failed_states is not None and state_name in failed_states

        if is_active:
            frame = _SPINNER[self._tick % len(_SPINNER)]
            elapsed = _elapsed_str(str(session.get("started_at", "")))
            label.append(f"{frame} ", style="bold yellow")
            label.append(state_name)
            if elapsed:
                label.append(f" {elapsed}", style="dim")
            # Visit count badge
            if visit_counts and visit_counts.get(state_name, 0) > 1:
                label.append(f"  visit {visit_counts[state_name]}", style="dim")
        elif is_failed:
            label.append("✗ ", style="bold red")
            label.append(state_name)
            duration = _duration_str(str(session.get("started_at", "")), str(session.get("completed_at", "")))
            if duration:
                label.append(f" — {duration}", style="dim")
            label.append("  failed", style="bold red")
        else:
            label.append("✓ ", style="green")
            label.append(state_name)
            duration = _duration_str(str(session.get("started_at", "")), str(session.get("completed_at", "")))
            if duration:
                label.append(f" — {duration}", style="dim")
            # Result outcome badge
            if result_outcomes and state_name in result_outcomes:
                outcome = result_outcomes[state_name]
                label.append(f"  {outcome}", style="bold green")
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

        # Build issue tree without root "Issues" node
        roots = [(iid, issue) for iid, issue in state.issues.items() if issue.decomposed_from is None]
        for iid, issue in roots:
            self._add_issue_node(self.root, iid, issue, state)

        # Add Insights parent node with children when insights are enabled
        if self._insights_enabled:
            insights_label = Text()
            insights_label.append("◆ ", style="bold cyan")
            insights_label.append("Insights", style="cyan")
            insights_node = self.root.add(insights_label, data="insights")
            insights_node.expand()
            for i, entry in enumerate(self._read_insights()):
                sev = entry.get("severity", "info")
                title = str(entry.get("title", "Untitled"))[:60]
                lbl = Text()
                if sev == "error":
                    lbl.append("● ", style="bold red")
                elif sev == "warning":
                    lbl.append("⚠ ", style="bold yellow")
                elif sev == "summary":
                    lbl.append("◆ ", style="bold cyan")
                else:
                    lbl.append("ℹ ", style="dim")
                lbl.append(title)
                insights_node.add_leaf(lbl, data=f"insight:{i}")

        self.root.expand()

        # Restore cursor, or select first root issue on initial load.
        # Use move_cursor instead of select_node to avoid triggering
        # auto_expand which toggles (collapses) already-expanded nodes.
        if cursor_data:
            restored = self._restore_cursor(cursor_data)
            if not restored and cursor_data.startswith("session:"):
                # Session leaf may have been truncated from the visible list.
                # Try to find the parent issue node instead.
                # Session nodes are children of issue nodes, so search for
                # the issue that owns this session.
                session_id = cursor_data[8:]
                for s in self._sessions:
                    if s.get("session_id") == session_id:
                        issue_data = f"issue:{s.get('issue_id', '')}"
                        self._restore_cursor(issue_data)
                        break

    def _add_issue_node(self, parent_node: TreeNode[str], issue_id: str, issue: Issue, state: State) -> None:
        # Compute enhanced data for this issue
        failed_states = _compute_failed_states(issue)
        node = parent_node.add(self._issue_label(issue, failed_states), data=f"issue:{issue_id}")
        node.expand()

        # Add child issues
        children = [(iid, iss) for iid, iss in state.issues.items() if iss.decomposed_from == issue_id]
        for child_id, child_issue in children:
            self._add_issue_node(node, child_id, child_issue, state)

        # Add worker run leaves for this issue (only if no child issues — leaf issue)
        if not children:
            result_outcomes = _extract_result_outcomes(issue.event_log)
            failure_errors = _extract_failure_errors(issue.event_log)

            # Worker session runs
            issue_sessions = [s for s in self._sessions if s.get("issue_id") == issue_id]
            # Show only the last few sessions to avoid flooding the tree
            if len(issue_sessions) > 5:
                issue_sessions = issue_sessions[-5:]
            # Track last completed (non-active) session per state for failure detection
            last_completed_per_state: dict[str, int] = {}
            for idx, s in enumerate(issue_sessions):
                if s.get("completed_at") is not None:
                    last_completed_per_state[str(s.get("state", ""))] = idx

            for idx, session in enumerate(issue_sessions):
                sname = str(session.get("state", "unknown"))
                is_last_completed = last_completed_per_state.get(sname) == idx
                run_label = self._worker_run_label(
                    sname,
                    session,
                    result_outcomes=result_outcomes,
                    failure_errors=failure_errors,
                    visit_counts=issue.visit_counts,
                    is_last_for_state=is_last_completed,
                    failed_states=failed_states,
                )
                session_id = str(session.get("session_id", ""))
                node.add_leaf(run_label, data=f"session:{session_id}")

                # Add inline failure error below the last completed session for a failed state
                if is_last_completed and sname in failed_states and failure_errors and sname in failure_errors:
                    err_label = Text()
                    err_label.append(f"  {failure_errors[sname]}", style="dim red")
                    node.add_leaf(err_label, data=f"error:{session_id}")

            # Active current state (shown when no session exists for it yet)
            if self._config is not None:
                current_state_def = self._config.states.get(issue.state)
                has_session_for_current = any(str(s.get("state", "")) == issue.state for s in issue_sessions)
                if (
                    current_state_def is not None
                    and not current_state_def.terminal
                    and current_state_def.worker is not None
                    and not has_session_for_current
                ):
                    active_label = Text()
                    active_label.append(f"○ {issue.state}", style="bold")
                    node.add_leaf(active_label, data=f"pending:{issue.state}")

            # Pending steps (dimmed, not-yet-visited states)
            if self._config is not None:
                pending = _pending_steps(self._config, issue.visit_counts)
                for step_name in pending:
                    # Skip the current state (it's shown above as active)
                    if step_name == issue.state:
                        continue
                    pending_label = Text()
                    pending_label.append(f"○ {step_name}", style="dim")
                    node.add_leaf(pending_label, data=f"pending:{step_name}")

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
        elif data.startswith("session:"):
            session_id = data[8:]
            session = next((s for s in self._sessions if s.get("session_id") == session_id), None)
            active = session is not None and session.get("completed_at") is None
            worktree_path = str(session.get("worktree_path", "")) if session else ""
            issue_id = str(session.get("issue_id", "")) if session else ""
            self.post_message(
                WorkerRunSelected(
                    session_id,
                    active=active,
                    worktree_path=worktree_path,
                    issue_id=issue_id,
                )
            )
        elif data == "insights":
            self.post_message(InsightsSelected())
        elif data.startswith("insight:"):
            idx = int(data[8:])
            entries = self._read_insights()
            if 0 <= idx < len(entries):
                e = entries[idx]
                from orca.tui.messages import InsightEntrySelected

                self.post_message(
                    InsightEntrySelected(
                        title=str(e.get("title", "")),
                        detail=str(e.get("detail", "")),
                        remediation=str(e.get("remediation", "")),
                        severity=str(e.get("severity", "info")),
                    )
                )

    def refresh_tick(self) -> None:
        """Called by the app timer to advance the spinner without full rebuild."""
        self._tick += 1
        # Update labels for active worker runs in-place
        self._update_active_labels(self.root)

    def _update_active_labels(self, node: TreeNode[str]) -> None:
        if node.data and node.data.startswith("session:"):
            session_id = node.data[8:]
            for session in self._sessions:
                if session.get("session_id") == session_id and session.get("completed_at") is None:
                    node.set_label(self._worker_run_label(str(session.get("state", "unknown")), session))
                    break
        for child in node.children:
            self._update_active_labels(child)
