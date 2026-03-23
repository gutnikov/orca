from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from rich.text import Text
from textual.widgets import Tree
from textual.widgets.tree import TreeNode

from orca.engine.types import Issue, State
from orca.tui.messages import IssueSelected, WorkerRunSelected

# Braille dot spinner frames
_SPINNER = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


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

    def __init__(self) -> None:
        super().__init__("", id="issue-tree")
        self.show_root = False
        self.show_guides = False
        self._sessions: list[dict[str, Any]] = []
        self._tick: int = 0

    def _issue_label(self, issue: Issue) -> Text:
        title = str(issue.fields.get("title", "untitled"))
        label = Text()
        label.append(title)
        # Detect retries exhausted: failed, not active, not terminal
        if issue.failure_count > 0 and not issue.worker_active:
            label.append(f" [{issue.state}]", style="bold red")
            label.append(" FAILED", style="bold red")
        elif issue.state == "done":
            label.append(f" [{issue.state}]", style="bold green")
        else:
            label.append(f" [{issue.state}]", style="dim")
        return label

    def _worker_run_label(self, state_name: str, session: dict[str, Any]) -> Text:
        label = Text()
        is_active = session.get("completed_at") is None
        if is_active:
            frame = _SPINNER[self._tick % len(_SPINNER)]
            elapsed = _elapsed_str(str(session.get("started_at", "")))
            label.append(f"{frame} ", style="bold yellow")
            label.append(state_name)
            if elapsed:
                label.append(f" {elapsed}", style="dim")
        else:
            label.append("  ", style="green")
            label.append(state_name, style="dim")
        return label

    def update_state(self, state: State, sessions: list[dict[str, Any]]) -> None:
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

        self.root.expand()

        # Restore cursor, or select first root issue on initial load
        # Use move_cursor instead of select_node to avoid triggering
        # auto_expand which toggles (collapses) already-expanded nodes.
        if cursor_data:
            self._restore_cursor(cursor_data)
        elif roots and self.root.children:
            self.move_cursor(self.root.children[0])
            first_id = roots[0][0]
            self.post_message(IssueSelected(first_id))

    def _add_issue_node(self, parent_node: TreeNode[str], issue_id: str, issue: Issue, state: State) -> None:
        node = parent_node.add(self._issue_label(issue), data=f"issue:{issue_id}")
        node.expand()

        # Add child issues
        children = [(iid, iss) for iid, iss in state.issues.items() if iss.decomposed_from == issue_id]
        for child_id, child_issue in children:
            self._add_issue_node(node, child_id, child_issue, state)

        # Add worker run leaves for this issue (only if no child issues — leaf issue)
        if not children:
            issue_sessions = [s for s in self._sessions if s.get("issue_id") == issue_id]
            # Show only the last few sessions to avoid flooding the tree
            if len(issue_sessions) > 5:
                issue_sessions = issue_sessions[-5:]
            for session in issue_sessions:
                run_label = self._worker_run_label(str(session.get("state", "unknown")), session)
                session_id = str(session.get("session_id", ""))
                node.add_leaf(run_label, data=f"session:{session_id}")

    def _restore_cursor(self, data: str) -> None:
        found = self._find_by_data(self.root, data)
        if found:
            self.move_cursor(found)

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
        if data.startswith("issue:"):
            self.post_message(IssueSelected(data[6:]))
        elif data.startswith("session:"):
            session_id = data[8:]
            active = any(s.get("session_id") == session_id and s.get("completed_at") is None for s in self._sessions)
            self.post_message(WorkerRunSelected(session_id, active=active))

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
