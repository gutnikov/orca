from __future__ import annotations

from collections.abc import Generator

from textual.containers import VerticalScroll
from textual.widget import Widget
from textual.widgets import Markdown

from orca.engine.types import State

_PLACEHOLDER = "*Select an issue or worker run from the tree*"


class IssueDetail(VerticalScroll):
    """Content panel — shows issue title/description."""

    DEFAULT_CSS = """
    IssueDetail {
        width: 1fr;
        padding: 1 2;
    }
    """

    def __init__(self) -> None:
        super().__init__(id="issue-detail")
        self._markdown = Markdown(_PLACEHOLDER)
        # Wired by app.py — used to construct the debug review URL
        self._run_id: str = ""
        self._browser_port: int | None = None

    def compose(self) -> Generator[Widget, None, None]:
        yield self._markdown

    def set_run_context(self, run_id: str, browser_port: int | None) -> None:
        """Inject the run id + browser port so debug-review URLs can be rendered."""
        self._run_id = run_id
        self._browser_port = browser_port

    def show_issue(self, issue_id: str, state: State) -> None:
        issue = state.issues.get(issue_id)
        if issue is None:
            self._markdown.update(_PLACEHOLDER)
            return
        title = issue.fields.get("title", "Untitled")
        description = issue.fields.get("description", "")

        parts: list[str] = []

        # Debug-review pause banner — surfaced at the TOP so it's the first
        # thing the user sees when selecting a paused issue.
        if getattr(issue, "debug_pending", False):
            parts.append(self._debug_review_banner(issue_id, issue.state))

        parts.append(f"# {title}\n\n{description}")

        # Show failure info if retries exhausted
        if issue.failure_count > 0 and not issue.worker_active:
            last_error = self._last_failure_error(issue)
            parts.append(f"---\n\n**Worker failed {issue.failure_count} time(s) — retries exhausted**")
            if last_error:
                parts.append(f"```\n{last_error}\n```")

        self._markdown.update("\n\n".join(parts))

    def _debug_review_banner(self, issue_id: str, state_name: str) -> str:
        """Markdown callout shown above the issue body when paused for review."""
        if self._browser_port is not None and self._run_id:
            url = f"http://localhost:{self._browser_port}/debug/{self._run_id}/{issue_id}"
            url_block = f"`{url}`"
        else:
            url_block = "*(browser-port unavailable — start the daemon to surface a review URL)*"
        return (
            "> ⏸ **Paused for debug review**\n"
            f">\n"
            f"> State `{state_name}` finished. Pick an action in the browser:\n"
            f">\n"
            f"> {url_block}\n"
            f">\n"
            "> **Modify prompt + config & restart** · **Restart without changes** "
            "· **Accept & continue** · **Stop run**"
        )

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
