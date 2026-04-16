from __future__ import annotations

from collections.abc import Generator

from textual.containers import VerticalScroll
from textual.widget import Widget
from textual.widgets import Markdown

from orca.engine.types import State

_PLACEHOLDER = "*Select an issue or worker run from the tree*"


class IssueDetail(VerticalScroll):
    """Content panel — shows issue title/description or insights."""

    DEFAULT_CSS = """
    IssueDetail {
        width: 1fr;
        padding: 1 2;
    }
    """

    def __init__(self) -> None:
        super().__init__(id="issue-detail")
        self._markdown = Markdown(_PLACEHOLDER)

    def compose(self) -> Generator[Widget, None, None]:
        yield self._markdown

    def show_issue(self, issue_id: str, state: State) -> None:
        issue = state.issues.get(issue_id)
        if issue is None:
            self._markdown.update(_PLACEHOLDER)
            return
        title = issue.fields.get("title", "Untitled")
        description = issue.fields.get("description", "")
        content = f"# {title}\n\n{description}"

        # Show failure info if retries exhausted
        if issue.failure_count > 0 and not issue.worker_active:
            last_error = self._last_failure_error(issue)
            content += f"\n\n---\n\n**Worker failed {issue.failure_count} time(s) — retries exhausted**"
            if last_error:
                content += f"\n\n```\n{last_error}\n```"

        self._markdown.update(content)

    @staticmethod
    def _last_failure_error(issue: object) -> str:
        """Extract the error message from the last worker_failed event log entry."""
        from orca.engine.types import Issue

        if not isinstance(issue, Issue):
            return ""
        for entry in reversed(issue.event_log):
            if entry.type == "worker_failed":
                return str(entry.data.get("error", ""))
        return ""

    def show_issue_text(self, title: str, content: str) -> None:
        """Display arbitrary markdown content."""
        self._markdown.update(content)

    def clear(self) -> None:
        self._markdown.update(_PLACEHOLDER)
