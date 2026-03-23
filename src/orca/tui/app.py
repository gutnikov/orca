from __future__ import annotations

import time
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Footer, Header

from orca.engine.types import State, StateMachineConfig
from orca.tui.messages import IssueSelected, StateUpdated
from orca.tui.state_reader import StateReader
from orca.tui.widgets.issue_detail import IssueDetail
from orca.tui.widgets.issue_tree import IssueTree
from orca.tui.widgets.status_history import StatusHistory

_STALE_THRESHOLD = 10.0
_DEADLOCK_THRESHOLD = 30.0


class OrcaApp(App[None]):
    """Orca TUI — interactive viewer for orchestrator runs."""

    CSS = """
    #main-panels {
        height: 1fr;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "force_refresh", "Refresh"),
    ]

    def __init__(
        self,
        run_dir: Path,
        branch_name: str,
        config: StateMachineConfig | None = None,
    ) -> None:
        super().__init__()
        self._reader = StateReader(run_dir)
        self._branch_name = branch_name
        self._config = config
        self._state: State | None = None
        self._selected_issue_id: str | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main-panels"):
            yield IssueTree()
            yield IssueDetail()
            yield StatusHistory()
        yield Footer()

    def on_mount(self) -> None:
        self.title = f"orca watch — {self._branch_name}"
        self._poll_state()
        self.set_interval(1.5, self._poll_state)

    def _poll_state(self) -> None:
        state = self._reader.read()
        if state is not None:
            self._state = state
            self.post_message(StateUpdated(state))

    def action_force_refresh(self) -> None:
        self._reader.reset()
        self._poll_state()

    def on_state_updated(self, message: StateUpdated) -> None:
        tree = self.query_one(IssueTree)
        tree.update_state(message.state)
        if self._selected_issue_id:
            detail = self.query_one(IssueDetail)
            detail.show_issue(self._selected_issue_id, message.state)
            history = self.query_one(StatusHistory)
            history.show_issue(self._selected_issue_id, message.state)
        self._update_status()

    def on_issue_selected(self, message: IssueSelected) -> None:
        self._selected_issue_id = message.issue_id
        if self._state:
            detail = self.query_one(IssueDetail)
            detail.show_issue(message.issue_id, self._state)
            history = self.query_one(StatusHistory)
            history.show_issue(message.issue_id, self._state)

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

    def _find_root_issue(self) -> str | None:
        if self._state is None:
            return None
        for iid, issue in self._state.issues.items():
            if issue.decomposed_from is None:
                return iid
        return None
