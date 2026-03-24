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
        # For .md-based transcript viewing (completed sessions)
        self._current_transcript_path: Path | None = None
        self._transcript_mtime: float = 0.0
        # For live JSONL-based rendering (active sessions)
        self._jsonl_path: Path | None = None
        self._jsonl_offset: int = 0
        self._jsonl_last_type: str = ""
        self._rendered_md: str = ""

    def compose(self) -> Generator[Widget, None, None]:
        yield self._markdown

    def refresh_transcript(self) -> None:
        """Re-read transcript source if it has changed. Handles both JSONL (active) and .md (completed)."""
        if self._jsonl_path is not None:
            self._refresh_jsonl()
        elif self._current_transcript_path is not None:
            self._refresh_md()

    def _refresh_jsonl(self) -> None:
        """Incrementally render new JSONL entries for live sessions."""
        if self._jsonl_path is None or not self._jsonl_path.exists():
            return
        from orca.orchestrator.transcript import render_incremental

        md, new_offset, new_last_type = render_incremental(self._jsonl_path, self._jsonl_offset, self._jsonl_last_type)
        if not md:
            return
        self._jsonl_offset = new_offset
        self._jsonl_last_type = new_last_type
        if self._rendered_md:
            self._rendered_md += "\n\n" + md
        else:
            self._rendered_md = md
        self._markdown.update(self._rendered_md)
        if self.max_scroll_y - self.scroll_y < 5:
            self.scroll_end(animate=False)

    def _refresh_md(self) -> None:
        """Re-read .md file if mtime changed (for completed sessions)."""
        if self._current_transcript_path is None or not self._current_transcript_path.exists():
            return
        mtime = self._current_transcript_path.stat().st_mtime
        if mtime == self._transcript_mtime:
            return
        self._transcript_mtime = mtime
        content = self._current_transcript_path.read_text()
        self._markdown.update(content)
        if self.max_scroll_y - self.scroll_y < 5:
            self.scroll_end(animate=False)

    def stop_auto_refresh(self) -> None:
        """Clear all transcript tracking state."""
        self._current_transcript_path = None
        self._transcript_mtime = 0.0
        self._jsonl_path = None
        self._jsonl_offset = 0
        self._jsonl_last_type = ""
        self._rendered_md = ""

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

    def show_transcript(
        self, session_id: str, *, active: bool = False, worktree_path: str = "", claude_session_id: str = ""
    ) -> None:
        self.stop_auto_refresh()

        # Try pre-rendered .md first
        if self._transcripts_dir is not None:
            transcript_path = self._transcripts_dir / f"{session_id}.md"
            if transcript_path.exists():
                self._current_transcript_path = transcript_path
                self._transcript_mtime = transcript_path.stat().st_mtime
                content = transcript_path.read_text()
                self._markdown.update(content)
                if active:
                    self._jsonl_path = (
                        self._find_jsonl(claude_session_id or session_id, worktree_path) if worktree_path else None
                    )
                return

        # No .md — try JSONL directly
        if worktree_path:
            jsonl = self._find_jsonl(claude_session_id or session_id, worktree_path)
            if jsonl is not None:
                self._jsonl_path = jsonl
                self._refresh_jsonl()
                if self._rendered_md:
                    return

        self._markdown.update(f"*Waiting for transcript for session {session_id[:8]}...*")

    @staticmethod
    def _find_jsonl(session_id: str, worktree_path: str) -> Path | None:
        """Locate the JSONL transcript file for a session."""
        claude_projects_root = Path.home() / ".claude" / "projects"
        if not claude_projects_root.exists():
            return None

        project_hash = worktree_path.replace("/", "-").replace(".", "-")
        project_dir = claude_projects_root / project_hash
        candidate = project_dir / f"{session_id}.jsonl"
        if candidate.exists():
            return candidate

        # Fallback: most recently modified JSONL (for active sessions before
        # the real Claude session ID is known)
        if project_dir.exists():
            jsonl_files = sorted(project_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
            if jsonl_files:
                return jsonl_files[0]

        return None

    def show_insights(self, insights_path: Path) -> None:
        """Display the contents of insights.md."""
        self.stop_auto_refresh()
        if not insights_path.exists():
            self._markdown.update("*No insights generated yet*")
            return
        self._current_transcript_path = insights_path
        self._transcript_mtime = insights_path.stat().st_mtime
        content = insights_path.read_text()
        self._markdown.update(content or "*Insights file is empty -- waiting for first analysis*")

    def clear(self) -> None:
        self.stop_auto_refresh()
        self._markdown.update(_PLACEHOLDER)
