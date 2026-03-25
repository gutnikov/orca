# Pty-Based Worker Output Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the JSONL transcript pipeline with direct pty-based worker spawning, rendering live terminal output in the TUI.

**Architecture:** Workers spawn in pseudo-terminals via `os.openpty()`. A `pyte.HistoryScreen` emulates the terminal in-memory. The TUI renders screen state via Rich `Text` objects. Completed sessions freeze their screen buffer for later viewing.

**Tech Stack:** Python 3.12, pyte (VT100 emulator), Rich (styling), Textual (TUI framework)

**Spec:** `docs/superpowers/specs/2026-03-25-pty-worker-output-design.md`

---

## File Structure

### New Files
| File | Responsibility |
|------|---------------|
| `src/orca/orchestrator/pty_session.py` | Pty lifecycle, pyte screen, async read loop, snapshot |
| `src/orca/tui/widgets/terminal_view.py` | TUI widget: live rendering + frozen display |
| `tests/orchestrator/test_pty_session.py` | PtySession unit tests |
| `tests/tui/test_terminal_view.py` | TerminalView widget tests |

### Modified Files
| File | Change |
|------|--------|
| `src/orca/orchestrator/worker.py` | Replace piped subprocess with PtySession in `execute()` |
| `src/orca/orchestrator/orchestrator.py` | Add pty/frozen registries, wire snapshot on completion |
| `src/orca/orchestrator/runner.py` | Pass registries from orchestrator to TUI app |
| `src/orca/tui/app.py` | Accept registries, route worker selection to TerminalView |
| `src/orca/tui/messages.py` | No changes needed (existing `WorkerRunSelected` suffices) |
| `src/orca/tui/widgets/issue_detail.py` | Remove transcript methods (Phase 3) |
| `src/orca/orchestrator/session_sync.py` | Remove `claude_session_id` handling (Phase 3) |
| `src/orca/orchestrator/transcript.py` | Delete entirely (Phase 3) |
| `pyproject.toml` | Add `pyte` dependency |

---

## Phase 1: Add New Components (Additive Only)

### Task 1: Add pyte dependency

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add pyte to dependencies**

In `pyproject.toml`, add `pyte` to the `dependencies` list.

- [ ] **Step 2: Install and verify**

Run: `uv sync && uv run python -c "import pyte; print(pyte.__version__)"`
Expected: version string printed, no errors

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: add pyte dependency for terminal emulation"
```

---

### Task 2: Implement PtySession core (spawn, read_loop, close)

**Files:**
- Create: `src/orca/orchestrator/pty_session.py`
- Create: `tests/orchestrator/test_pty_session.py`

- [ ] **Step 1: Write failing test — spawn and read output**

```python
# tests/orchestrator/test_pty_session.py
from __future__ import annotations

import asyncio

import pytest

from orca.orchestrator.pty_session import PtySession


@pytest.mark.asyncio()
async def test_spawn_and_read_output() -> None:
    """Spawn echo via pty, verify pyte screen captures the output."""
    session = PtySession(cols=80, rows=24)
    await session.spawn("python3", ["-c", 'print("hello pty")'], cwd=".")
    read_task = asyncio.create_task(session.read_loop())
    await asyncio.sleep(0.5)  # let process finish and output drain
    read_task.cancel()
    try:
        await read_task
    except asyncio.CancelledError:
        pass

    # Check that "hello pty" appears somewhere in the screen buffer
    screen_text = ""
    for row in range(session.screen.lines):
        line = session.screen.display[row].rstrip()
        if line:
            screen_text += line + "\n"
    assert "hello pty" in screen_text
    session.close()


@pytest.mark.asyncio()
async def test_alive_property() -> None:
    """Session reports alive correctly."""
    session = PtySession(cols=80, rows=24)
    await session.spawn("python3", ["-c", 'print("done")'], cwd=".")
    read_task = asyncio.create_task(session.read_loop())
    await asyncio.sleep(0.5)
    read_task.cancel()
    try:
        await read_task
    except asyncio.CancelledError:
        pass
    assert not session.alive
    session.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/orchestrator/test_pty_session.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement PtySession**

```python
# src/orca/orchestrator/pty_session.py
from __future__ import annotations

import asyncio
import errno
import fcntl
import os
import struct
import subprocess
import termios
from pathlib import Path

import pyte


_DEFAULT_HISTORY = 10_000


class PtySession:
    """Pty-backed subprocess with in-memory VT100 terminal emulator."""

    def __init__(self, cols: int = 120, rows: int = 40) -> None:
        self._cols = cols
        self._rows = rows
        self._stream = pyte.Stream()
        self.screen = pyte.HistoryScreen(cols, rows, history=_DEFAULT_HISTORY)
        self._stream.attach(self.screen)
        self._master_fd: int | None = None
        self._proc: subprocess.Popen[bytes] | None = None
        self._log_file: object | None = None

    @property
    def alive(self) -> bool:
        if self._proc is None:
            return False
        return self._proc.poll() is None

    @property
    def pid(self) -> int:
        if self._proc is None:
            raise RuntimeError("PtySession not spawned")
        return self._proc.pid

    async def spawn(
        self,
        cmd: str,
        args: list[str],
        cwd: str | Path,
        env: dict[str, str] | None = None,
        log_path: Path | None = None,
    ) -> None:
        master_fd, slave_fd = os.openpty()

        # Set terminal size on the slave
        winsize = struct.pack("HHHH", self._rows, self._cols, 0, 0)
        fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, winsize)

        # Set master to non-blocking
        flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
        fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

        spawn_env = os.environ.copy()
        spawn_env["TERM"] = "xterm-256color"
        if env:
            spawn_env.update(env)

        self._proc = subprocess.Popen(
            [cmd, *args],
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            cwd=str(cwd),
            env=spawn_env,
            close_fds=True,
            start_new_session=True,
        )

        # Close slave fd in parent — child has its own copy
        os.close(slave_fd)
        self._master_fd = master_fd

        if log_path is not None:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            self._log_file = open(log_path, "wb")  # noqa: SIM115

    async def read_loop(self) -> None:
        """Read from master fd, feed to pyte stream. Runs until EOF or cancel."""
        if self._master_fd is None:
            raise RuntimeError("PtySession not spawned")

        loop = asyncio.get_running_loop()
        fd = self._master_fd
        event = asyncio.Event()

        def _on_readable() -> None:
            event.set()

        loop.add_reader(fd, _on_readable)
        try:
            while True:
                await event.wait()
                event.clear()
                try:
                    data = os.read(fd, 65536)
                except OSError as e:
                    if e.errno == errno.EIO:
                        break  # child exited, pty closed
                    raise
                if not data:
                    break
                if self._log_file is not None:
                    self._log_file.write(data)  # type: ignore[union-attr]
                self._stream.feed(data.decode("utf-8", errors="replace"))
        finally:
            loop.remove_reader(fd)
            if self._log_file is not None:
                self._log_file.close()  # type: ignore[union-attr]
                self._log_file = None

    def close(self) -> None:
        if self._master_fd is not None:
            try:
                os.close(self._master_fd)
            except OSError:
                pass
            self._master_fd = None
        if self._proc is not None and self._proc.poll() is None:
            self._proc.kill()
            self._proc.wait()
        if self._log_file is not None:
            self._log_file.close()  # type: ignore[union-attr]
            self._log_file = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/orchestrator/test_pty_session.py -v`
Expected: 2 passed

- [ ] **Step 5: Run linters**

Run: `uv run ruff check src/orca/orchestrator/pty_session.py && uv run mypy src/orca/orchestrator/pty_session.py`
Expected: no errors (fix any that appear)

- [ ] **Step 6: Commit**

```bash
git add src/orca/orchestrator/pty_session.py tests/orchestrator/test_pty_session.py
git commit -m "feat: add PtySession with spawn, read_loop, and close"
```

---

### Task 3: Add resize and snapshot to PtySession

**Files:**
- Modify: `src/orca/orchestrator/pty_session.py`
- Modify: `tests/orchestrator/test_pty_session.py`

- [ ] **Step 1: Write failing test — resize**

```python
@pytest.mark.asyncio()
async def test_resize_updates_screen_and_pty() -> None:
    """Resize updates pyte screen dimensions and sends TIOCSWINSZ."""
    session = PtySession(cols=80, rows=24)
    await session.spawn("python3", ["-c", "import time; time.sleep(2)"], cwd=".")
    session.resize(120, 40)
    assert session.screen.columns == 120
    assert session.screen.lines == 40
    session.close()
```

- [ ] **Step 2: Write failing test — snapshot**

```python
@pytest.mark.asyncio()
async def test_snapshot_returns_rich_text_lines() -> None:
    """Snapshot converts pyte screen to list of Rich Text objects."""
    from rich.text import Text

    session = PtySession(cols=80, rows=24)
    await session.spawn("python3", ["-c", 'print("snapshot test")'], cwd=".")
    read_task = asyncio.create_task(session.read_loop())
    await asyncio.sleep(0.5)
    read_task.cancel()
    try:
        await read_task
    except asyncio.CancelledError:
        pass

    lines = session.snapshot()
    assert isinstance(lines, list)
    assert len(lines) > 0
    assert all(isinstance(line, Text) for line in lines)
    # At least one line should contain our output
    combined = "\n".join(str(line) for line in lines)
    assert "snapshot test" in combined
    session.close()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/orchestrator/test_pty_session.py -v`
Expected: 2 new tests FAIL (no resize/snapshot methods)

- [ ] **Step 4: Implement resize and snapshot**

Add to `PtySession` class in `src/orca/orchestrator/pty_session.py`:

```python
    def resize(self, cols: int, rows: int) -> None:
        """Resize terminal. Updates pyte screen and sends SIGWINCH to child."""
        self._cols = cols
        self._rows = rows
        self.screen.resize(rows, cols)
        if self._master_fd is not None:
            winsize = struct.pack("HHHH", rows, cols, 0, 0)
            fcntl.ioctl(self._master_fd, termios.TIOCSWINSZ, winsize)

    def snapshot(self) -> list[Text]:
        """Capture screen + scrollback as Rich Text objects."""
        lines: list[Text] = []

        # Scrollback history (oldest first)
        for history_line in self.screen.history.top:
            lines.append(self.pyte_line_to_rich(history_line, self._cols))

        # Current screen
        for row in range(self.screen.lines):
            row_data = self.screen.buffer[row]
            lines.append(self.pyte_line_to_rich(row_data, self.screen.columns))

        return lines

    @staticmethod
    def pyte_line_to_rich(row_data: dict[int, pyte.screens.Char], cols: int) -> Text:
        """Convert a pyte row (dict of column -> Char) to a Rich Text."""
        text = Text()
        if isinstance(row_data, dict):
            for col in range(cols):
                char = row_data.get(col, pyte.screens.Char(" "))
                style_parts: list[str] = []
                if char.fg and char.fg != "default":
                    style_parts.append(char.fg)
                if char.bg and char.bg != "default":
                    style_parts.append(f"on {char.bg}")
                if char.bold:
                    style_parts.append("bold")
                if char.italics:
                    style_parts.append("italic")
                if char.underscore:
                    style_parts.append("underline")
                style_str = " ".join(style_parts) if style_parts else ""
                text.append(char.data, style=style_str)
        return text
```

Add `from rich.text import Text` to imports.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/orchestrator/test_pty_session.py -v`
Expected: 4 passed

- [ ] **Step 6: Run linters**

Run: `uv run ruff check src/orca/orchestrator/pty_session.py && uv run mypy src/orca/orchestrator/pty_session.py`
Expected: no errors

- [ ] **Step 7: Commit**

```bash
git add src/orca/orchestrator/pty_session.py tests/orchestrator/test_pty_session.py
git commit -m "feat: add resize and snapshot to PtySession"
```

---

### Task 4: Test raw log file support in PtySession

**Files:**
- Modify: `tests/orchestrator/test_pty_session.py`

- [ ] **Step 1: Write test for log_path (already implemented in Task 2)**

```python
@pytest.mark.asyncio()
async def test_log_path_writes_raw_bytes(tmp_path: Path) -> None:
    """When log_path is provided, raw pty bytes are written to file."""
    log_file = tmp_path / "session.raw"
    session = PtySession(cols=80, rows=24)
    await session.spawn("python3", ["-c", 'print("logged output")'], cwd=".", log_path=log_file)
    read_task = asyncio.create_task(session.read_loop())
    await asyncio.sleep(0.5)
    read_task.cancel()
    try:
        await read_task
    except asyncio.CancelledError:
        pass

    session.close()
    assert log_file.exists()
    content = log_file.read_bytes()
    assert b"logged output" in content
```

- [ ] **Step 2: Run test to verify it passes**

Run: `uv run pytest tests/orchestrator/test_pty_session.py::test_log_path_writes_raw_bytes -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/orchestrator/test_pty_session.py
git commit -m "test: add log_path test for PtySession"
```

---

### Task 5: Implement TerminalView widget

**Files:**
- Create: `src/orca/tui/widgets/terminal_view.py`
- Create: `tests/tui/test_terminal_view.py`

- [ ] **Step 1: Write failing test — frozen mode rendering**

```python
# tests/tui/test_terminal_view.py
from __future__ import annotations

from rich.text import Text

from orca.tui.widgets.terminal_view import FrozenTerminal, TerminalView


def test_frozen_terminal_stores_lines() -> None:
    """FrozenTerminal is a simple container of Rich Text lines."""
    lines = [Text("line 1"), Text("line 2"), Text("line 3")]
    frozen = FrozenTerminal(lines=lines)
    assert len(frozen.lines) == 3
    assert str(frozen.lines[0]) == "line 1"


def test_terminal_view_show_frozen_sets_mode() -> None:
    """show_frozen sets the widget to frozen mode."""
    view = TerminalView()
    frozen = FrozenTerminal(lines=[Text("hello")])
    view.show_frozen(frozen)
    assert view._frozen is not None
    assert view._pty_session is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/tui/test_terminal_view.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement TerminalView**

```python
# src/orca/tui/widgets/terminal_view.py
from __future__ import annotations

from dataclasses import dataclass

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.events import Resize
from textual.widget import Widget
from textual.widgets import Static

from orca.orchestrator.pty_session import PtySession


@dataclass(frozen=True)
class FrozenTerminal:
    """Captured terminal state from a completed worker."""

    lines: list[Text]


_PLACEHOLDER = "*Select a worker run to view its terminal output*"


class TerminalView(VerticalScroll):
    """Displays live pty output or frozen terminal snapshots."""

    DEFAULT_CSS = """
    TerminalView {
        width: 1fr;
        padding: 0;
    }
    TerminalView Static {
        width: 1fr;
    }
    """

    def __init__(self) -> None:
        super().__init__(id="terminal-view")
        self._static = Static(_PLACEHOLDER)
        self._pty_session: PtySession | None = None
        self._frozen: FrozenTerminal | None = None
        self._timer_handle: object | None = None

    def compose(self) -> ComposeResult:
        yield self._static

    def show_live(self, session: PtySession) -> None:
        """Attach to a live PtySession and start rendering."""
        self._stop()
        self._pty_session = session
        self._frozen = None
        self._render_screen()
        self._timer_handle = self.set_interval(1 / 20, self._render_screen)  # 50ms

    def show_frozen(self, frozen: FrozenTerminal) -> None:
        """Display a frozen terminal snapshot."""
        self._stop()
        self._frozen = frozen
        self._pty_session = None
        content = Text("\n").join(frozen.lines) if frozen.lines else Text(_PLACEHOLDER)
        self._static.update(content)

    def show_placeholder(self) -> None:
        """Reset to placeholder state."""
        self._stop()
        self._static.update(_PLACEHOLDER)

    def _render_screen(self) -> None:
        """Render current pyte screen state to the Static widget."""
        if self._pty_session is None:
            return
        screen = self._pty_session.screen
        # Take a shallow copy of buffer rows to avoid RuntimeError if
        # the orchestrator thread mutates the buffer during iteration.
        rows_copy = {row: dict(screen.buffer[row]) for row in range(screen.lines)}
        lines: list[Text] = []
        for row in range(screen.lines):
            lines.append(PtySession.pyte_line_to_rich(rows_copy[row], screen.columns))
        content = Text("\n").join(lines)
        self._static.update(content)
        if self.max_scroll_y - self.scroll_y < 5:
            self.scroll_end(animate=False)

    def _stop(self) -> None:
        """Stop any active rendering."""
        if self._timer_handle is not None:
            self._timer_handle.stop()  # type: ignore[union-attr]
            self._timer_handle = None
        self._pty_session = None
        self._frozen = None

    def on_resize(self, event: Resize) -> None:
        """Propagate resize to live pty session."""
        if self._pty_session is not None:
            width = self.content_size.width
            height = self.content_size.height
            if width > 0 and height > 0:
                self._pty_session.resize(width, height)

    def clear(self) -> None:
        self.show_placeholder()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/tui/test_terminal_view.py -v`
Expected: 2 passed

- [ ] **Step 5: Run linters**

Run: `uv run ruff check src/orca/tui/widgets/terminal_view.py && uv run mypy src/orca/tui/widgets/terminal_view.py`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add src/orca/tui/widgets/terminal_view.py tests/tui/test_terminal_view.py
git commit -m "feat: add TerminalView widget with live and frozen modes"
```

---

### Task 6: Add pty registries to Orchestrator

**Files:**
- Modify: `src/orca/orchestrator/orchestrator.py`

- [ ] **Step 1: Add registry attributes to Orchestrator.__init__**

Add after the existing instance variables in `__init__`:

```python
import threading
from orca.orchestrator.pty_session import PtySession
from orca.tui.widgets.terminal_view import FrozenTerminal

# Pty registries for TUI terminal rendering (thread-safe access via _pty_lock)
self._pty_lock = threading.Lock()
self._pty_registry: dict[str, PtySession] = {}
self._frozen_registry: dict[str, FrozenTerminal] = {}
```

- [ ] **Step 2: Add public accessor properties**

```python
@property
def pty_lock(self) -> threading.Lock:
    return self._pty_lock

@property
def pty_registry(self) -> dict[str, PtySession]:
    return self._pty_registry

@property
def frozen_registry(self) -> dict[str, FrozenTerminal]:
    return self._frozen_registry
```

- [ ] **Step 3: Run linters and existing tests**

Run: `uv run ruff check src/orca/orchestrator/orchestrator.py && uv run mypy src/orca/orchestrator/orchestrator.py && uv run pytest tests/orchestrator/test_orchestrator.py -v`
Expected: all pass

- [ ] **Step 4: Commit**

```bash
git add src/orca/orchestrator/orchestrator.py
git commit -m "feat: add pty and frozen registries to Orchestrator"
```

---

### Task 7: Wire TerminalView into TUI app

**Files:**
- Modify: `src/orca/tui/app.py`
- Modify: `src/orca/tui/messages.py`

- [ ] **Step 1: Add registries to OrcaApp.__init__**

Update `OrcaApp.__init__` to accept optional registry references:

```python
import threading
from orca.orchestrator.pty_session import PtySession
from orca.tui.widgets.terminal_view import FrozenTerminal, TerminalView

def __init__(
    self,
    run_dir: Path,
    branch_name: str,
    config: StateMachineConfig | None = None,
    insights_enabled: bool = False,
    pty_registry: dict[str, PtySession] | None = None,
    frozen_registry: dict[str, FrozenTerminal] | None = None,
    pty_lock: threading.Lock | None = None,
) -> None:
    ...
    self._pty_registry = pty_registry or {}
    self._frozen_registry = frozen_registry or {}
    self._pty_lock = pty_lock or threading.Lock()
```

- [ ] **Step 2: Add TerminalView to compose layout**

Update `compose()` to include both `IssueDetail` and `TerminalView`:

```python
def compose(self) -> ComposeResult:
    yield Header()
    with Horizontal(id="main-panels"):
        yield IssueTree(insights_enabled=self._insights_enabled)
        yield IssueDetail(transcripts_dir=self._transcripts_dir)
        yield TerminalView()
    yield Footer()
```

Add CSS to hide TerminalView by default:

```python
CSS = """
#main-panels { height: 1fr; }
#terminal-view { display: none; }
"""
```

- [ ] **Step 3: Route worker selection to TerminalView**

Update `on_worker_run_selected` to check registries first:

```python
def on_worker_run_selected(self, message: WorkerRunSelected) -> None:
    detail = self.query_one(IssueDetail)
    terminal = self.query_one(TerminalView)

    # Check pty registries for live/frozen terminal
    with self._pty_lock:
        live_session = self._pty_registry.get(message.session_id)
        frozen = self._frozen_registry.get(message.session_id)

    if live_session is not None:
        detail.styles.display = "none"
        terminal.styles.display = "block"
        terminal.show_live(live_session)
    elif frozen is not None:
        detail.styles.display = "none"
        terminal.styles.display = "block"
        terminal.show_frozen(frozen)
    else:
        # Fall back to existing transcript pipeline
        terminal.styles.display = "none"
        detail.styles.display = "block"
        detail.show_transcript(
            message.session_id,
            active=message.active,
            worktree_path=message.worktree_path,
            claude_session_id=message.claude_session_id,
            state=message.state,
        )
```

Update `on_issue_selected` and `on_insights_selected` to switch back to IssueDetail:

```python
def on_issue_selected(self, message: IssueSelected) -> None:
    if self._state:
        terminal = self.query_one(TerminalView)
        terminal.styles.display = "none"
        detail = self.query_one(IssueDetail)
        detail.styles.display = "block"
        detail.show_issue(message.issue_id, self._state)

def on_insights_selected(self, message: InsightsSelected) -> None:
    terminal = self.query_one(TerminalView)
    terminal.styles.display = "none"
    detail = self.query_one(IssueDetail)
    detail.styles.display = "block"
    insights_path = self._run_dir / "insights.md"
    detail.show_insights(insights_path)
```

- [ ] **Step 4: Update scroll actions to handle both widgets**

```python
def action_scroll_detail_down(self) -> None:
    terminal = self.query_one(TerminalView)
    if terminal.styles.display != "none":
        terminal.scroll_down()
    else:
        self.query_one(IssueDetail).scroll_down()

def action_scroll_detail_up(self) -> None:
    terminal = self.query_one(TerminalView)
    if terminal.styles.display != "none":
        terminal.scroll_up()
    else:
        self.query_one(IssueDetail).scroll_up()

def action_focus_detail(self) -> None:
    terminal = self.query_one(TerminalView)
    if terminal.styles.display != "none":
        terminal.focus()
    else:
        self.query_one(IssueDetail).focus()
```

- [ ] **Step 5: Run linters and tests**

Run: `uv run ruff check src/orca/tui/ && uv run mypy src/orca/tui/ && uv run pytest tests/tui/ -v`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add src/orca/tui/app.py src/orca/tui/widgets/terminal_view.py
git commit -m "feat: wire TerminalView into TUI with registry-based routing"
```

---

### Task 8: Pass registries from runner to TUI

**Files:**
- Modify: `src/orca/orchestrator/runner.py`

- [ ] **Step 1: Pass orchestrator registries to OrcaApp**

In `runner.py`, after creating the orchestrator (around line 326-339), pass registries to the TUI:

```python
app = OrcaApp(
    run_dir=run_dir,
    branch_name=branch_name,
    config=config,
    insights_enabled=args.insights,
    pty_registry=orchestrator.pty_registry,
    frozen_registry=orchestrator.frozen_registry,
    pty_lock=orchestrator.pty_lock,
)
```

**Key restructuring required:** The orchestrator is currently created inside `run()` (the async function called by `asyncio.run()` in the daemon thread). The registries live on the `Orchestrator` instance, so the TUI can't access them until the orchestrator exists. Solution: create the registries + lock as standalone objects in the main thread, pass them to both the orchestrator (via constructor) and the TUI app. The `Orchestrator.__init__` accepts optional `pty_registry`, `frozen_registry`, and `pty_lock` params. When provided, it uses them instead of creating its own.

Concrete changes to `runner.py`:
1. Before the daemon thread starts, create the shared objects:
   ```python
   import threading
   pty_lock = threading.Lock()
   pty_registry: dict[str, PtySession] = {}
   frozen_registry: dict[str, FrozenTerminal] = {}
   ```
2. Pass them into `run()` via closure or arguments
3. Inside `run()`, pass them to `Orchestrator()`
4. On the main thread, pass them to `OrcaApp()`

- [ ] **Step 2: Run linters**

Run: `uv run ruff check src/orca/orchestrator/runner.py && uv run mypy src/orca/orchestrator/runner.py`
Expected: no errors

- [ ] **Step 3: Commit**

```bash
git add src/orca/orchestrator/runner.py
git commit -m "feat: pass pty registries from orchestrator to TUI app"
```

---

## Phase 2: Switch Worker to Pty

### Task 9: Replace piped subprocess with PtySession in worker

**Files:**
- Modify: `src/orca/orchestrator/worker.py`
- Modify: `tests/orchestrator/test_worker.py`

- [ ] **Step 1: Write failing test — pty-based execute**

```python
@pytest.mark.asyncio()
async def test_execute_uses_pty_session(tmp_path: Path) -> None:
    """Worker execute spawns via PtySession and reads result.json."""
    result_path = tmp_path / "result.json"
    workdir = tmp_path / "work"
    workdir.mkdir()

    # Write a result file that the "worker" will produce
    result_data = {"outcome": "done", "summary": "test passed"}
    result_path.write_text(json.dumps(result_data))

    worker = ClaudeCodeWorker(repo_root=tmp_path)
    # We need to mock the actual claude CLI call since it won't be available in tests
    # Test that the PtySession integration path works structurally
    ...
```

Note: The actual worker test will need to mock `PtySession.spawn` since `claude` CLI won't be available in CI. The key behavior to test is that `execute()` creates a `PtySession`, runs `read_loop`, waits for process exit, and reads `result.json`.

- [ ] **Step 2: Modify ClaudeCodeWorker.execute() to accept and use PtySession**

The orchestrator (Task 10) creates the `PtySession` and passes it to `execute()`. The worker uses it instead of `asyncio.create_subprocess_exec`:

1. Accept `pty_session: PtySession | None = None` parameter
2. If `pty_session` is provided, spawn `claude -p - --max-turns 50 --permission-mode bypassPermissions` via `pty_session.spawn()`. The `-p -` flag tells Claude to read the prompt from stdin. Write the rendered prompt to the pty master fd, then send EOF (`\x04`).
3. Run `pty_session.read_loop()` as concurrent task
4. Monitor for inactivity by tracking last byte time
5. On process exit: read `result.json` as before
6. Return `WorkerSuccess`/`WorkerFailure` with `session_id=None`
7. If `pty_session` is None, fall back to the existing piped subprocess path (for backward compatibility during migration)

Key changes to `execute()`:
- Add `pty_session` parameter to signature and `Worker` protocol
- When using pty: no `--print`, no `--output-format stream-json`, no `--verbose`
- When using pty: no JSONL session log, no `session_id` extraction
- Keep `execute_raw()` unchanged (insights stays piped)

- [ ] **Step 3: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: all pass

- [ ] **Step 4: Run linters**

Run: `uv run ruff check src/orca/orchestrator/worker.py && uv run mypy src/orca/orchestrator/worker.py`
Expected: no errors

- [ ] **Step 5: Commit**

```bash
git add src/orca/orchestrator/worker.py tests/orchestrator/test_worker.py
git commit -m "feat: replace piped subprocess with PtySession in ClaudeCodeWorker"
```

---

### Task 10: Wire PtySession into orchestrator lifecycle

**Files:**
- Modify: `src/orca/orchestrator/orchestrator.py`

- [ ] **Step 1: Register PtySession on worker spawn**

In `_spawn_worker()`, after creating the task, store the pty session reference. This requires the worker to expose its `PtySession` after `execute()` starts. Since `execute()` is async, we need a callback or shared reference pattern.

Approach: The orchestrator creates the `PtySession` and passes it to the worker, rather than the worker creating it internally. This gives the orchestrator control over the registry.

Update `_run_worker()`:

```python
async def _run_worker(self, effect, worker, prompt_template, tracking_id):
    workdir = await self._ensure_worktree(effect.issue_id)
    # ... existing workdir/result_path logic ...

    # Create PtySession and register it (skip in headless mode)
    from orca.orchestrator.pty_session import PtySession
    pty_session = PtySession(cols=120, rows=40)

    # Optionally write raw bytes to session log for debugging
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    log_dir = workdir / ".orca" / "sessions"
    log_path = log_dir / f"{effect.state}-{timestamp}.raw"

    with self._pty_lock:
        self._pty_registry[tracking_id] = pty_session

    try:
        outcome = await worker.execute(
            effect, workdir, result_path, prompt_path, pty_session=pty_session, log_path=log_path
        )
    finally:
        # Snapshot and move to frozen registry. Guard snapshot() —
        # if pyte screen is in a bad state after a crash, don't lose cleanup.
        with self._pty_lock:
            self._pty_registry.pop(tracking_id, None)
            try:
                frozen_lines = pty_session.snapshot()
            except Exception:
                frozen_lines = []
            from orca.tui.widgets.terminal_view import FrozenTerminal
            self._frozen_registry[tracking_id] = FrozenTerminal(lines=frozen_lines)
        pty_session.close()

    return outcome
```

- [ ] **Step 2: Update Worker protocol to accept optional PtySession**

In `worker.py`, update the `Worker` protocol and `ClaudeCodeWorker.execute()` signature:

```python
from orca.orchestrator.pty_session import PtySession

class Worker(Protocol):
    async def execute(
        self,
        effect: DispatchWorkerEffect,
        workdir: Path,
        result_path: Path,
        prompt_path: Path | None = None,
        inactivity_timeout: int | None = None,
        pty_session: PtySession | None = None,
        log_path: Path | None = None,
    ) -> WorkerOutcome: ...
```

- [ ] **Step 3: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: all pass

- [ ] **Step 4: Commit**

```bash
git add src/orca/orchestrator/orchestrator.py src/orca/orchestrator/worker.py
git commit -m "feat: wire PtySession lifecycle into orchestrator spawn/complete flow"
```

---

## Phase 3: Remove Old Transcript Pipeline

### Task 11: Remove transcript code from IssueDetail

**Files:**
- Modify: `src/orca/tui/widgets/issue_detail.py`
- Modify: `tests/tui/test_issue_detail.py`

- [ ] **Step 1: Remove transcript methods from IssueDetail**

Remove from `issue_detail.py`:
- `_extract_claude_session_id()` function (lines 17-43)
- `show_transcript()` method
- `_find_jsonl()` static method
- `_refresh_jsonl()` method
- JSONL-related instance variables (`_jsonl_path`, `_jsonl_offset`, `_jsonl_last_type`, `_rendered_md`)
- `refresh_transcript()` method (keep only the `_refresh_md()` path for insights)
- Remove `json`, `re` imports if no longer used
- Remove `transcripts_dir` constructor parameter

Keep: `show_issue()`, `show_insights()`, `_refresh_md()`, `clear()`

- [ ] **Step 2: Update tests**

Remove transcript-related tests from `tests/tui/test_issue_detail.py`. Keep issue display and insights tests.

- [ ] **Step 3: Update app.py**

Remove `transcripts_dir` from `IssueDetail` constructor call. Remove the transcript fallback path from `on_worker_run_selected` (all workers now go through TerminalView or show a placeholder).

- [ ] **Step 4: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: all pass

- [ ] **Step 5: Run linters**

Run: `uv run ruff check src/orca/tui/ && uv run mypy src/orca/tui/`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add src/orca/tui/widgets/issue_detail.py src/orca/tui/app.py tests/tui/test_issue_detail.py
git commit -m "refactor: remove transcript rendering from IssueDetail"
```

---

### Task 12: Remove transcript.py and session sync transcript code

**Files:**
- Delete: `src/orca/orchestrator/transcript.py`
- Delete: `tests/orchestrator/test_transcript.py`
- Modify: `src/orca/orchestrator/session_sync.py`
- Modify: `src/orca/orchestrator/orchestrator.py`
- Modify: `tests/orchestrator/test_session_sync.py`

- [ ] **Step 1: Update insights worker to not depend on transcripts**

In `orchestrator.py`, update `_run_insights_once()`: replace the `gather_transcripts()` call with an empty dict (or pass frozen terminal snapshots converted to plain text). The insights worker already handles missing transcripts gracefully.

```python
# Before:
transcripts = gather_transcripts(transcripts_dir, sessions) if transcripts_dir.exists() else {}
# After:
transcripts: dict[str, str] = {}  # Transcripts removed; insights uses state data only
```

Remove the `gather_transcripts` import from `orchestrator.py`.

- [ ] **Step 2: Delete transcript.py and its tests**

```bash
git rm src/orca/orchestrator/transcript.py tests/orchestrator/test_transcript.py
```

- [ ] **Step 4: Remove _sync_sessions_loop from orchestrator**

Remove the `_sync_sessions_loop()` method and its `asyncio.create_task` call from the orchestrator's `run()` method.

- [ ] **Step 5: Remove claude_session_id from session_sync**

In `session_sync.py`:
- Remove `backfill_claude_session_ids()` method
- Remove `claude_session_id` parameter from `mark_completed()`
- Remove `claude_session_id` field handling from manifest entries

Update `orchestrator.py` line 471:
```python
# Before:
self._session_sync.manifest.mark_completed(tracking_id, ts, claude_session_id=outcome.session_id)
# After:
self._session_sync.manifest.mark_completed(tracking_id, ts)
```

- [ ] **Step 6: Drop session_id from WorkerSuccess/WorkerFailure**

In `worker.py`, remove `session_id` field from both dataclasses. Update all return sites.

- [ ] **Step 7: Update all tests**

Fix any tests referencing removed fields or methods.

- [ ] **Step 8: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: all pass

- [ ] **Step 9: Run linters**

Run: `uv run ruff check . && uv run mypy src/`
Expected: no errors

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "refactor: remove JSONL transcript pipeline and session_id tracking"
```

---

### Task 13: Remove JSONL session log creation from worker

**Files:**
- Modify: `src/orca/orchestrator/worker.py`

- [ ] **Step 1: Remove session log creation from execute()**

In `ClaudeCodeWorker.execute()`, remove:
- Session log path creation (`sessions_dir`, `session_log_path`)
- The `with session_log_path.open("wb") as log_file:` block
- All JSONL writing/parsing

The `log_path` parameter on `PtySession.spawn()` replaces this — raw bytes are optionally logged.

- [ ] **Step 2: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: all pass

- [ ] **Step 3: Run linters**

Run: `uv run ruff check src/orca/orchestrator/worker.py && uv run mypy src/orca/orchestrator/worker.py`
Expected: no errors

- [ ] **Step 4: Commit**

```bash
git add src/orca/orchestrator/worker.py
git commit -m "refactor: remove JSONL session log creation from worker"
```

---

### Task 14: Clean up transcripts directory management

**Files:**
- Modify: `src/orca/orchestrator/runner.py`
- Modify: `src/orca/orchestrator/session_sync.py`
- Modify: `src/orca/tui/app.py`

- [ ] **Step 1: Remove transcripts_dir from runner and app**

In `runner.py`: remove `transcripts_dir` creation and passing to `SessionSync`.
In `app.py`: remove `self._transcripts_dir` and any remaining references.
In `session_sync.py`: remove `transcripts_dir` parameter from `SessionSync.__init__` and the `sync()` method that renders transcripts.

- [ ] **Step 2: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: all pass

- [ ] **Step 3: Run linters**

Run: `uv run ruff check . && uv run mypy src/`
Expected: no errors

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor: remove transcripts directory management"
```

---

### Task 15: Final verification

- [ ] **Step 1: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: all 300+ tests pass

- [ ] **Step 2: Run all linters**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy src/`
Expected: all clean

- [ ] **Step 3: Verify no stale imports**

Run: `uv run ruff check . --select F401`
Expected: no unused imports

- [ ] **Step 4: Commit any final cleanup**

```bash
git add -A
git commit -m "chore: final cleanup after pty migration"
```
