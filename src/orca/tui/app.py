from __future__ import annotations

import time
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Footer

from orca.engine.types import State, StateMachineConfig
from orca.tui.messages import InsightsSelected, IssueSelected, StateUpdated, WorkerRunSelected
from orca.tui.state_reader import StateReader
from orca.tui.widgets.header import OrcaHeader
from orca.tui.widgets.issue_detail import IssueDetail
from orca.tui.widgets.issue_tree import IssueTree
from orca.tui.widgets.terminal_view import TerminalView

_STALE_THRESHOLD = 10.0
_DEADLOCK_THRESHOLD = 30.0


class OrcaApp(App[None]):
    """Orca TUI — interactive viewer for orchestrator runs."""

    THEME = "flexoki"

    CSS = """
    #main-panels {
        height: 1fr;
    }
    #terminal-view {
        display: none;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh_all", "Refresh"),
        Binding("n", "retry_failed", "Retry"),
        Binding("h,left", "focus_tree", "Tree", show=False),
        Binding("l,right", "focus_detail", "Detail", show=False),
        Binding("j", "scroll_detail_down", "Scroll ↓", show=False),
        Binding("k", "scroll_detail_up", "Scroll ↑", show=False),
    ]

    def __init__(
        self,
        run_dir: Path,
        branch_name: str,
        config: StateMachineConfig | None = None,
        insights_enabled: bool = False,
        hot_sessions: set[str] | None = None,
        session_log_paths: dict[str, str] | None = None,
    ) -> None:
        super().__init__()
        self._reader = StateReader(run_dir)
        self._run_dir = run_dir
        self._branch_name = branch_name
        self._config = config
        self._insights_enabled = insights_enabled
        self._state: State | None = None
        # Shared with orchestrator thread
        self._hot_sessions: set[str] = hot_sessions if hot_sessions is not None else set()
        self._session_log_paths: dict[str, str] = session_log_paths if session_log_paths is not None else {}
        self._selected_session_id: str | None = None

    def compose(self) -> ComposeResult:
        yield OrcaHeader(branch_name=self._branch_name, config=self._config)
        with Horizontal(id="main-panels"):
            yield IssueTree(insights_enabled=self._insights_enabled)
            yield IssueDetail()
            yield TerminalView()
        yield Footer()

    def on_mount(self) -> None:
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

    def action_refresh_all(self) -> None:
        """Refresh the content pane."""
        detail = self.query_one(IssueDetail)
        detail.refresh_transcript()

    def action_focus_tree(self) -> None:
        self.query_one(IssueTree).focus()

    def action_focus_detail(self) -> None:
        terminal = self.query_one(TerminalView)
        if str(terminal.styles.display) != "none":
            terminal.focus()
        else:
            self.query_one(IssueDetail).focus()

    def on_state_updated(self, message: StateUpdated) -> None:
        tree = self.query_one(IssueTree)
        tree.update_state(message.state, message.sessions)
        header = self.query_one(OrcaHeader)
        header.update_state(message.state, message.sessions)
        self._update_status()

    def on_issue_selected(self, message: IssueSelected) -> None:
        if self._state:
            self._deselect_session()
            self.query_one(TerminalView).styles.display = "none"
            detail = self.query_one(IssueDetail)
            detail.styles.display = "block"
            detail.show_issue(message.issue_id, self._state)

    def on_worker_run_selected(self, message: WorkerRunSelected) -> None:
        detail = self.query_one(IssueDetail)
        terminal = self.query_one(TerminalView)

        # Mark this session as hot (frequent capture) and deselect previous
        self._deselect_session()
        self._selected_session_id = message.session_id
        self._hot_sessions.add(message.session_id)

        # Find the log file path
        log_path_str = self._session_log_paths.get(message.session_id)
        log_path = Path(log_path_str) if log_path_str else None

        detail.styles.display = "none"
        terminal.styles.display = "block"

        if log_path is not None:
            terminal.show_log_file(log_path, active=message.active)
        else:
            terminal.show_placeholder()

    def on_insights_selected(self, message: InsightsSelected) -> None:
        self._deselect_session()
        self.query_one(TerminalView).styles.display = "none"
        detail = self.query_one(IssueDetail)
        detail.styles.display = "block"
        detail.show_insights(self._run_dir / "insights.md")

    def _deselect_session(self) -> None:
        """Remove the previous session from hot set."""
        if self._selected_session_id is not None:
            self._hot_sessions.discard(self._selected_session_id)
            self._selected_session_id = None

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

    def action_scroll_detail_down(self) -> None:
        """Scroll the detail panel down."""
        terminal = self.query_one(TerminalView)
        if str(terminal.styles.display) != "none":
            terminal.scroll_down()
        else:
            self.query_one(IssueDetail).scroll_down()

    def action_scroll_detail_up(self) -> None:
        """Scroll the detail panel up."""
        terminal = self.query_one(TerminalView)
        if str(terminal.styles.display) != "none":
            terminal.scroll_up()
        else:
            self.query_one(IssueDetail).scroll_up()

    def _find_root_issue(self) -> str | None:
        if self._state is None:
            return None
        for iid, issue in self._state.issues.items():
            if issue.decomposed_from is None:
                return iid
        return None
