# Textual TUI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Textual-based terminal dashboard (`orca watch`) that shows a live, interactive view of orchestrator state with a three-panel layout: issue tree, issue detail (markdown), and status history timeline.

**Architecture:** Standalone `src/orca/tui/` package that reads `state.json` via polling. No changes to engine or orchestrator. The TUI reuses existing `State`/`Issue` types and `Persistence.load()` for deserialization. Textual's `Tree`, `Markdown`, and `Static` widgets provide the three panels.

**Tech Stack:** Python 3.12, Textual >= 1.0 (optional dependency), existing orca.engine.types and orca.engine.config

**Spec:** `docs/superpowers/specs/2026-03-23-textual-tui-design.md`

---

## File Structure

```
src/orca/tui/
├── __init__.py              # Empty
├── app.py                   # OrcaApp — layout, polling timer, keybindings
├── messages.py              # Custom Textual messages: StateUpdated, IssueSelected
├── state_reader.py          # StateReader — mtime-tracked state.json reading
└── widgets/
    ├── __init__.py           # Empty
    ├── issue_tree.py         # IssueTree — left panel tree widget
    ├── issue_detail.py       # IssueDetail — center panel markdown viewer
    └── status_history.py     # StatusHistory — right panel timeline

tests/tui/
├── __init__.py
├── test_state_reader.py     # StateReader unit tests
├── test_issue_tree.py       # IssueTree unit tests
├── test_issue_detail.py     # IssueDetail unit tests
├── test_status_history.py   # StatusHistory unit tests
└── test_app.py              # OrcaApp integration tests

Modify:
├── pyproject.toml            # Add textual optional dependency
└── src/orca/orchestrator/runner.py  # Add `orca watch` subcommand
```

---

### Task 1: Add Textual Optional Dependency

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add textual to optional dependencies in pyproject.toml**

Add an optional dependency group and include it in dev dependencies for testing:

```toml
[project.optional-dependencies]
tui = ["textual>=1.0"]
```

And add to the dev dependency group:

```toml
[dependency-groups]
dev = [
    # ... existing entries ...
    "textual>=1.0",
]
```

- [ ] **Step 2: Run uv sync to install**

Run: `uv sync`
Expected: Textual and its dependencies installed successfully.

- [ ] **Step 3: Verify import works**

Run: `uv run python -c "import textual; print(textual.__version__)"`
Expected: Prints version >= 1.0

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "feat: add textual as optional dependency for TUI"
```

---

### Task 2: Custom Textual Messages

**Files:**
- Create: `src/orca/tui/__init__.py`
- Create: `src/orca/tui/messages.py`

- [ ] **Step 1: Create package init files**

Create empty `src/orca/tui/__init__.py` and `src/orca/tui/widgets/__init__.py`.

- [ ] **Step 2: Write messages module**

```python
# src/orca/tui/messages.py
from __future__ import annotations

from textual.message import Message

from orca.engine.types import State


class StateUpdated(Message):
    """Posted when state.json has changed on disk."""

    def __init__(self, state: State) -> None:
        super().__init__()
        self.state = state


class IssueSelected(Message):
    """Posted when the user selects an issue in the tree."""

    def __init__(self, issue_id: str) -> None:
        super().__init__()
        self.issue_id = issue_id
```

- [ ] **Step 3: Run type check**

Run: `uv run mypy src/orca/tui/messages.py`
Expected: Success, no errors.

- [ ] **Step 4: Commit**

```bash
git add src/orca/tui/
git commit -m "feat: add custom Textual messages for TUI"
```

---

### Task 3: StateReader

**Files:**
- Create: `src/orca/tui/state_reader.py`
- Create: `tests/tui/__init__.py`
- Create: `tests/tui/test_state_reader.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/tui/test_state_reader.py
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from orca.engine.types import EventLogEntry, Issue, State
from orca.tui.state_reader import StateReader


def _make_state(title: str = "Test Issue") -> State:
    """Create a minimal State for testing."""
    return State(
        issues={
            "issue-1": Issue(
                fields={"title": title, "description": "A test issue"},
                state="triage",
                worker_active=False,
                decomposed_from=None,
                depends_on=[],
                event_log=[
                    EventLogEntry(
                        timestamp="2026-01-01T00:00:00+00:00",
                        type="created",
                        data={},
                    )
                ],
            )
        },
        worker_queues={},
    )


def _write_state(path: Path, state: State) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state.to_dict(), indent=2))


class TestStateReader:
    def test_read_returns_none_when_file_missing(self, tmp_path: Path) -> None:
        reader = StateReader(tmp_path / "nonexistent")
        assert reader.read() is None

    def test_read_returns_state_when_file_exists(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run"
        state = _make_state()
        _write_state(run_dir / "state.json", state)

        reader = StateReader(run_dir)
        result = reader.read()

        assert result is not None
        assert "issue-1" in result.issues
        assert result.issues["issue-1"].fields["title"] == "Test Issue"

    def test_read_returns_none_when_mtime_unchanged(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run"
        state = _make_state()
        _write_state(run_dir / "state.json", state)

        reader = StateReader(run_dir)
        first = reader.read()
        assert first is not None

        second = reader.read()
        assert second is None  # mtime unchanged, skip

    def test_read_returns_new_state_after_file_update(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run"
        state = _make_state("Original")
        state_path = run_dir / "state.json"
        _write_state(state_path, state)

        reader = StateReader(run_dir)
        first = reader.read()
        assert first is not None

        # Ensure mtime changes (filesystem granularity)
        time.sleep(0.05)
        updated = _make_state("Updated")
        _write_state(state_path, updated)

        result = reader.read()
        assert result is not None
        assert result.issues["issue-1"].fields["title"] == "Updated"

    def test_last_mtime_returns_zero_when_no_file(self, tmp_path: Path) -> None:
        reader = StateReader(tmp_path / "nonexistent")
        assert reader.last_mtime == 0.0

    def test_last_mtime_updates_after_read(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run"
        _write_state(run_dir / "state.json", _make_state())

        reader = StateReader(run_dir)
        assert reader.last_mtime == 0.0
        reader.read()
        assert reader.last_mtime > 0.0

    def test_reset_allows_re_read(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run"
        _write_state(run_dir / "state.json", _make_state())

        reader = StateReader(run_dir)
        first = reader.read()
        assert first is not None

        second = reader.read()
        assert second is None  # mtime unchanged

        reader.reset()
        third = reader.read()
        assert third is not None  # re-read after reset
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/tui/test_state_reader.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'orca.tui.state_reader'`

- [ ] **Step 3: Write StateReader implementation**

```python
# src/orca/tui/state_reader.py
from __future__ import annotations

import json
from pathlib import Path

from orca.engine.types import State


class StateReader:
    """Reads orchestrator state from disk with mtime-based change detection."""

    def __init__(self, run_dir: Path) -> None:
        self._state_path = run_dir / "state.json"
        self._last_mtime: float = 0.0

    @property
    def last_mtime(self) -> float:
        return self._last_mtime

    def read(self) -> State | None:
        """Read state.json if it exists and has changed since the last read.

        Returns the new State if the file was updated, or None if:
        - The file does not exist
        - The file mtime has not changed since the last read
        """
        if not self._state_path.exists():
            return None

        mtime = self._state_path.stat().st_mtime
        if mtime == self._last_mtime:
            return None

        self._last_mtime = mtime
        data = json.loads(self._state_path.read_text())
        return State.from_dict(data)

    def reset(self) -> None:
        """Reset mtime tracking so the next read() always returns state."""
        self._last_mtime = 0.0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/tui/test_state_reader.py -v`
Expected: All 7 tests PASS.

- [ ] **Step 5: Run linters**

Run: `uv run ruff check src/orca/tui/state_reader.py tests/tui/ && uv run mypy src/orca/tui/state_reader.py`
Expected: No errors.

- [ ] **Step 6: Commit**

```bash
git add src/orca/tui/state_reader.py tests/tui/
git commit -m "feat: add StateReader with mtime-based change detection"
```

---

### Task 4: IssueTree Widget

**Files:**
- Create: `src/orca/tui/widgets/issue_tree.py`
- Create: `tests/tui/test_issue_tree.py`

- [ ] **Step 1: Write the failing tests**

Test the tree-building logic and label formatting. Use Textual's async test support (`async with app.run_test()`).

```python
# tests/tui/test_issue_tree.py
from __future__ import annotations

import pytest
from textual.app import App, ComposeResult

from orca.engine.types import EventLogEntry, Issue, State
from orca.tui.messages import StateUpdated
from orca.tui.widgets.issue_tree import IssueTree


def _make_issue(
    title: str = "Test",
    state: str = "triage",
    worker_active: bool = False,
    decomposed_from: str | None = None,
    depends_on: list[str] | None = None,
) -> Issue:
    return Issue(
        fields={"title": title, "description": "desc"},
        state=state,
        worker_active=worker_active,
        decomposed_from=decomposed_from,
        depends_on=depends_on or [],
        event_log=[
            EventLogEntry(timestamp="2026-01-01T00:00:00+00:00", type="created", data={})
        ],
    )


class IssueTreeApp(App[None]):
    """Test harness app for IssueTree."""

    def compose(self) -> ComposeResult:
        yield IssueTree()


class TestIssueTree:
    @pytest.mark.asyncio
    async def test_builds_tree_from_state(self) -> None:
        app = IssueTreeApp()
        async with app.run_test() as pilot:
            tree = app.query_one(IssueTree)
            state = State(
                issues={
                    "root": _make_issue("Root Task", "work"),
                    "child-1": _make_issue("Child One", "triage", decomposed_from="root"),
                },
                worker_queues={},
            )
            tree.update_state(state)
            await pilot.pause()

            # Root should have one child
            root_node = tree.root
            assert len(root_node.children) == 1
            top_node = root_node.children[0]
            assert "Root Task" in str(top_node.label)
            assert len(top_node.children) == 1
            assert "Child One" in str(top_node.children[0].label)

    @pytest.mark.asyncio
    async def test_label_shows_state_badge(self) -> None:
        app = IssueTreeApp()
        async with app.run_test() as pilot:
            tree = app.query_one(IssueTree)
            state = State(
                issues={"id-1": _make_issue("My Task", "work")},
                worker_queues={},
            )
            tree.update_state(state)
            await pilot.pause()

            label_text = str(tree.root.children[0].label)
            assert "work" in label_text

    @pytest.mark.asyncio
    async def test_label_shows_worker_spinner(self) -> None:
        app = IssueTreeApp()
        async with app.run_test() as pilot:
            tree = app.query_one(IssueTree)
            state = State(
                issues={"id-1": _make_issue("Active Task", "work", worker_active=True)},
                worker_queues={},
            )
            tree.update_state(state)
            await pilot.pause()

            label_text = str(tree.root.children[0].label)
            assert "⟳" in label_text

    @pytest.mark.asyncio
    async def test_no_spinner_when_worker_inactive(self) -> None:
        app = IssueTreeApp()
        async with app.run_test() as pilot:
            tree = app.query_one(IssueTree)
            state = State(
                issues={"id-1": _make_issue("Idle Task", "work", worker_active=False)},
                worker_queues={},
            )
            tree.update_state(state)
            await pilot.pause()

            label_text = str(tree.root.children[0].label)
            assert "⟳" not in label_text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/tui/test_issue_tree.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'orca.tui.widgets.issue_tree'`

- [ ] **Step 3: Write IssueTree implementation**

```python
# src/orca/tui/widgets/issue_tree.py
from __future__ import annotations

from textual.widgets import Tree
from textual.widgets.tree import TreeNode

from orca.engine.types import Issue, State
from orca.tui.messages import IssueSelected


class IssueTree(Tree[str]):
    """Hierarchical tree view of orchestrator issues."""

    DEFAULT_CSS = """
    IssueTree {
        width: 3fr;
        border-right: solid $surface-lighten-2;
        padding: 1;
    }
    """

    def __init__(self) -> None:
        super().__init__("Issues", id="issue-tree")
        self._issue_ids: set[str] = set()

    def _make_label(self, issue: Issue) -> str:
        title = str(issue.fields.get("title", "untitled"))
        spinner = " ⟳" if issue.worker_active else ""
        return f"{title} [{issue.state}]{spinner}"

    def update_state(self, state: State) -> None:
        """Rebuild the tree from the current state."""
        # Track cursor position
        cursor_issue_id: str | None = None
        if self.cursor_node and self.cursor_node.data:
            cursor_issue_id = self.cursor_node.data

        # Clear and rebuild
        self.root.remove_children()
        self._issue_ids.clear()

        # Find root issues (no parent)
        roots = {
            iid: issue
            for iid, issue in state.issues.items()
            if issue.decomposed_from is None
        }

        for iid, issue in roots.items():
            node = self.root.add(self._make_label(issue), data=iid)
            self._issue_ids.add(iid)
            self._add_children(node, iid, state)
            node.expand()

        self.root.expand()

        # Restore cursor if possible
        if cursor_issue_id:
            self._select_node(cursor_issue_id)

    def _add_children(
        self, parent_node: TreeNode[str], parent_id: str, state: State
    ) -> None:
        children = {
            iid: issue
            for iid, issue in state.issues.items()
            if issue.decomposed_from == parent_id
        }
        for iid, issue in children.items():
            node = parent_node.add(self._make_label(issue), data=iid)
            self._issue_ids.add(iid)
            self._add_children(node, iid, state)
            node.expand()

    def _select_node(self, issue_id: str) -> None:
        """Find and select a node by issue_id."""
        for node in self.root.children:
            found = self._find_node(node, issue_id)
            if found:
                self.select_node(found)
                return

    def _find_node(
        self, node: TreeNode[str], issue_id: str
    ) -> TreeNode[str] | None:
        if node.data == issue_id:
            return node
        for child in node.children:
            found = self._find_node(child, issue_id)
            if found:
                return found
        return None

    def on_tree_node_selected(self, event: Tree.NodeSelected[str]) -> None:
        """When a tree node is clicked/selected, post IssueSelected."""
        if event.node.data:
            self.post_message(IssueSelected(event.node.data))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/tui/test_issue_tree.py -v`
Expected: All 4 tests PASS.

- [ ] **Step 5: Run linters**

Run: `uv run ruff check src/orca/tui/widgets/issue_tree.py tests/tui/test_issue_tree.py && uv run mypy src/orca/tui/widgets/issue_tree.py`
Expected: No errors.

- [ ] **Step 6: Commit**

```bash
git add src/orca/tui/widgets/issue_tree.py tests/tui/test_issue_tree.py
git commit -m "feat: add IssueTree widget with hierarchy and worker spinner"
```

---

### Task 5: IssueDetail Widget

**Files:**
- Create: `src/orca/tui/widgets/issue_detail.py`
- Create: `tests/tui/test_issue_detail.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/tui/test_issue_detail.py
from __future__ import annotations

import pytest
from textual.app import App, ComposeResult

from orca.engine.types import Issue, State
from orca.tui.widgets.issue_detail import IssueDetail


def _make_issue(title: str = "Test", description: str = "Some description") -> Issue:
    return Issue(
        fields={"title": title, "description": description},
        state="triage",
        worker_active=False,
        decomposed_from=None,
        depends_on=[],
        event_log=[],
    )


class IssueDetailApp(App[None]):
    def compose(self) -> ComposeResult:
        yield IssueDetail()


class TestIssueDetail:
    @pytest.mark.asyncio
    async def test_shows_placeholder_when_no_issue_selected(self) -> None:
        app = IssueDetailApp()
        async with app.run_test() as pilot:
            detail = app.query_one(IssueDetail)
            await pilot.pause()
            # Should show placeholder text by default
            assert detail._current_issue_id is None

    @pytest.mark.asyncio
    async def test_shows_issue_content(self) -> None:
        app = IssueDetailApp()
        async with app.run_test() as pilot:
            detail = app.query_one(IssueDetail)
            state = State(
                issues={"id-1": _make_issue("My Title", "My **bold** text")},
                worker_queues={},
            )
            detail.show_issue("id-1", state)
            await pilot.pause()
            assert detail._current_issue_id == "id-1"

    @pytest.mark.asyncio
    async def test_clears_when_issue_not_in_state(self) -> None:
        app = IssueDetailApp()
        async with app.run_test() as pilot:
            detail = app.query_one(IssueDetail)
            state = State(issues={}, worker_queues={})
            detail.show_issue("nonexistent", state)
            await pilot.pause()
            assert detail._current_issue_id is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/tui/test_issue_detail.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write IssueDetail implementation**

```python
# src/orca/tui/widgets/issue_detail.py
from __future__ import annotations

from textual.containers import VerticalScroll
from textual.widgets import Markdown

from orca.engine.types import State

_PLACEHOLDER = "*Select an issue from the tree*"


class IssueDetail(VerticalScroll):
    """Center panel — renders the selected issue's fields as markdown."""

    DEFAULT_CSS = """
    IssueDetail {
        width: 4fr;
        border-right: solid $surface-lighten-2;
        padding: 1;
    }
    """

    def __init__(self) -> None:
        super().__init__(id="issue-detail")
        self._markdown = Markdown(_PLACEHOLDER)
        self._current_issue_id: str | None = None

    def compose(self):  # type: ignore[override]
        yield self._markdown

    def show_issue(self, issue_id: str, state: State) -> None:
        """Render the given issue's fields as markdown."""
        issue = state.issues.get(issue_id)
        if issue is None:
            self._current_issue_id = None
            self._markdown.update(_PLACEHOLDER)
            return

        self._current_issue_id = issue_id
        title = issue.fields.get("title", "Untitled")
        description = issue.fields.get("description", "")
        content = f"# {title}\n\n{description}"
        self._markdown.update(content)

    def clear(self) -> None:
        """Reset to placeholder."""
        self._current_issue_id = None
        self._markdown.update(_PLACEHOLDER)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/tui/test_issue_detail.py -v`
Expected: All 3 tests PASS.

- [ ] **Step 5: Run linters**

Run: `uv run ruff check src/orca/tui/widgets/issue_detail.py tests/tui/test_issue_detail.py && uv run mypy src/orca/tui/widgets/issue_detail.py`
Expected: No errors.

- [ ] **Step 6: Commit**

```bash
git add src/orca/tui/widgets/issue_detail.py tests/tui/test_issue_detail.py
git commit -m "feat: add IssueDetail widget with markdown rendering"
```

---

### Task 6: StatusHistory Widget

**Files:**
- Create: `src/orca/tui/widgets/status_history.py`
- Create: `tests/tui/test_status_history.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/tui/test_status_history.py
from __future__ import annotations

import pytest
from textual.app import App, ComposeResult

from orca.engine.types import EventLogEntry, Issue, State
from orca.tui.widgets.status_history import StatusHistory, build_timeline


def _make_issue_with_log(entries: list[EventLogEntry], current_state: str = "review") -> Issue:
    return Issue(
        fields={"title": "Test", "description": "desc"},
        state=current_state,
        worker_active=False,
        decomposed_from=None,
        depends_on=[],
        event_log=entries,
    )


class TestBuildTimeline:
    def test_empty_event_log(self) -> None:
        issue = _make_issue_with_log([], current_state="triage")
        result = build_timeline(issue)
        # Should show at least the current state
        assert "triage" in result

    def test_shows_state_transitions_in_order(self) -> None:
        entries = [
            EventLogEntry(
                timestamp="2026-01-01T00:00:00+00:00",
                type="created",
                data={"state": "triage"},
            ),
            EventLogEntry(
                timestamp="2026-01-01T00:01:00+00:00",
                type="state_changed",
                data={"from": "triage", "to": "work", "outcome": "ready"},
            ),
            EventLogEntry(
                timestamp="2026-01-01T00:02:00+00:00",
                type="state_changed",
                data={"from": "work", "to": "review", "outcome": "completed"},
            ),
        ]
        issue = _make_issue_with_log(entries, current_state="review")
        result = build_timeline(issue)
        assert "triage" in result
        assert "work" in result
        assert "review" in result
        assert "ready" in result
        assert "completed" in result

    def test_current_state_uses_filled_marker(self) -> None:
        entries = [
            EventLogEntry(
                timestamp="2026-01-01T00:00:00+00:00",
                type="created",
                data={"state": "triage"},
            ),
        ]
        issue = _make_issue_with_log(entries, current_state="triage")
        result = build_timeline(issue)
        assert "◉" in result

    def test_past_states_use_open_marker(self) -> None:
        entries = [
            EventLogEntry(
                timestamp="2026-01-01T00:00:00+00:00",
                type="created",
                data={"state": "triage"},
            ),
            EventLogEntry(
                timestamp="2026-01-01T00:01:00+00:00",
                type="state_changed",
                data={"from": "triage", "to": "work", "outcome": "ready"},
            ),
        ]
        issue = _make_issue_with_log(entries, current_state="work")
        result = build_timeline(issue)
        assert "●" in result  # past state marker
        assert "◉" in result  # current state marker


class StatusHistoryApp(App[None]):
    def compose(self) -> ComposeResult:
        yield StatusHistory()


class TestStatusHistoryWidget:
    @pytest.mark.asyncio
    async def test_shows_placeholder_when_no_issue(self) -> None:
        app = StatusHistoryApp()
        async with app.run_test() as pilot:
            widget = app.query_one(StatusHistory)
            await pilot.pause()
            assert widget._current_issue_id is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/tui/test_status_history.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write StatusHistory implementation**

```python
# src/orca/tui/widgets/status_history.py
from __future__ import annotations

from datetime import UTC, datetime

from textual.containers import VerticalScroll
from textual.widgets import Static

from orca.engine.types import Issue, State


def _relative_time(timestamp: str) -> str:
    """Convert ISO timestamp to a human-readable relative time."""
    try:
        dt = datetime.fromisoformat(timestamp)
        now = datetime.now(UTC)
        delta = now - dt
        seconds = int(delta.total_seconds())
        if seconds < 60:
            return "now"
        if seconds < 3600:
            mins = seconds // 60
            return f"{mins}m ago"
        if seconds < 86400:
            hours = seconds // 3600
            return f"{hours}h ago"
        days = seconds // 86400
        return f"{days}d ago"
    except (ValueError, TypeError):
        return ""


def build_timeline(issue: Issue) -> str:
    """Build a text timeline from an issue's event log."""
    lines: list[str] = []
    states_seen: list[tuple[str, str, str | None]] = []  # (state, timestamp, outcome)

    # Extract state transitions from event log
    for entry in issue.event_log:
        if entry.type == "created":
            state_name = entry.data.get("state", issue.state)
            states_seen.append((state_name, entry.timestamp, None))
        elif entry.type == "state_changed":
            outcome = entry.data.get("outcome")
            to_state = entry.data.get("to", "")
            # Update the previous state's outcome
            if states_seen:
                prev = states_seen[-1]
                states_seen[-1] = (prev[0], prev[1], outcome)
            states_seen.append((to_state, entry.timestamp, None))

    # If no events found, just show current state
    if not states_seen:
        states_seen.append((issue.state, "", None))

    for i, (state_name, timestamp, outcome) in enumerate(states_seen):
        is_current = i == len(states_seen) - 1
        marker = "◉" if is_current else "●"
        time_str = _relative_time(timestamp) if timestamp else ""

        line = f"{marker} {state_name}"
        if time_str:
            line += f"  {time_str}"
        lines.append(line)

        if outcome:
            lines.append(f"  outcome: {outcome}")

        if not is_current:
            lines.append("    ↓")

    return "\n".join(lines)


class StatusHistory(VerticalScroll):
    """Right panel — shows state transition timeline for the selected issue."""

    DEFAULT_CSS = """
    StatusHistory {
        width: 3fr;
        padding: 1;
    }
    """

    def __init__(self) -> None:
        super().__init__(id="status-history")
        self._static = Static("", id="timeline-content")
        self._current_issue_id: str | None = None

    def compose(self):  # type: ignore[override]
        yield self._static

    def show_issue(self, issue_id: str, state: State) -> None:
        """Render the timeline for the given issue."""
        issue = state.issues.get(issue_id)
        if issue is None:
            self._current_issue_id = None
            self._static.update("")
            return

        self._current_issue_id = issue_id
        self._static.update(build_timeline(issue))

    def clear(self) -> None:
        self._current_issue_id = None
        self._static.update("")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/tui/test_status_history.py -v`
Expected: All 5 tests PASS.

- [ ] **Step 5: Run linters**

Run: `uv run ruff check src/orca/tui/widgets/status_history.py tests/tui/test_status_history.py && uv run mypy src/orca/tui/widgets/status_history.py`
Expected: No errors.

- [ ] **Step 6: Commit**

```bash
git add src/orca/tui/widgets/status_history.py tests/tui/test_status_history.py
git commit -m "feat: add StatusHistory widget with timeline rendering"
```

---

### Task 7: OrcaApp — Main Application

**Files:**
- Create: `src/orca/tui/app.py`
- Create: `tests/tui/test_app.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/tui/test_app.py
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from orca.engine.types import EventLogEntry, Issue, State
from orca.tui.app import OrcaApp


def _make_state(title: str = "Root Task", state_name: str = "triage") -> State:
    return State(
        issues={
            "root-1": Issue(
                fields={"title": title, "description": "Root description"},
                state=state_name,
                worker_active=False,
                decomposed_from=None,
                depends_on=[],
                event_log=[
                    EventLogEntry(
                        timestamp="2026-01-01T00:00:00+00:00",
                        type="created",
                        data={"state": state_name},
                    )
                ],
            ),
        },
        worker_queues={},
    )


def _write_state(path: Path, state: State) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state.to_dict(), indent=2))


class TestOrcaApp:
    @pytest.mark.asyncio
    async def test_app_mounts_three_panels(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run"
        _write_state(run_dir / "state.json", _make_state())

        app = OrcaApp(run_dir=run_dir, branch_name="test-branch")
        async with app.run_test() as pilot:
            await pilot.pause()

            from orca.tui.widgets.issue_tree import IssueTree
            from orca.tui.widgets.issue_detail import IssueDetail
            from orca.tui.widgets.status_history import StatusHistory

            assert len(app.query(IssueTree)) == 1
            assert len(app.query(IssueDetail)) == 1
            assert len(app.query(StatusHistory)) == 1

    @pytest.mark.asyncio
    async def test_app_loads_initial_state(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run"
        _write_state(run_dir / "state.json", _make_state("My Root"))

        app = OrcaApp(run_dir=run_dir, branch_name="test-branch")
        async with app.run_test() as pilot:
            await pilot.pause()

            from orca.tui.widgets.issue_tree import IssueTree

            tree = app.query_one(IssueTree)
            # Tree should have loaded the root issue
            assert len(tree.root.children) == 1
            assert "My Root" in str(tree.root.children[0].label)

    @pytest.mark.asyncio
    async def test_quit_binding(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run"
        _write_state(run_dir / "state.json", _make_state())

        app = OrcaApp(run_dir=run_dir, branch_name="test-branch")
        async with app.run_test() as pilot:
            await pilot.press("q")
            # App should exit without error
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/tui/test_app.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write OrcaApp implementation**

```python
# src/orca/tui/app.py
from __future__ import annotations

import time
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Footer, Header, Static

from orca.engine.types import State, StateMachineConfig
from orca.tui.messages import IssueSelected, StateUpdated
from orca.tui.state_reader import StateReader
from orca.tui.widgets.issue_detail import IssueDetail
from orca.tui.widgets.issue_tree import IssueTree
from orca.tui.widgets.status_history import StatusHistory

_STALE_THRESHOLD = 10.0  # seconds before "running" -> uncertain
_DEADLOCK_THRESHOLD = 30.0  # seconds before showing "deadlocked"


class OrcaApp(App[None]):
    """Orca TUI — interactive viewer for orchestrator runs."""

    CSS = """
    #main-panels {
        height: 1fr;
    }
    #status-bar {
        height: 1;
        background: $surface;
        color: $text-muted;
        padding: 0 1;
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
        """Force re-read state.json regardless of mtime."""
        self._reader.reset()
        self._poll_state()

    def on_state_updated(self, message: StateUpdated) -> None:
        tree = self.query_one(IssueTree)
        tree.update_state(message.state)

        # Update detail and history if an issue is selected
        if self._selected_issue_id:
            detail = self.query_one(IssueDetail)
            detail.show_issue(self._selected_issue_id, message.state)
            history = self.query_one(StatusHistory)
            history.show_issue(self._selected_issue_id, message.state)

        # Update subtitle with run status
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

        # Check if root issue is terminal
        root_id = self._find_root_issue()
        if root_id and root_id in self._state.issues:
            root = self._state.issues[root_id]
            if self._config and root.state in self._config.states:
                if self._config.states[root.state].terminal:
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/tui/test_app.py -v`
Expected: All 3 tests PASS.

- [ ] **Step 5: Run linters**

Run: `uv run ruff check src/orca/tui/app.py tests/tui/test_app.py && uv run mypy src/orca/tui/app.py`
Expected: No errors.

- [ ] **Step 6: Commit**

```bash
git add src/orca/tui/app.py tests/tui/test_app.py
git commit -m "feat: add OrcaApp with three-panel layout and polling"
```

---

### Task 8: CLI Entry Point — `orca watch`

**Files:**
- Modify: `src/orca/orchestrator/runner.py:249-261`

- [ ] **Step 1: Write the failing test**

```python
# Add to tests/tui/test_app.py or a new tests/tui/test_cli.py

# Manual verification: run `orca watch --help` and check it shows usage.
# This is an integration-level check — the unit tests above cover the app logic.
```

- [ ] **Step 2: Add the `watch` subcommand to runner.py**

In `src/orca/orchestrator/runner.py`, modify the `main()` function to add a `watch` subparser:

```python
def main() -> None:
    """CLI entry point: orca run <task_file> <branch_name>."""
    parser = argparse.ArgumentParser(prog="orca", description="Orca orchestrator CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run the orchestrator with a task file")
    run_parser.add_argument("task_file", type=Path, help="Path to the task file")
    run_parser.add_argument("branch_name", type=str, help="Git branch name for this run")

    watch_parser = subparsers.add_parser("watch", help="Watch orchestrator state in a TUI dashboard")
    watch_parser.add_argument("branch_name", type=str, help="Git branch name of the run to watch")

    args = parser.parse_args()

    if args.command == "run":
        asyncio.run(run(args.task_file, args.branch_name))
    elif args.command == "watch":
        try:
            from orca.tui.app import OrcaApp
        except ImportError:
            print("Error: textual is not installed. Install with: uv pip install 'orca[tui]'")
            raise SystemExit(1)

        repo_root = Path.cwd()
        run_dir = repo_root / ".orca" / "runs" / args.branch_name

        if not run_dir.exists():
            print(f"Error: no run found at {run_dir}")
            raise SystemExit(1)

        # Load config for terminal state detection
        config = None
        config_path = repo_root / "orca.yml"
        if config_path.exists():
            from orca.engine.config import parse_config
            config = parse_config(config_path.read_text())

        app = OrcaApp(run_dir=run_dir, branch_name=args.branch_name, config=config)
        app.run()
```

- [ ] **Step 3: Verify the command works**

Run: `uv run orca watch --help`
Expected: Shows usage with `branch_name` argument.

- [ ] **Step 4: Run all linters and type checks**

Run: `uv run ruff check src/orca/ && uv run mypy src/orca/`
Expected: No errors.

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest -v`
Expected: All tests pass, including all new TUI tests.

- [ ] **Step 6: Commit**

```bash
git add src/orca/orchestrator/runner.py
git commit -m "feat: add orca watch CLI command for TUI dashboard"
```

---

### Task 9: Manual Smoke Test

This task verifies the full TUI works end-to-end with real (or simulated) state data.

- [ ] **Step 1: Create a test state fixture**

Create a temporary state.json with a multi-level issue hierarchy to visually verify the TUI layout:

```bash
mkdir -p /tmp/orca-tui-test
cat > /tmp/orca-tui-test/state.json << 'EOF'
{
  "issues": {
    "root-1": {
      "fields": {"title": "Build API Service", "description": "# API Service\n\nImplement a REST API with:\n- User authentication\n- CRUD endpoints\n- Rate limiting"},
      "state": "work",
      "worker_active": true,
      "decomposed_from": null,
      "depends_on": [],
      "event_log": [
        {"timestamp": "2026-03-23T10:00:00+00:00", "type": "created", "data": {"state": "triage"}},
        {"timestamp": "2026-03-23T10:02:00+00:00", "type": "state_changed", "data": {"from": "triage", "to": "work", "outcome": "ready"}}
      ],
      "visit_counts": {"triage": 1, "work": 1},
      "hop_count": 1
    },
    "child-1": {
      "fields": {"title": "Auth Module", "description": "Implement JWT-based authentication"},
      "state": "review",
      "worker_active": false,
      "decomposed_from": "root-1",
      "depends_on": [],
      "event_log": [
        {"timestamp": "2026-03-23T10:03:00+00:00", "type": "created", "data": {"state": "triage"}},
        {"timestamp": "2026-03-23T10:04:00+00:00", "type": "state_changed", "data": {"from": "triage", "to": "work", "outcome": "ready"}},
        {"timestamp": "2026-03-23T10:10:00+00:00", "type": "state_changed", "data": {"from": "work", "to": "review", "outcome": "completed"}}
      ],
      "visit_counts": {"triage": 1, "work": 1, "review": 1},
      "hop_count": 2
    },
    "child-2": {
      "fields": {"title": "CRUD Endpoints", "description": "Build user and order endpoints"},
      "state": "work",
      "worker_active": true,
      "decomposed_from": "root-1",
      "depends_on": ["child-1"],
      "event_log": [
        {"timestamp": "2026-03-23T10:05:00+00:00", "type": "created", "data": {"state": "triage"}},
        {"timestamp": "2026-03-23T10:06:00+00:00", "type": "state_changed", "data": {"from": "triage", "to": "work", "outcome": "ready"}}
      ],
      "visit_counts": {"triage": 1, "work": 1},
      "hop_count": 1
    }
  },
  "worker_queues": {}
}
EOF
```

- [ ] **Step 2: Launch the TUI**

Run: `uv run python -c "from orca.tui.app import OrcaApp; from pathlib import Path; app = OrcaApp(run_dir=Path('/tmp/orca-tui-test'), branch_name='smoke-test'); app.run()"`

Verify:
- Three panels visible (tree, detail, history)
- Tree shows: Build API Service → Auth Module, CRUD Endpoints
- Worker spinner `⟳` visible on active issues
- Clicking an issue shows its markdown description in the center
- Right panel shows state transition timeline
- Press `q` to quit cleanly

- [ ] **Step 3: Final commit with any fixes**

If any adjustments were needed during smoke testing, commit them:

```bash
git add -A
git commit -m "fix: adjustments from TUI smoke testing"
```
