from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer

from orca.engine.types import State, StateMachineConfig
from orca.tui.messages import (
    InsightEntrySelected,
    InsightsSelected,
    IssueSelected,
    PhaseSelected,
    StateUpdated,
    WorkerRunSelected,
)
from orca.tui.state_reader import StateReader
from orca.tui.widgets.header import OrcaHeader
from orca.tui.widgets.insights_modal import InsightsModal
from orca.tui.widgets.issue_detail import IssueDetail
from orca.tui.widgets.issue_tree import IssueTree
from orca.tui.widgets.phases_panel import PhasesPanel
from orca.tui.widgets.terminal_view import TerminalView

_STALE_THRESHOLD = 10.0
_DEADLOCK_THRESHOLD = 30.0


class OrcaApp(App[None]):
    """Orca TUI — interactive viewer for orchestrator runs."""

    _daemon_sock: Path
    _daemon_mode: bool

    THEME = "flexoki"

    CSS = """
    Screen {
        padding: 0;
    }
    #main-panels {
        height: 1fr;
    }
    #left-column {
        width: 1fr;
        min-width: 30;
        max-width: 60;
        border-right: solid #333333;
    }
    #terminal-view {
        display: none;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("n", "retry_failed", "Retry", show=False),
        Binding("h,left", "focus_tree", "Tree", show=False),
        Binding("l,right", "focus_detail", "Detail", show=False),
        Binding("j", "scroll_detail_down", "Scroll ↓", show=False),
        Binding("k", "scroll_detail_up", "Scroll ↑", show=False),
        Binding("t", "toggle_tab", "Toggle Tab", show=False),
        Binding("i", "toggle_insights", "Insights", show=False),
        Binding("escape", "close_modal", "Close", show=False),
    ]

    def __init__(
        self,
        run_dir: Path,
        branch_name: str,
        config: StateMachineConfig | None = None,
        insights_enabled: bool = False,
        hot_sessions: set[str] | None = None,
        session_log_paths: dict[str, str] | None = None,
        insights_state: dict[str, str] | None = None,
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
        self._insights_state: dict[str, str] = insights_state if insights_state is not None else {}
        self._selected_session_id: str | None = None
        self._sessions: list[dict[str, object]] = []

    @classmethod
    def from_daemon(cls, sock_path: Path) -> OrcaApp:
        """Create an OrcaApp that connects to the daemon."""
        # This is a stub for the first iteration.
        # Full implementation (run list screen, daemon polling) comes later.
        app = cls.__new__(cls)
        app._daemon_sock = sock_path
        app._daemon_mode = True
        return app

    @property
    def _insights_tracking_id(self) -> str:
        return self._insights_state.get("tracking_id", "")

    def compose(self) -> ComposeResult:
        yield OrcaHeader(branch_name=self._branch_name, config=self._config)
        with Horizontal(id="main-panels"):
            with Vertical(id="left-column"):
                yield IssueTree(config=self._config, insights_enabled=self._insights_enabled)
                yield PhasesPanel()
            yield IssueDetail()
            yield TerminalView()
        yield InsightsModal()
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
        phases = self.query_one(PhasesPanel)
        phases.refresh_tick(tree._tick)

    def action_focus_tree(self) -> None:
        self.query_one(IssueTree).focus()

    def action_focus_detail(self) -> None:
        terminal = self.query_one(TerminalView)
        if str(terminal.styles.display) != "none":
            terminal.focus()
        else:
            self.query_one(IssueDetail).focus()

    def on_state_updated(self, message: StateUpdated) -> None:
        self._sessions = message.sessions
        tree = self.query_one(IssueTree)
        tree.update_state(message.state, message.sessions)
        header = self.query_one(OrcaHeader)
        header.update_state(message.state, message.sessions)
        # Refresh phases panel if it's showing an issue
        phases = self.query_one(PhasesPanel)
        if phases._issue_id:
            phases.show_phases(phases._issue_id, message.sessions)
            self._update_phase_outcomes(phases._issue_id, phases)
        self._update_status()

    def on_issue_selected(self, message: IssueSelected) -> None:
        if self._state:
            self._deselect_session()
            self.query_one(TerminalView).styles.display = "none"
            detail = self.query_one(IssueDetail)
            detail.styles.display = "block"
            detail.show_issue(message.issue_id, self._state)
            # Populate phases panel
            phases = self.query_one(PhasesPanel)
            phases.show_phases(message.issue_id, self._sessions)
            self._update_phase_outcomes(message.issue_id, phases)

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

        # Look up result data for the selected session
        result_data: dict[str, object] | None = None
        state_name = ""
        duration = ""
        if message.issue_id and not message.active:
            result_data = self._session_result_map(message.issue_id).get(message.session_id)

        # Find session info for state_name and duration
        session = next(
            (s for s in self._sessions if s.get("session_id") == message.session_id),
            None,
        )
        if session:
            state_name = str(session.get("state", ""))
            started = str(session.get("started_at", ""))
            completed = str(session.get("completed_at", ""))
            if started and completed:
                duration = _compute_duration(started, completed)

        detail.styles.display = "none"
        terminal.styles.display = "block"

        if log_path is not None:
            terminal.show_log_file(
                log_path,
                active=message.active,
                result=result_data,
                state_name=state_name,
                duration=duration,
            )
        else:
            terminal.show_placeholder()

    def on_phase_selected(self, message: PhaseSelected) -> None:
        """Handle phase selection from PhasesPanel — load session in terminal."""
        detail = self.query_one(IssueDetail)
        terminal = self.query_one(TerminalView)

        self._deselect_session()
        self._selected_session_id = message.session_id
        self._hot_sessions.add(message.session_id)

        log_path_str = self._session_log_paths.get(message.session_id)
        log_path = Path(log_path_str) if log_path_str else None

        result_data: dict[str, object] | None = None
        state_name = ""
        duration = ""
        if message.issue_id and not message.active:
            result_data = self._session_result_map(message.issue_id).get(message.session_id)

        session = next(
            (s for s in self._sessions if s.get("session_id") == message.session_id),
            None,
        )
        if session:
            state_name = str(session.get("state", ""))
            started = str(session.get("started_at", ""))
            completed = str(session.get("completed_at", ""))
            if started and completed:
                duration = _compute_duration(started, completed)

        detail.styles.display = "none"
        terminal.styles.display = "block"

        if log_path is not None:
            terminal.show_log_file(
                log_path,
                active=message.active,
                result=result_data,
                state_name=state_name,
                duration=duration,
            )
        else:
            terminal.show_placeholder()

    def on_insights_selected(self, message: InsightsSelected) -> None:
        """Handle insights node selection — show insights session log."""
        tracking_id = self._insights_tracking_id
        if not tracking_id:
            return
        detail = self.query_one(IssueDetail)
        terminal = self.query_one(TerminalView)
        self._deselect_session()
        self._selected_session_id = tracking_id
        self._hot_sessions.add(tracking_id)
        log_path_str = self._session_log_paths.get(tracking_id)
        log_path = Path(log_path_str) if log_path_str else None
        detail.styles.display = "none"
        terminal.styles.display = "block"
        if log_path is not None:
            terminal.show_log_file(log_path, active=True, state_name="insights")
        else:
            terminal.show_placeholder()

    def on_insight_entry_selected(self, message: InsightEntrySelected) -> None:
        self._deselect_session()
        terminal = self.query_one(TerminalView)
        terminal.styles.display = "none"
        detail = self.query_one(IssueDetail)
        detail.styles.display = "block"
        icon = {"error": "●", "warning": "⚠", "info": "ℹ", "summary": "◆"}.get(message.severity, "ℹ")
        content = f"# {icon} {message.title}\n\n"
        if message.detail:
            content += f"{message.detail}\n\n"
        if message.remediation:
            content += f"## Remediation\n\n{message.remediation}\n"
        detail.show_issue_text(message.title, content)

    def _deselect_session(self) -> None:
        """Remove the previous session from hot set."""
        if self._selected_session_id is not None:
            self._hot_sessions.discard(self._selected_session_id)
            self._selected_session_id = None

    def _session_result_map(self, issue_id: str) -> dict[str, dict[str, object]]:
        """Build a mapping from session_id to its worker_result event data.

        Matches completed sessions to worker_result events by order (zip).
        """
        if not self._state:
            return {}
        issue = self._state.issues.get(issue_id)
        if not issue:
            return {}
        issue_sessions = [s for s in self._sessions if s.get("issue_id") == issue_id and s.get("completed_at")]
        result_events = [e for e in issue.event_log if e.type == "worker_result"]
        result_map: dict[str, dict[str, object]] = {}
        for session, event in zip(issue_sessions, result_events, strict=False):
            sid = str(session.get("session_id", ""))
            if sid:
                result_map[sid] = event.data
        return result_map

    def _update_phase_outcomes(self, issue_id: str, phases: PhasesPanel) -> None:
        """Extract outcome per session from event_log and pass to PhasesPanel."""
        result_map = self._session_result_map(issue_id)
        outcomes: dict[str, str] = {}
        for sid, data in result_map.items():
            outcome = str(data.get("outcome", ""))
            if outcome:
                outcomes[sid] = outcome
        phases.set_outcomes(outcomes)

    def _update_status(self) -> None:
        if self._state is None:
            self.sub_title = "waiting for state..."
            return
        root_id = self._find_root_issue()
        if root_id and root_id in self._state.issues:
            root = self._state.issues[root_id]
            if self._config:
                type_states = self._config.root_type_def.states
                if root.state in type_states and type_states[root.state].terminal:
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

    def action_toggle_tab(self) -> None:
        """Toggle between Session and Result tabs in the terminal view."""
        terminal = self.query_one(TerminalView)
        if str(terminal.styles.display) != "none":
            terminal.toggle_tab()

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

    def action_toggle_insights(self) -> None:
        """Toggle the insights modal."""
        modal = self.query_one(InsightsModal)
        if modal.is_open:
            modal.close()
        else:
            insights = self._read_insights()
            modal.open(insights)

    def _read_insights(self) -> list[dict[str, object]]:
        import json

        p = self._run_dir / "insights.json"
        if not p.exists():
            return []
        try:
            data: list[dict[str, object]] = json.loads(p.read_text())
            return data
        except (json.JSONDecodeError, OSError):
            return []

    def action_close_modal(self) -> None:
        """Close the insights modal if open."""
        modal = self.query_one(InsightsModal)
        if modal.is_open:
            modal.close()

    def _find_root_issue(self) -> str | None:
        if self._state is None:
            return None
        for iid, issue in self._state.issues.items():
            if issue.decomposed_from is None:
                return iid
        return None


def _compute_duration(started: str, completed: str) -> str:
    """Compute a human-readable duration string from ISO timestamps."""
    try:
        start_dt = datetime.fromisoformat(started)
        end_dt = datetime.fromisoformat(completed)
        delta = end_dt - start_dt
        total_seconds = int(delta.total_seconds())
        if total_seconds < 0:
            return ""
        minutes, seconds = divmod(total_seconds, 60)
        if minutes > 0:
            return f"{minutes}m {seconds}s"
        return f"{seconds}s"
    except (ValueError, TypeError):
        return ""
