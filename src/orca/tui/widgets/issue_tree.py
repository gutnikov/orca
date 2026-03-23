from __future__ import annotations

from rich.text import Text
from textual.widgets import Tree
from textual.widgets.tree import TreeNode

from orca.engine.types import Issue, State
from orca.tui.messages import IssueSelected


class IssueTree(Tree[str]):
    """Hierarchical tree view of orchestrator issues."""

    DEFAULT_CSS = """
    IssueTree {
        width: 3fr;
        border-right: solid $surface-lighten-2;
        padding: 1;
    }
    """

    def __init__(self) -> None:
        super().__init__("Issues", id="issue-tree")
        self._issue_ids: set[str] = set()

    def _make_label(self, issue: Issue) -> Text:
        title = str(issue.fields.get("title", "untitled"))
        spinner = " ⟳" if issue.worker_active else ""
        label = Text()
        label.append(title)
        label.append(f" [{issue.state}]{spinner}")
        return label

    def update_state(self, state: State) -> None:
        cursor_issue_id: str | None = None
        if self.cursor_node and self.cursor_node.data:
            cursor_issue_id = self.cursor_node.data
        self.root.remove_children()
        self._issue_ids.clear()
        roots = {iid: issue for iid, issue in state.issues.items() if issue.decomposed_from is None}
        for iid, issue in roots.items():
            node = self.root.add(self._make_label(issue), data=iid)
            self._issue_ids.add(iid)
            self._populate_children(node, iid, state)
            node.expand()
        self.root.expand()
        if cursor_issue_id:
            self._select_node(cursor_issue_id)

    def _populate_children(self, parent_node: TreeNode[str], parent_id: str, state: State) -> None:
        children = {iid: issue for iid, issue in state.issues.items() if issue.decomposed_from == parent_id}
        for iid, issue in children.items():
            node = parent_node.add(self._make_label(issue), data=iid)
            self._issue_ids.add(iid)
            self._populate_children(node, iid, state)
            node.expand()

    def _select_node(self, issue_id: str) -> None:
        for node in self.root.children:
            found = self._find_node(node, issue_id)
            if found:
                self.select_node(found)
                return

    def _find_node(self, node: TreeNode[str], issue_id: str) -> TreeNode[str] | None:
        if node.data == issue_id:
            return node
        for child in node.children:
            found = self._find_node(child, issue_id)
            if found:
                return found
        return None

    def on_tree_node_selected(self, event: Tree.NodeSelected[str]) -> None:
        if event.node.data:
            self.post_message(IssueSelected(event.node.data))
