from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

from textual.containers import VerticalScroll
from textual.widget import Widget
from textual.widgets import Markdown

from orca.engine.types import State

_PLACEHOLDER = "*Select an issue or worker run from the tree*"


class IssueDetail(VerticalScroll):
    """Content panel — shows issue title/description or worker run transcript."""

    DEFAULT_CSS = """
    IssueDetail {
        width: 1fr;
        padding: 1;
    }
    """

    def __init__(self, transcripts_dir: Path | None = None) -> None:
        super().__init__(id="issue-detail")
        self._markdown = Markdown(_PLACEHOLDER)
        self._transcripts_dir = transcripts_dir
        self._current_transcript_path: Path | None = None
        self._transcript_mtime: float = 0.0

    def compose(self) -> Generator[Widget, None, None]:
        yield self._markdown

    def refresh_transcript(self) -> None:
        """Re-read the current transcript .md file if it has changed."""
        if self._current_transcript_path is None:
            return
        if not self._current_transcript_path.exists():
            return
        mtime = self._current_transcript_path.stat().st_mtime
        if mtime == self._transcript_mtime:
            return
        self._transcript_mtime = mtime
        content = self._current_transcript_path.read_text()
        self._markdown.update(content)
        # Auto-scroll to bottom if user is near the bottom
        if self.max_scroll_y - self.scroll_y < 5:
            self.scroll_end(animate=False)

    def stop_auto_refresh(self) -> None:
        """Clear transcript tracking state."""
        self._current_transcript_path = None
        self._transcript_mtime = 0.0

    def show_issue(self, issue_id: str, state: State) -> None:
        self.stop_auto_refresh()
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

    def show_transcript(self, session_id: str) -> None:
        self.stop_auto_refresh()
        if self._transcripts_dir is None:
            self._markdown.update("*Transcripts directory not configured*")
            return
        transcript_path = self._transcripts_dir / f"{session_id}.md"
        self._current_transcript_path = transcript_path
        if transcript_path.exists():
            self._transcript_mtime = transcript_path.stat().st_mtime
            content = transcript_path.read_text()
            self._markdown.update(content)
        else:
            self._markdown.update(f"*Transcript not yet available for session {session_id[:8]}...*")

    def clear(self) -> None:
        self.stop_auto_refresh()
        self._markdown.update(_PLACEHOLDER)
