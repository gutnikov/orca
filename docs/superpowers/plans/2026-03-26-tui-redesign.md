# TUI Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Polish the orca TUI with a custom header bar, progress bars, pending steps, result badges, failure context, and session/result tabs.

**Architecture:** All changes are in `src/orca/tui/`. The engine and orchestrator are untouched. New `OrcaHeader` widget replaces Textual's `Header`. `IssueTree` gets progress bars, pending steps, result badges, and failure context. `TerminalView` gets a tab bar for switching between session logs and result.json display.

**Tech Stack:** Python 3.12, Textual (TUI framework), Rich (styling)

**Spec:** `docs/superpowers/specs/2026-03-26-tui-redesign-design.md`

---

## File Structure

### New Files
| File | Responsibility |
|------|---------------|
| `src/orca/tui/widgets/header.py` | Custom `OrcaHeader` widget with run stats |
| `tests/tui/test_header.py` | Header widget tests |

### Modified Files
| File | Change |
|------|--------|
| `src/orca/tui/app.py` | Replace `Header` with `OrcaHeader`, pass config to tree, pass state to header |
| `src/orca/tui/messages.py` | Add `issue_id` to `WorkerRunSelected` |
| `src/orca/tui/widgets/issue_tree.py` | Progress bar, pending steps, result badges, failure context, visit counts. Accept `StateMachineConfig`. |
| `src/orca/tui/widgets/terminal_view.py` | Tab bar (Session/Result), result rendering, `t` key binding |
| `tests/tui/test_issue_tree.py` | Tests for new tree features |
| `tests/tui/test_terminal_view.py` | Tests for tab switching and result display |

---

### Task 1: Custom Header Bar

**Files:**
- Create: `src/orca/tui/widgets/header.py`
- Create: `tests/tui/test_header.py`
- Modify: `src/orca/tui/app.py`

- [ ] **Step 1: Write failing test for OrcaHeader**

```python
# tests/tui/test_header.py
from __future__ import annotations

from orca.engine.types import EventLogEntry, Issue, State, StateMachineConfig, StateDef
from orca.tui.widgets.header import OrcaHeader


def _make_config() -> StateMachineConfig:
    return StateMachineConfig(
        issue_fields={},
        initial="planning",
        states={
            "planning": StateDef(),
            "implementing": StateDef(),
            "done": StateDef(terminal=True),
        },
    )


def _make_state(current_state: str = "implementing", worker_active: bool = True) -> State:
    return State(
        issues={
            "root-1": Issue(
                fields={"title": "Test"},
                state=current_state,
                worker_active=worker_active,
                decomposed_from=None,
                depends_on=[],
                event_log=[
                    EventLogEntry(timestamp="2026-01-01T00:00:00+00:00", type="created", data={"state": "planning"}),
                ],
                visit_counts={"planning": 1, "implementing": 1},
            ),
        },
        worker_queues={},
    )


def test_header_renders_branch_name() -> None:
    header = OrcaHeader(branch_name="SMEW-1942", config=_make_config())
    header.update_state(_make_state(), sessions=[], active_workers=1)
    rendered = header.render_text()
    assert "SMEW-1942" in rendered


def test_header_step_count() -> None:
    config = _make_config()
    header = OrcaHeader(branch_name="test", config=config)
    state = _make_state("implementing")
    header.update_state(state, sessions=[], active_workers=1)
    rendered = header.render_text()
    # 2 non-terminal states, root visited 2 unique states
    assert "2/2" in rendered


def test_header_shows_failure_count() -> None:
    header = OrcaHeader(branch_name="test", config=_make_config())
    state = _make_state("implementing", worker_active=False)
    state.issues["root-1"].failure_count = 2
    header.update_state(state, sessions=[], active_workers=0)
    rendered = header.render_text()
    assert "failed" in rendered
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/tui/test_header.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement OrcaHeader**

```python
# src/orca/tui/widgets/header.py
from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.widgets import Static

from orca.engine.types import State, StateMachineConfig


class OrcaHeader(Static):
    """Custom header bar showing run stats."""

    DEFAULT_CSS = """
    OrcaHeader {
        background: #252540;
        color: #888888;
        height: 1;
        dock: top;
        padding: 0 1;
    }
    """

    def __init__(self, branch_name: str, config: StateMachineConfig | None = None) -> None:
        super().__init__("")
        self._branch_name = branch_name
        self._config = config
        self._state: State | None = None
        self._active_workers = 0
        self._elapsed = ""
        # Precompute non-terminal state count
        self._total_steps = 0
        if config:
            self._total_steps = sum(1 for s in config.states.values() if not s.terminal)

    def update_state(self, state: State, sessions: list[dict[str, Any]], active_workers: int = 0) -> None:
        self._state = state
        self._active_workers = active_workers
        # Compute elapsed from first session
        if sessions:
            first = min((s.get("started_at", "") for s in sessions), default="")
            if first:
                self._elapsed = self._format_elapsed(first)
        self.update(self.render_text())

    def render_text(self) -> str:
        parts: list[str] = [f"  orca │"]

        # Status dot + branch
        if self._state is None:
            parts.append(f" {self._branch_name} │ waiting…")
            return " ".join(parts)

        # Check for failures and completion
        root = self._find_root()
        has_failures = any(i.failure_count > 0 for i in self._state.issues.values())
        is_completed = root is not None and self._config is not None and self._is_terminal(root.state)

        if is_completed:
            parts.append(f" ✓ {self._branch_name}")
        elif has_failures:
            parts.append(f" ● {self._branch_name}")
        else:
            parts.append(f" ● {self._branch_name}")

        # Step N/M (root issue only)
        if root is not None and self._total_steps > 0:
            visited = min(len(root.visit_counts), self._total_steps)
            parts.append(f"│ Step {visited}/{self._total_steps}")

        # Workers
        parts.append(f"│ Workers {self._active_workers}")

        # Failures
        if has_failures:
            fail_count = sum(1 for i in self._state.issues.values() if i.failure_count > 0)
            parts.append(f"│ {fail_count} failed")

        # Elapsed
        if self._elapsed:
            parts.append(f"│ {self._elapsed}")

        return " ".join(parts)

    def _find_root(self) -> Any:
        if self._state is None:
            return None
        for issue in self._state.issues.values():
            if issue.decomposed_from is None:
                return issue
        return None

    def _is_terminal(self, state_name: str) -> bool:
        if self._config is None:
            return False
        state_def = self._config.states.get(state_name)
        return state_def is not None and state_def.terminal

    @staticmethod
    def _format_elapsed(iso_timestamp: str) -> str:
        from datetime import UTC, datetime

        try:
            start = datetime.fromisoformat(iso_timestamp)
            delta = datetime.now(UTC) - start
            total = int(delta.total_seconds())
            if total < 0:
                total = 0
            hours, remainder = divmod(total, 3600)
            minutes, _ = divmod(remainder, 60)
            if hours > 0:
                return f"{hours}h {minutes}m"
            return f"{minutes}m"
        except (ValueError, TypeError):
            return ""
```

- [ ] **Step 4: Wire OrcaHeader into app.py**

Replace `Header` import and usage:

```python
# In app.py compose():
from orca.tui.widgets.header import OrcaHeader

def compose(self) -> ComposeResult:
    yield OrcaHeader(branch_name=self._branch_name, config=self._config)
    with Horizontal(id="main-panels"):
        yield IssueTree(insights_enabled=self._insights_enabled, config=self._config)
        yield IssueDetail()
        yield TerminalView()
    yield Footer()

# In on_state_updated():
def on_state_updated(self, message: StateUpdated) -> None:
    tree = self.query_one(IssueTree)
    tree.update_state(message.state, message.sessions)
    # Update header
    active_workers = sum(1 for i in message.state.issues.values() if i.worker_active)
    header = self.query_one(OrcaHeader)
    header.update_state(message.state, message.sessions, active_workers)
    self._update_status()
```

Remove `from textual.widgets import Header` import.

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/tui/test_header.py tests/tui/test_app.py -v`
Expected: all pass

- [ ] **Step 6: Run linters**

Run: `uv run ruff check src/orca/tui/ && uv run mypy src/orca/tui/`

- [ ] **Step 7: Commit**

```bash
git add src/orca/tui/widgets/header.py src/orca/tui/app.py tests/tui/test_header.py
git commit -m "feat: add custom OrcaHeader with run stats"
```

---

### Task 2: Add issue_id to WorkerRunSelected

**Files:**
- Modify: `src/orca/tui/messages.py`
- Modify: `src/orca/tui/widgets/issue_tree.py`

- [ ] **Step 1: Add issue_id to WorkerRunSelected**

In `messages.py`, add `issue_id: str = ""` parameter:

```python
class WorkerRunSelected(Message):
    def __init__(
        self,
        session_id: str,
        active: bool = False,
        worktree_path: str = "",
        issue_id: str = "",
    ) -> None:
        super().__init__()
        self.session_id = session_id
        self.active = active
        self.worktree_path = worktree_path
        self.issue_id = issue_id
```

- [ ] **Step 2: Pass issue_id from issue_tree.py**

In `on_tree_node_highlighted`, look up the session's `issue_id`:

```python
elif data.startswith("session:"):
    session_id = data[8:]
    session = next((s for s in self._sessions if s.get("session_id") == session_id), None)
    active = session is not None and session.get("completed_at") is None
    worktree_path = str(session.get("worktree_path", "")) if session else ""
    issue_id = str(session.get("issue_id", "")) if session else ""
    self.post_message(
        WorkerRunSelected(
            session_id,
            active=active,
            worktree_path=worktree_path,
            issue_id=issue_id,
        )
    )
```

- [ ] **Step 3: Run tests**

Run: `uv run pytest tests/ -q`
Expected: all pass

- [ ] **Step 4: Commit**

```bash
git add src/orca/tui/messages.py src/orca/tui/widgets/issue_tree.py
git commit -m "feat: add issue_id to WorkerRunSelected message"
```

---

### Task 3: Pass StateMachineConfig to IssueTree + progress bar

**Files:**
- Modify: `src/orca/tui/widgets/issue_tree.py`
- Modify: `tests/tui/test_issue_tree.py`

- [ ] **Step 1: Write failing test for progress bar rendering**

```python
# Add to tests/tui/test_issue_tree.py
from orca.engine.types import StateMachineConfig, StateDef

def test_progress_bar_text() -> None:
    """Progress bar renders correct segments for visited/active/pending states."""
    from orca.tui.widgets.issue_tree import _progress_bar_text

    config = StateMachineConfig(
        issue_fields={},
        initial="a",
        states={
            "a": StateDef(),
            "b": StateDef(),
            "c": StateDef(),
            "done": StateDef(terminal=True),
        },
    )
    # Issue visited a (done), currently in b, c pending
    visited = {"a": 1, "b": 1}
    current_state = "b"
    failed_states: set[str] = set()
    result = _progress_bar_text(config, visited, current_state, failed_states)
    assert result is not None
    # Should have 3 segments (a, b, c — done excluded)
    text_str = str(result)
    assert len(text_str) > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/tui/test_issue_tree.py::test_progress_bar_text -v`

- [ ] **Step 3: Update IssueTree constructor to accept config**

```python
def __init__(self, insights_enabled: bool = False, config: StateMachineConfig | None = None) -> None:
    super().__init__("", id="issue-tree")
    self.show_root = False
    self.show_guides = False
    self._sessions: list[dict[str, Any]] = []
    self._state: State | None = None
    self._tick: int = 0
    self._insights_enabled = insights_enabled
    self._config = config
```

- [ ] **Step 4: Implement _progress_bar_text helper**

Add as a module-level function:

```python
def _progress_bar_text(
    config: StateMachineConfig,
    visit_counts: dict[str, int],
    current_state: str,
    failed_states: set[str],
) -> Text | None:
    """Render a progress bar for an issue based on workflow states."""
    non_terminal = [name for name, sdef in config.states.items() if not sdef.terminal]
    if not non_terminal:
        return None
    bar = Text()
    seg_width = max(1, 30 // len(non_terminal))  # ~30 chars total
    for state_name in non_terminal:
        if state_name == current_state:
            bar.append("█" * seg_width, style="#d4a064")  # yellow: active
        elif state_name in failed_states:
            bar.append("█" * seg_width, style="#e06070")  # red: failed
        elif state_name in visit_counts:
            bar.append("█" * seg_width, style="#8bc88b")  # green: done
        else:
            bar.append("█" * seg_width, style="#333333")  # gray: pending
    return bar
```

- [ ] **Step 5: Add progress bar to _add_issue_node**

After adding the issue label node, add the progress bar as the first child content. Compute `failed_states` from the issue's event log (states where the last event was `worker_failed`).

```python
def _add_issue_node(self, parent_node, issue_id, issue, state):
    node = parent_node.add(self._issue_label(issue), data=f"issue:{issue_id}")
    node.expand()

    # Progress bar (only for leaf issues with config)
    children = [(iid, iss) for iid, iss in state.issues.items() if iss.decomposed_from == issue_id]
    if not children and self._config is not None:
        failed_states = self._compute_failed_states(issue)
        bar = _progress_bar_text(self._config, issue.visit_counts, issue.state, failed_states)
        if bar is not None:
            node.add_leaf(bar, data=f"progress:{issue_id}")
    # ... rest of method
```

- [ ] **Step 6: Run tests**

Run: `uv run pytest tests/tui/ -v`

- [ ] **Step 7: Run linters**

Run: `uv run ruff check src/orca/tui/ && uv run mypy src/orca/tui/`

- [ ] **Step 8: Commit**

```bash
git add src/orca/tui/widgets/issue_tree.py tests/tui/test_issue_tree.py
git commit -m "feat: add progress bar to issue tree"
```

---

### Task 4: Pending steps + visit counts + result badges + failure context

**Files:**
- Modify: `src/orca/tui/widgets/issue_tree.py`
- Modify: `tests/tui/test_issue_tree.py`

This task adds the remaining tree enhancements. They all modify `_add_issue_node` and `_worker_run_label`.

- [ ] **Step 1: Write tests**

```python
def test_pending_steps_shown() -> None:
    """Unvisited non-terminal states shown as dimmed entries."""
    from orca.tui.widgets.issue_tree import _pending_steps

    config = StateMachineConfig(
        issue_fields={},
        initial="a",
        states={"a": StateDef(), "b": StateDef(), "c": StateDef(), "done": StateDef(terminal=True)},
    )
    visited = {"a": 1}  # only visited a
    result = _pending_steps(config, visited)
    assert "b" in result
    assert "c" in result
    assert "a" not in result  # already visited
    assert "done" not in result  # terminal


def test_visit_count_for_loops() -> None:
    """Visit count > 1 detected from visit_counts."""
    # visit_counts tracks how many times each state was entered
    visit_counts = {"a": 2, "b": 1}
    assert visit_counts.get("a", 0) > 1  # would show "visit 2"
    assert visit_counts.get("b", 0) == 1  # no badge


def test_result_badge_from_event_log() -> None:
    """Extract outcome from worker_result event log entry."""
    from orca.engine.types import EventLogEntry
    from orca.tui.widgets.issue_tree import _extract_result_outcome

    log = [
        EventLogEntry(timestamp="2026-01-01T00:00:00", type="created", data={"state": "a"}),
        EventLogEntry(timestamp="2026-01-01T00:01:00", type="worker_result", data={"outcome": "ready", "summary": "done"}),
    ]
    assert _extract_result_outcome(log, "a") == "ready"


def test_failure_error_from_event_log() -> None:
    """Extract error from worker_failed event log entry."""
    from orca.engine.types import EventLogEntry
    from orca.tui.widgets.issue_tree import _extract_failure_error

    log = [
        EventLogEntry(timestamp="2026-01-01T00:00:00", type="created", data={"state": "a"}),
        EventLogEntry(timestamp="2026-01-01T00:01:00", type="worker_failed", data={"error": "exit code 1"}),
    ]
    assert _extract_failure_error(log, "a") == "exit code 1"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/tui/test_issue_tree.py -v -k "pending or visit or badge or failure"`

- [ ] **Step 3: Implement helper functions**

```python
def _pending_steps(config: StateMachineConfig, visit_counts: dict[str, int]) -> list[str]:
    """Return non-terminal states not yet visited."""
    return [
        name for name, sdef in config.states.items()
        if not sdef.terminal and name not in visit_counts
    ]


def _extract_result_outcome(event_log: list[EventLogEntry], state_name: str) -> str | None:
    """Find the outcome from the last worker_result for a given state."""
    for entry in reversed(event_log):
        if entry.type == "worker_result":
            outcome = entry.data.get("outcome")
            if outcome:
                return str(outcome)
    return None


def _extract_failure_error(event_log: list[EventLogEntry], state_name: str) -> str | None:
    """Find the error from the last worker_failed for a given state."""
    for entry in reversed(event_log):
        if entry.type == "worker_failed":
            return str(entry.data.get("error", ""))
    return None
```

- [ ] **Step 4: Update _worker_run_label to show result badges and visit counts**

Enhance the label for completed runs:

```python
def _worker_run_label(self, state_name: str, session: dict[str, Any], issue: Issue | None = None) -> Text:
    label = Text()
    is_active = session.get("completed_at") is None
    is_failed = session.get("outcome") == "__failed__"  # check from session data

    if is_active:
        frame = _SPINNER[self._tick % len(_SPINNER)]
        elapsed = _elapsed_str(str(session.get("started_at", "")))
        label.append(f"{frame} ", style="bold yellow")
        label.append(state_name)
        if elapsed:
            label.append(f" {elapsed}", style="dim")
        # Visit count badge
        if issue and issue.visit_counts.get(state_name, 0) > 1:
            count = issue.visit_counts[state_name]
            label.append(f" visit {count}", style="dim")
        # Retry indicator
        # ... compute from event log
    else:
        # Completed or failed
        if is_failed:
            label.append("✗ ", style="bold red")
        else:
            label.append("✓ ", style="green")
        label.append(state_name, style="dim")
        duration = _duration_str(...)
        if duration:
            label.append(f" — {duration}", style="dim")
        # Result badge
        if issue and not is_failed:
            outcome = _extract_result_outcome(issue.event_log, state_name)
            if outcome:
                label.append(f" {outcome}", style="green on #1a3020")
    return label
```

The exact implementation will need to account for:
- Getting the `issue` reference (pass from `_add_issue_node`)
- Determining failed vs succeeded from session/event log data
- Computing retry count from event log

- [ ] **Step 5: Add pending steps and failure context to _add_issue_node**

After worker run leaves, add pending steps as dimmed entries and failure error inline:

```python
# After adding worker run leaves:
if not children and self._config is not None:
    # Pending steps
    pending = _pending_steps(self._config, issue.visit_counts)
    for step_name in pending:
        pending_label = Text()
        pending_label.append("○ ", style="#444444")
        pending_label.append(step_name, style="#444444")
        node.add_leaf(pending_label, data=f"pending:{step_name}")

    # Failure context inline
    if issue.failure_count > 0 and not issue.worker_active:
        error = _extract_failure_error(issue.event_log, issue.state)
        if error:
            error_label = Text()
            error_label.append(f"  {error[:60]}", style="#e06070")
            node.add_leaf(error_label, data=f"error:{issue_id}")
```

- [ ] **Step 6: Run all tests**

Run: `uv run pytest tests/ -q`

- [ ] **Step 7: Run linters**

Run: `uv run ruff check src/orca/tui/ && uv run mypy src/orca/tui/`

- [ ] **Step 8: Commit**

```bash
git add src/orca/tui/widgets/issue_tree.py tests/tui/test_issue_tree.py
git commit -m "feat: add pending steps, visit counts, result badges, failure context to tree"
```

---

### Task 5: Session/Result Tabs in TerminalView

**Files:**
- Modify: `src/orca/tui/widgets/terminal_view.py`
- Modify: `src/orca/tui/app.py`
- Modify: `tests/tui/test_terminal_view.py`

- [ ] **Step 1: Write tests**

```python
# tests/tui/test_terminal_view.py
from __future__ import annotations

from pathlib import Path

from orca.tui.widgets.terminal_view import TerminalView


def test_terminal_view_initial_state() -> None:
    view = TerminalView()
    assert view._log_path is None
    assert view._timer_handle is None
    assert view._active_tab == "session"


def test_show_result_sets_result_data() -> None:
    view = TerminalView()
    result_data = {"outcome": "ready", "summary": "done"}
    view.show_result(result_data, state_name="planning", duration="3m 20s")
    assert view._result_data == result_data
    assert view._active_tab == "result"


def test_show_log_file_for_active_defaults_to_session() -> None:
    view = TerminalView()
    # Active worker: session tab, no result
    view.show_log_file(Path("/tmp/test.log"), active=True)
    assert view._active_tab == "session"
```

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Add tab state and result rendering to TerminalView**

Add to `TerminalView`:

```python
def __init__(self) -> None:
    super().__init__(id="terminal-view")
    self._tab_bar = Static("")
    self._static = Static(_PLACEHOLDER)
    self._log_path: Path | None = None
    self._last_mtime: float = 0.0
    self._timer_handle: object | None = None
    self._active_tab: str = "session"  # "session" or "result"
    self._result_data: dict[str, Any] | None = None
    self._result_state: str = ""
    self._result_duration: str = ""

def compose(self) -> ComposeResult:
    yield self._tab_bar
    yield self._static

def show_result(self, result: dict[str, Any], state_name: str = "", duration: str = "") -> None:
    """Show result.json for a completed worker."""
    self._stop()
    self._result_data = result
    self._result_state = state_name
    self._result_duration = duration
    self._active_tab = "result"
    self._render_tabs()
    self._render_result()

def show_log_file(self, path: Path, *, active: bool = False, result: dict[str, Any] | None = None, ...) -> None:
    """Display session log. If result provided, enable tab switching."""
    self._stop()
    self._log_path = path
    self._last_mtime = 0.0
    self._result_data = result
    if result and not active:
        self._active_tab = "result"
        self._render_tabs()
        self._render_result()
    else:
        self._active_tab = "session"
        self._render_tabs()
        self._render_log()
        if active:
            self._timer_handle = self.set_interval(1.0, self._render_log)

def toggle_tab(self) -> None:
    """Switch between session and result tabs."""
    if self._result_data is None:
        return
    if self._active_tab == "session":
        self._active_tab = "result"
        self._render_tabs()
        self._render_result()
    else:
        self._active_tab = "session"
        self._render_tabs()
        self._render_log()

def _render_tabs(self) -> None:
    """Update the tab bar display."""
    bar = Text()
    if self._active_tab == "session":
        bar.append(" Session ", style="bold")
        bar.append(" │ ", style="dim")
        if self._result_data:
            bar.append(" Result ", style="dim")
        else:
            bar.append(" Result ", style="#444444")
    else:
        bar.append(" Session ", style="dim")
        bar.append(" │ ", style="dim")
        bar.append(" Result ", style="bold")
    self._tab_bar.update(bar)

def _render_result(self) -> None:
    """Render result.json as formatted key/value pairs."""
    if self._result_data is None:
        return
    content = Text()
    content.append(f"  ✓ {self._result_state}", style="green")
    if self._result_duration:
        content.append(f" — completed in {self._result_duration}", style="dim")
    content.append("\n\n")
    for key, value in self._result_data.items():
        content.append(f"  {key:<20}", style="dim")
        if isinstance(value, list):
            for i, item in enumerate(value):
                if i > 0:
                    content.append(f"\n  {'':<20}")
                content.append(str(item))
            content.append("\n")
        else:
            content.append(f"{value}\n")
    self._static.update(content)
```

- [ ] **Step 4: Wire tab toggling in app.py**

Add `t` binding and handler:

```python
BINDINGS = [
    ...
    Binding("t", "toggle_tab", "Toggle Tab", show=False),
]

def action_toggle_tab(self) -> None:
    terminal = self.query_one(TerminalView)
    if str(terminal.styles.display) != "none":
        terminal.toggle_tab()
```

- [ ] **Step 5: Update on_worker_run_selected to pass result data**

```python
def on_worker_run_selected(self, message: WorkerRunSelected) -> None:
    # ... existing code ...
    # Look up result from event log
    result_data = None
    duration = ""
    if self._state and message.issue_id:
        issue = self._state.issues.get(message.issue_id)
        if issue and not message.active:
            # Find last worker_result in event log
            for entry in reversed(issue.event_log):
                if entry.type == "worker_result":
                    result_data = entry.data
                    break
            # Compute duration from session
            # ...

    if log_path is not None:
        terminal.show_log_file(log_path, active=message.active, result=result_data, ...)
```

- [ ] **Step 6: Run tests**

Run: `uv run pytest tests/ -q`

- [ ] **Step 7: Run linters**

Run: `uv run ruff check . && uv run mypy src/`

- [ ] **Step 8: Commit**

```bash
git add src/orca/tui/widgets/terminal_view.py src/orca/tui/app.py tests/tui/test_terminal_view.py
git commit -m "feat: add Session/Result tabs to TerminalView"
```

---

### Task 6: Final polish and verification

- [ ] **Step 1: Run full test suite**

Run: `uv run pytest tests/ -v`

- [ ] **Step 2: Run all linters**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy src/`

- [ ] **Step 3: Check for unused imports**

Run: `uv run ruff check . --select F401`

- [ ] **Step 4: Visual test**

Run orca with a real workflow and verify:
- Custom header shows branch, step count, workers, elapsed
- Progress bar renders under issues
- Pending steps shown as dimmed ○ entries
- Result badges on completed runs
- Failure errors shown inline in red
- Visit counts on looped states
- `t` key toggles Session/Result for completed workers

- [ ] **Step 5: Commit any cleanup**

```bash
git add -A
git commit -m "chore: final polish for TUI redesign"
```
