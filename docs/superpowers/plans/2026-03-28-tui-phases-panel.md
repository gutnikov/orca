# TUI Phases Panel & Insights Modal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the TUI left panel into issue tree (top) and scrollable phases panel (bottom), move insights into a keyboard-triggered modal.

**Architecture:** Create two new Textual widgets (`PhasesPanel`, `InsightsModal`), simplify `IssueTree` by removing session children/pending steps/insights, rewire `OrcaApp.compose()` to a `Vertical` split layout, and connect the new widgets via existing message patterns.

**Tech Stack:** Python 3.12, Textual (TUI framework), Rich (text rendering)

---

## File Structure

| Action | Path | Responsibility |
|--------|------|---------------|
| Create | `src/orca/tui/widgets/phases_panel.py` | Scrollable phase list for selected issue |
| Create | `src/orca/tui/widgets/insights_modal.py` | Modal overlay listing insight entries |
| Modify | `src/orca/tui/widgets/issue_tree.py` | Remove session children, pending steps, insights |
| Modify | `src/orca/tui/app.py` | New layout, wire up phases + modal |
| Modify | `src/orca/tui/messages.py` | Add `PhaseSelected` message |
| Create | `tests/tui/test_phases_panel.py` | Unit tests for PhasesPanel |
| Create | `tests/tui/test_insights_modal.py` | Unit tests for InsightsModal |
| Modify | `tests/tui/test_issue_tree.py` | Update for simplified tree |

---

### Task 1: Add `PhaseSelected` message

**Files:**
- Modify: `src/orca/tui/messages.py`

- [ ] **Step 1: Add PhaseSelected to messages.py**

Add after the `WorkerRunSelected` class in `src/orca/tui/messages.py`:

```python
class PhaseSelected(Message):
    """Posted when the user selects a phase in the phases panel."""

    def __init__(
        self,
        session_id: str,
        active: bool = False,
        issue_id: str = "",
    ) -> None:
        super().__init__()
        self.session_id = session_id
        self.active = active
        self.issue_id = issue_id
```

- [ ] **Step 2: Run type checker**

Run: `uv run mypy src/orca/tui/messages.py`
Expected: Success

- [ ] **Step 3: Commit**

```bash
git add src/orca/tui/messages.py
git commit -m "feat(tui): add PhaseSelected message"
```

---

### Task 2: Create `PhasesPanel` widget

**Files:**
- Create: `src/orca/tui/widgets/phases_panel.py`
- Create: `tests/tui/test_phases_panel.py`

- [ ] **Step 1: Write tests for PhasesPanel**

Create `tests/tui/test_phases_panel.py`:

```python
from __future__ import annotations

from typing import Any

import pytest
from textual.app import App, ComposeResult

from orca.tui.widgets.phases_panel import PhasesPanel


def _make_session(
    session_id: str,
    issue_id: str = "issue-1",
    state: str = "planning",
    started_at: str = "2026-01-01T00:00:00+00:00",
    completed_at: str | None = "2026-01-01T00:01:00+00:00",
) -> dict[str, Any]:
    d: dict[str, Any] = {
        "session_id": session_id,
        "issue_id": issue_id,
        "state": state,
        "started_at": started_at,
    }
    if completed_at is not None:
        d["completed_at"] = completed_at
    return d


class PhasesPanelApp(App[None]):
    def compose(self) -> ComposeResult:
        yield PhasesPanel()


class TestPhasesPanel:
    @pytest.mark.asyncio
    async def test_empty_state(self) -> None:
        app = PhasesPanelApp()
        async with app.run_test() as pilot:
            panel = app.query_one(PhasesPanel)
            assert panel is not None
            await pilot.pause()

    @pytest.mark.asyncio
    async def test_show_phases_renders_sessions(self) -> None:
        app = PhasesPanelApp()
        async with app.run_test() as pilot:
            panel = app.query_one(PhasesPanel)
            sessions = [
                _make_session("s1", state="planning", completed_at="2026-01-01T00:01:00+00:00"),
                _make_session("s2", state="implementing", completed_at="2026-01-01T00:05:00+00:00"),
                _make_session("s3", state="reviewing", completed_at=None),
            ]
            panel.show_phases("issue-1", sessions)
            await pilot.pause()
            # Active session should be first (reversed order)
            content = panel._static.renderable
            text = str(content)
            assert "reviewing" in text
            assert "implementing" in text
            assert "planning" in text

    @pytest.mark.asyncio
    async def test_show_phases_reversed_order(self) -> None:
        app = PhasesPanelApp()
        async with app.run_test() as pilot:
            panel = app.query_one(PhasesPanel)
            sessions = [
                _make_session("s1", state="planning", completed_at="2026-01-01T00:01:00+00:00"),
                _make_session("s2", state="implementing", completed_at="2026-01-01T00:05:00+00:00"),
            ]
            panel.show_phases("issue-1", sessions)
            await pilot.pause()
            text = str(panel._static.renderable)
            # implementing should appear before planning (reversed)
            assert text.index("implementing") < text.index("planning")

    @pytest.mark.asyncio
    async def test_no_pending_phases_shown(self) -> None:
        """Only active + completed phases shown, no future/pending."""
        app = PhasesPanelApp()
        async with app.run_test() as pilot:
            panel = app.query_one(PhasesPanel)
            sessions = [
                _make_session("s1", state="planning", completed_at="2026-01-01T00:01:00+00:00"),
            ]
            panel.show_phases("issue-1", sessions)
            await pilot.pause()
            text = str(panel._static.renderable)
            assert "planning" in text
            # No pending states should appear
            assert "○" not in text

    @pytest.mark.asyncio
    async def test_clear(self) -> None:
        app = PhasesPanelApp()
        async with app.run_test() as pilot:
            panel = app.query_one(PhasesPanel)
            panel.show_phases("issue-1", [_make_session("s1", state="planning")])
            await pilot.pause()
            panel.clear()
            await pilot.pause()
            text = str(panel._static.renderable)
            assert "planning" not in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/tui/test_phases_panel.py -v`
Expected: ImportError — `phases_panel` module does not exist

- [ ] **Step 3: Implement PhasesPanel**

Create `src/orca/tui/widgets/phases_panel.py`:

```python
from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.events import Click
from textual.widgets import Static

from orca.tui.messages import PhaseSelected

_SPINNER = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
_PLACEHOLDER = "*Select an issue to view phases*"


class PhasesPanel(VerticalScroll):
    """Scrollable list of worker phases for the selected issue."""

    DEFAULT_CSS = """
    PhasesPanel {
        height: 1fr;
        min-height: 10;
        border-top: solid #333333;
        padding: 1;
    }
    PhasesPanel Static {
        width: 1fr;
    }
    PhasesPanel #phases-header {
        height: 1;
        color: #666666;
        text-style: bold;
    }
    """

    def __init__(self) -> None:
        super().__init__(id="phases-panel")
        self._header = Static("PHASES", id="phases-header")
        self._static = Static(_PLACEHOLDER)
        self._sessions: list[dict[str, Any]] = []
        self._issue_id: str = ""
        self._tick: int = 0

    def compose(self) -> ComposeResult:
        yield self._header
        yield self._static

    def show_phases(self, issue_id: str, sessions: list[dict[str, Any]]) -> None:
        """Display phases for the given issue."""
        self._issue_id = issue_id
        self._sessions = [s for s in sessions if s.get("issue_id") == issue_id]
        self._render()

    def clear(self) -> None:
        self._issue_id = ""
        self._sessions = []
        self._static.update(_PLACEHOLDER)

    def refresh_tick(self, tick: int) -> None:
        """Advance the spinner for active phases."""
        self._tick = tick
        if self._sessions:
            self._render()

    def on_click(self, event: Click) -> None:
        """Handle click on a phase entry."""
        widget = event.widget
        if widget is self._static:
            # Determine which session was clicked based on y offset
            # For now, clicking the panel selects the active/first session
            if self._sessions:
                # Find clicked session from the entry map
                for session in reversed(self._sessions):
                    session_id = str(session.get("session_id", ""))
                    active = session.get("completed_at") is None
                    if session_id:
                        self.post_message(
                            PhaseSelected(
                                session_id=session_id,
                                active=active,
                                issue_id=self._issue_id,
                            )
                        )
                        break

    def _render(self) -> None:
        if not self._sessions:
            self._static.update(_PLACEHOLDER)
            return

        lines = Text()
        # Reversed: newest first
        reversed_sessions = list(reversed(self._sessions))

        for i, session in enumerate(reversed_sessions):
            state_name = str(session.get("state", "unknown"))
            is_active = session.get("completed_at") is None

            if is_active:
                frame = _SPINNER[self._tick % len(_SPINNER)]
                lines.append(f"{frame} ", style="bold yellow")
                lines.append(state_name, style="bold yellow")
                elapsed = _elapsed_str(str(session.get("started_at", "")))
                if elapsed:
                    lines.append(f"\n  {elapsed}", style="dim")
            else:
                lines.append("✓ ", style="green")
                lines.append(state_name, style="green")
                duration = _duration_str(
                    str(session.get("started_at", "")),
                    str(session.get("completed_at", "")),
                )
                if duration:
                    lines.append(f"\n  {duration}", style="dim")

            # Arrow between entries (not after the last one)
            if i < len(reversed_sessions) - 1:
                lines.append("\n  ↑\n", style="dim")
            else:
                lines.append("\n")

        with contextlib.suppress(Exception):
            self._static.update(lines)


def _elapsed_str(started_at: str) -> str:
    try:
        dt = datetime.fromisoformat(started_at)
        delta = datetime.now(UTC) - dt
        total = int(delta.total_seconds())
        if total < 0:
            total = 0
        minutes, seconds = divmod(total, 60)
        if minutes > 0:
            return f"{minutes}m {seconds:02d}s"
        return f"{seconds}s"
    except (ValueError, TypeError):
        return ""


def _duration_str(started_at: str, completed_at: str) -> str:
    try:
        start = datetime.fromisoformat(started_at)
        end = datetime.fromisoformat(completed_at)
        total = int((end - start).total_seconds())
        if total < 0:
            total = 0
        minutes, seconds = divmod(total, 60)
        if minutes > 0:
            return f"{minutes}m {seconds:02d}s"
        return f"{seconds}s"
    except (ValueError, TypeError):
        return ""
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/tui/test_phases_panel.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Run type checker and linter**

Run: `uv run mypy src/orca/tui/widgets/phases_panel.py && uv run ruff check src/orca/tui/widgets/phases_panel.py`
Expected: No errors

- [ ] **Step 6: Commit**

```bash
git add src/orca/tui/widgets/phases_panel.py tests/tui/test_phases_panel.py
git commit -m "feat(tui): add PhasesPanel widget"
```

---

### Task 3: Create `InsightsModal` widget

**Files:**
- Create: `src/orca/tui/widgets/insights_modal.py`
- Create: `tests/tui/test_insights_modal.py`

- [ ] **Step 1: Write tests for InsightsModal**

Create `tests/tui/test_insights_modal.py`:

```python
from __future__ import annotations

from typing import Any

import pytest
from textual.app import App, ComposeResult

from orca.tui.widgets.insights_modal import InsightsModal


class InsightsModalApp(App[None]):
    def compose(self) -> ComposeResult:
        yield InsightsModal()


class TestInsightsModal:
    @pytest.mark.asyncio
    async def test_starts_hidden(self) -> None:
        app = InsightsModalApp()
        async with app.run_test() as pilot:
            modal = app.query_one(InsightsModal)
            assert str(modal.styles.display) == "none"
            await pilot.pause()

    @pytest.mark.asyncio
    async def test_open_and_close(self) -> None:
        app = InsightsModalApp()
        async with app.run_test() as pilot:
            modal = app.query_one(InsightsModal)
            entries: list[dict[str, Any]] = [
                {"severity": "error", "title": "Build failed", "detail": "d", "remediation": "r"},
                {"severity": "warning", "title": "Slow worker", "detail": "d", "remediation": "r"},
            ]
            modal.open(entries)
            await pilot.pause()
            assert str(modal.styles.display) != "none"
            text = str(modal._static.renderable)
            assert "Build failed" in text
            assert "Slow worker" in text

            modal.close()
            await pilot.pause()
            assert str(modal.styles.display) == "none"

    @pytest.mark.asyncio
    async def test_empty_entries(self) -> None:
        app = InsightsModalApp()
        async with app.run_test() as pilot:
            modal = app.query_one(InsightsModal)
            modal.open([])
            await pilot.pause()
            text = str(modal._static.renderable)
            assert "No insights" in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/tui/test_insights_modal.py -v`
Expected: ImportError — `insights_modal` module does not exist

- [ ] **Step 3: Implement InsightsModal**

Create `src/orca/tui/widgets/insights_modal.py`:

```python
from __future__ import annotations

import contextlib
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static

from orca.tui.messages import InsightEntrySelected

_SEVERITY_ICONS = {
    "error": ("● ", "bold red"),
    "warning": ("⚠ ", "bold yellow"),
    "summary": ("◆ ", "bold cyan"),
    "info": ("ℹ ", "dim"),
}


class InsightsModal(Vertical):
    """Modal overlay displaying insight entries."""

    DEFAULT_CSS = """
    InsightsModal {
        display: none;
        dock: bottom;
        width: 100%;
        height: 60%;
        background: #252540;
        border-top: solid #38b6cc;
        padding: 1 2;
        layer: overlay;
    }
    InsightsModal Static {
        width: 1fr;
    }
    InsightsModal #insights-header {
        height: 1;
        color: #38b6cc;
        text-style: bold;
    }
    InsightsModal #insights-footer {
        dock: bottom;
        height: 1;
        color: #555555;
    }
    """

    def __init__(self) -> None:
        super().__init__(id="insights-modal")
        self._header = Static("◆ Insights", id="insights-header")
        self._static = Static("")
        self._footer = Static("j/k navigate • Enter view detail • Esc close", id="insights-footer")
        self._entries: list[dict[str, Any]] = []

    def compose(self) -> ComposeResult:
        yield self._header
        yield self._static
        yield self._footer

    def open(self, entries: list[dict[str, Any]]) -> None:
        """Show the modal with the given insight entries."""
        self._entries = entries
        self.styles.display = "block"
        self._render()
        self.focus()

    def close(self) -> None:
        """Hide the modal."""
        self.styles.display = "none"

    @property
    def is_open(self) -> bool:
        return str(self.styles.display) != "none"

    def _render(self) -> None:
        if not self._entries:
            self._static.update("*No insights yet*")
            return

        lines = Text()
        for entry in self._entries:
            sev = str(entry.get("severity", "info"))
            title = str(entry.get("title", "Untitled"))
            icon, style = _SEVERITY_ICONS.get(sev, ("ℹ ", "dim"))
            lines.append(icon, style=style)
            lines.append(f"{title}\n")

        with contextlib.suppress(Exception):
            self._static.update(lines)

    def select_entry(self, index: int) -> None:
        """Post an InsightEntrySelected message for the entry at the given index."""
        if 0 <= index < len(self._entries):
            e = self._entries[index]
            self.post_message(
                InsightEntrySelected(
                    title=str(e.get("title", "")),
                    detail=str(e.get("detail", "")),
                    remediation=str(e.get("remediation", "")),
                    severity=str(e.get("severity", "info")),
                )
            )
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/tui/test_insights_modal.py -v`
Expected: All 3 tests PASS

- [ ] **Step 5: Run type checker and linter**

Run: `uv run mypy src/orca/tui/widgets/insights_modal.py && uv run ruff check src/orca/tui/widgets/insights_modal.py`
Expected: No errors

- [ ] **Step 6: Commit**

```bash
git add src/orca/tui/widgets/insights_modal.py tests/tui/test_insights_modal.py
git commit -m "feat(tui): add InsightsModal widget"
```

---

### Task 4: Simplify IssueTree — remove session children, pending steps, and insights

**Files:**
- Modify: `src/orca/tui/widgets/issue_tree.py`
- Modify: `tests/tui/test_issue_tree.py`

- [ ] **Step 1: Remove session children and pending steps from `_add_issue_node`**

In `src/orca/tui/widgets/issue_tree.py`, replace the `_add_issue_node` method (lines 307-383). The new version keeps only the issue node and child issues — no session leaves, no pending steps:

```python
def _add_issue_node(self, parent_node: TreeNode[str], issue_id: str, issue: Issue, state: State) -> None:
    failed_states = _compute_failed_states(issue)
    node = parent_node.add(self._issue_label(issue, failed_states), data=f"issue:{issue_id}")
    node.expand()

    # Add child issues (decomposed)
    children = [(iid, iss) for iid, iss in state.issues.items() if iss.decomposed_from == issue_id]
    for child_id, child_issue in children:
        self._add_issue_node(node, child_id, child_issue, state)
```

- [ ] **Step 2: Remove insights from `update_state`**

In `update_state`, remove the insights block (lines 266-286) that adds the insights parent node and its children. The block starts with `if self._insights_enabled:` and ends before `self.root.expand()`.

Also remove the `_read_insights` method and the `_insights_enabled` and `_run_dir` instance variables from `__init__`, since they're no longer used by the tree (insights are now in the modal).

Update `__init__` signature — remove `insights_enabled` and `run_dir` parameters:

```python
def __init__(
    self,
    config: StateMachineConfig | None = None,
) -> None:
    super().__init__("", id="issue-tree")
    self.show_root = False
    self.show_guides = False
    self._sessions: list[dict[str, Any]] = []
    self._state: State | None = None
    self._tick: int = 0
    self._config = config
```

- [ ] **Step 3: Remove insight-related event handling from `on_tree_node_highlighted`**

Remove the `elif data == "insights":` and `elif data.startswith("insight:")` branches (lines 424-440). Also remove the session-related branch (`elif data.startswith("session:"):`  lines 410-423) since session selection now comes from the PhasesPanel.

The simplified handler:

```python
def on_tree_node_highlighted(self, event: Tree.NodeHighlighted[str]) -> None:
    """Auto-activate on highlight (no Enter needed)."""
    if not event.node.data:
        return
    data = event.node.data
    if data.startswith(("progress:", "pending:", "error:")):
        return
    if data.startswith("issue:"):
        self.post_message(IssueSelected(data[6:]))
```

- [ ] **Step 4: Remove `_worker_run_label` method**

Delete the entire `_worker_run_label` method (lines 195-247) since worker run labels are now rendered by PhasesPanel.

- [ ] **Step 5: Clean up unused imports and helpers**

Remove unused imports and functions that were only used for session/insight rendering:
- Remove `from orca.tui.messages import InsightsSelected, WorkerRunSelected` (keep `IssueSelected`)
- Remove `_extract_result_outcomes` function if no longer referenced
- Remove `_extract_failure_errors` function if no longer referenced
- Remove `import json` if `_read_insights` is removed
- Remove `from pathlib import Path` if `_run_dir` is removed

Keep `_compute_failed_states` (used by `_issue_label` for progress bar) and `_progress_bar_text` and `_pending_steps`.

- [ ] **Step 6: Remove the `_update_active_labels` method**

Delete `_update_active_labels` (lines 448+) since active session spinner labels are now in PhasesPanel. Update `refresh_tick` to just increment the tick:

```python
def refresh_tick(self) -> None:
    """Called by the app timer to advance the spinner."""
    self._tick += 1
```

- [ ] **Step 7: Remove cursor restore for sessions**

In `update_state`, remove the session cursor restore fallback (lines 295-304) that tries to find a parent issue when a session node is truncated. The simplified cursor restore:

```python
if cursor_data:
    self._restore_cursor(cursor_data)
elif roots:
    first_iid = roots[0][0]
    first_node = self._find_by_data(self.root, f"issue:{first_iid}")
    if first_node:
        self.move_cursor(first_node)
```

- [ ] **Step 8: Update tests**

In `tests/tui/test_issue_tree.py`, update tests that check for session children or insights nodes. Remove or update:
- Tests that check worker run labels as children of issue nodes
- Tests that reference `insights_enabled` or `run_dir` constructor args
- Update `IssueTreeApp` to not pass removed params

Keep tests for `_compute_failed_states`, `_extract_result_outcomes`, `_extract_failure_errors`, `_progress_bar_text`, `_pending_steps` — these helper functions stay even if some aren't used by the tree directly anymore (PhasesPanel may reference them, or they serve as unit-tested utilities).

- [ ] **Step 9: Run all tests**

Run: `uv run pytest tests/tui/ -v`
Expected: All tests PASS

- [ ] **Step 10: Run type checker and linter**

Run: `uv run mypy src/orca/tui/widgets/issue_tree.py && uv run ruff check src/orca/tui/widgets/issue_tree.py`
Expected: No errors

- [ ] **Step 11: Commit**

```bash
git add src/orca/tui/widgets/issue_tree.py tests/tui/test_issue_tree.py
git commit -m "refactor(tui): simplify IssueTree — remove sessions, pending steps, insights"
```

---

### Task 5: Rewire `OrcaApp` layout and event handling

**Files:**
- Modify: `src/orca/tui/app.py`

- [ ] **Step 1: Update imports**

In `src/orca/tui/app.py`, add imports for the new widgets and message:

```python
from textual.containers import Horizontal, Vertical

from orca.tui.messages import (
    InsightEntrySelected,
    InsightsSelected,
    IssueSelected,
    PhaseSelected,
    StateUpdated,
    WorkerRunSelected,
)
from orca.tui.widgets.insights_modal import InsightsModal
from orca.tui.widgets.phases_panel import PhasesPanel
```

- [ ] **Step 2: Update CSS**

Replace the `CSS` class variable in `OrcaApp`:

```python
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
}
#terminal-view {
    display: none;
}
"""
```

- [ ] **Step 3: Update `compose` method**

Replace the `compose` method:

```python
def compose(self) -> ComposeResult:
    yield OrcaHeader(branch_name=self._branch_name, config=self._config)
    with Horizontal(id="main-panels"):
        with Vertical(id="left-column"):
            yield IssueTree(config=self._config)
            yield PhasesPanel()
        yield IssueDetail()
        yield TerminalView()
    yield InsightsModal()
    yield Footer()
```

- [ ] **Step 4: Add `i` keybinding for insights modal**

Add to `BINDINGS`:

```python
Binding("i", "toggle_insights", "Insights", show=False),
```

- [ ] **Step 5: Add `action_toggle_insights` method**

```python
def action_toggle_insights(self) -> None:
    """Toggle the insights modal."""
    modal = self.query_one(InsightsModal)
    if modal.is_open:
        modal.close()
    else:
        insights = self._read_insights()
        modal.open(insights)
```

- [ ] **Step 6: Add `_read_insights` helper to OrcaApp**

Move the insights-reading logic from IssueTree to OrcaApp:

```python
def _read_insights(self) -> list[dict[str, Any]]:
    import json
    p = self._run_dir / "insights.json"
    if not p.exists():
        return []
    try:
        data: list[dict[str, Any]] = json.loads(p.read_text())
        return data
    except (json.JSONDecodeError, OSError):
        return []
```

- [ ] **Step 7: Update `on_issue_selected` to populate PhasesPanel**

Replace `on_issue_selected`:

```python
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
```

- [ ] **Step 8: Add `on_phase_selected` handler**

Handle `PhaseSelected` the same way as `WorkerRunSelected`:

```python
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
    if self._state and message.issue_id:
        issue = self._state.issues.get(message.issue_id)
        if issue and not message.active:
            for entry in reversed(issue.event_log):
                if entry.type == "worker_result":
                    result_data = entry.data
                    break

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
```

- [ ] **Step 9: Update `on_state_updated` to refresh PhasesPanel**

In the existing `on_state_updated`, add a refresh for the phases panel:

```python
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
    self._update_status()
```

- [ ] **Step 10: Update `_tick_spinners` to also tick the phases panel**

```python
def _tick_spinners(self) -> None:
    tree = self.query_one(IssueTree)
    tree.refresh_tick()
    phases = self.query_one(PhasesPanel)
    phases.refresh_tick(tree._tick)
```

- [ ] **Step 11: Remove `on_insights_selected` handler**

Delete the `on_insights_selected` method since insights are no longer in the tree. Keep `on_insight_entry_selected` — it's still used when a user selects an entry from the modal.

- [ ] **Step 12: Handle Esc to close insights modal**

Add an `action_escape` or key binding. The simplest approach: add Esc handling in the insights modal key event, or add a binding:

```python
Binding("escape", "close_modal", "Close", show=False),
```

And the handler:

```python
def action_close_modal(self) -> None:
    """Close the insights modal if open."""
    modal = self.query_one(InsightsModal)
    if modal.is_open:
        modal.close()
```

- [ ] **Step 13: Update IssueTree constructor call**

The `compose` method already uses the new signature from Step 3 (`IssueTree(config=self._config)` without `insights_enabled` or `run_dir`). Verify no other place passes those removed params.

- [ ] **Step 14: Run all tests**

Run: `uv run pytest tests/tui/ -v`
Expected: All tests PASS

- [ ] **Step 15: Run full test suite, type checker, linter**

Run: `uv run pytest -x -q && uv run mypy src/ && uv run ruff check .`
Expected: All pass

- [ ] **Step 16: Commit**

```bash
git add src/orca/tui/app.py
git commit -m "feat(tui): rewire app layout with split left panel and insights modal"
```

---

### Task 6: Integration test and cleanup

**Files:**
- Modify: `tests/tui/test_app.py` (if it exists and needs updates)
- Modify: `src/orca/tui/widgets/__init__.py` (if it exports widgets)

- [ ] **Step 1: Check `__init__.py` exports**

Read `src/orca/tui/widgets/__init__.py` and `src/orca/tui/__init__.py`. If they export the old widget signatures, update them.

- [ ] **Step 2: Run full test suite**

Run: `uv run pytest -x -q`
Expected: All tests PASS

- [ ] **Step 3: Run type checker on entire project**

Run: `uv run mypy src/`
Expected: No errors

- [ ] **Step 4: Run linter**

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: No errors

- [ ] **Step 5: Commit any remaining cleanup**

```bash
git add -u
git commit -m "chore(tui): integration cleanup for phases panel"
```
