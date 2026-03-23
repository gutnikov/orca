from __future__ import annotations

from collections.abc import Generator

from textual.containers import VerticalScroll
from textual.widget import Widget
from textual.widgets import Markdown

from orca.engine.types import State

_PLACEHOLDER = "*Select an issue from the tree*"


class IssueDetail(VerticalScroll):
    """Center panel — renders the selected issue's fields as markdown."""

    DEFAULT_CSS = """
    IssueDetail {
        width: 4fr;
        border-right: solid $surface-lighten-2;
        padding: 1;
    }
    """

    def __init__(self) -> None:
        super().__init__(id="issue-detail")
        self._markdown = Markdown(_PLACEHOLDER)
        self._current_issue_id: str | None = None

    def compose(self) -> Generator[Widget, None, None]:
        yield self._markdown

    def show_issue(self, issue_id: str, state: State) -> None:
        issue = state.issues.get(issue_id)
        if issue is None:
            self._current_issue_id = None
            self._markdown.update(_PLACEHOLDER)
            return
        self._current_issue_id = issue_id
        title = issue.fields.get("title", "Untitled")
        description = issue.fields.get("description", "")
        content = f"# {title}\n\n{description}"
        self._markdown.update(content)

    def clear(self) -> None:
        self._current_issue_id = None
        self._markdown.update(_PLACEHOLDER)
