from __future__ import annotations

import time
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Footer, Header

from orca.engine.types import State, StateMachineConfig
from orca.tui.messages import InsightsSelected, IssueSelected, StateUpdated, WorkerRunSelected
from orca.tui.state_reader import StateReader
from orca.tui.widgets.issue_detail import IssueDetail
from orca.tui.widgets.issue_tree import IssueTree

_STALE_THRESHOLD = 10.0
_DEADLOCK_THRESHOLD = 30.0


class OrcaApp(App[None]):
    """Orca TUI — interactive viewer for orchestrator runs."""

    THEME = "gruvbox"

    CSS = """
    #main-panels {
        height: 1fr;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "force_refresh", "Refresh"),
        Binding("u", "update_transcript", "Update"),
        Binding("n", "retry_failed", "Retry"),
    ]

    def __init__(
        self,
        run_dir: Path,
        branch_name: str,
        config: StateMachineConfig | None = None,
    ) -> None:
        super().__init__()
        self._reader = StateReader(run_dir)
        self._run_dir = run_dir
        self._branch_name = branch_name
        self._config = config
        self._state: State | None = None
        # run_dir is .orca/runs/{branch}, so repo_root is 3 levels up
        repo_root = run_dir.parent.parent.parent
        self._transcripts_dir = repo_root / ".orca" / "transcripts"

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main-panels"):
            yield IssueTree()
            yield IssueDetail(transcripts_dir=self._transcripts_dir)
        yield Footer()

    def on_mount(self) -> None:
        self.title = f"orca watch — {self._branch_name}"
        self._poll_state()
        self.set_interval(1.5, self._poll_state)
        self.set_interval(0.15, self._tick_spinners)

    def _poll_state(self) -> None:
        result = self._reader.read()
        if result is not None:
            state, sessions = result
            self._state = state
            self.post_message(StateUpdated(state, sessions))

    def _tick_spinners(self) -> None:
        tree = self.query_one(IssueTree)
        tree.refresh_tick()

    def action_force_refresh(self) -> None:
        self._reader.reset()
        self._poll_state()

    def on_state_updated(self, message: StateUpdated) -> None:
        tree = self.query_one(IssueTree)
        tree.update_state(message.state, message.sessions)
        self._update_status()

    def on_issue_selected(self, message: IssueSelected) -> None:
        if self._state:
            detail = self.query_one(IssueDetail)
            detail.show_issue(message.issue_id, self._state)

    def on_worker_run_selected(self, message: WorkerRunSelected) -> None:
        detail = self.query_one(IssueDetail)
        detail.show_transcript(message.session_id, active=message.active, worktree_path=message.worktree_path)

    def on_insights_selected(self, message: InsightsSelected) -> None:
        detail = self.query_one(IssueDetail)
        insights_path = self._run_dir / "insights.md"
        detail.show_insights(insights_path)

    def action_update_transcript(self) -> None:
        """Manually refresh the transcript panel."""
        detail = self.query_one(IssueDetail)
        detail.refresh_transcript()

    def _update_status(self) -> None:
        if self._state is None:
            self.sub_title = "waiting for state..."
            return
        root_id = self._find_root_issue()
        if root_id and root_id in self._state.issues:
            root = self._state.issues[root_id]
            if self._config and root.state in self._config.states and self._config.states[root.state].terminal:
                self.sub_title = "completed"
                return
        elapsed = time.time() - self._reader.last_mtime if self._reader.last_mtime > 0 else 0
        if elapsed < _STALE_THRESHOLD:
            self.sub_title = "running"
        elif elapsed < _DEADLOCK_THRESHOLD:
            self.sub_title = "running (stale)"
        else:
            self.sub_title = "idle"

    def action_retry_failed(self) -> None:
        """Retry the currently highlighted failed issue."""
        if self._state is None:
            return
        tree = self.query_one(IssueTree)
        node = tree.cursor_node
        if node is None or node.data is None or not node.data.startswith("issue:"):
            self.notify("Select a failed issue to retry", severity="warning")
            return
        issue_id = node.data[6:]
        issue = self._state.issues.get(issue_id)
        if issue is None or issue.failure_count == 0 or issue.worker_active:
            self.notify("Issue is not in a failed state", severity="warning")
            return
        retry_dir = self._run_dir / "retry"
        retry_dir.mkdir(parents=True, exist_ok=True)
        (retry_dir / issue_id).touch()
        self.notify(f"Retry requested for {issue_id[:8]}...")

    def _find_root_issue(self) -> str | None:
        if self._state is None:
            return None
        for iid, issue in self._state.issues.items():
            if issue.decomposed_from is None:
                return iid
        return None
