# Incremental Transcript Streaming Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace batch transcript rendering with incremental append-only rendering and add live auto-refresh to the TUI, so users see worker activity within seconds instead of minutes.

**Architecture:** `render_incremental` reads only new JSONL bytes (tracking offset + last_type across calls), `SessionSync` appends markdown fragments to .md files every 5s, and `OrcaApp` polls the .md file every 3s for active sessions and pushes updates to `IssueDetail`.

**Tech Stack:** Python 3.12, Textual (TUI), existing JSONL → markdown rendering pipeline.

**Spec:** `docs/superpowers/specs/2026-03-23-incremental-transcript-streaming-design.md`

---

### Task 1: Add `render_incremental` to transcript.py

**Files:**
- Modify: `src/orca/orchestrator/transcript.py`
- Test: `tests/orchestrator/test_transcript.py`

- [ ] **Step 1: Write failing tests for `render_incremental`**

Add to `tests/orchestrator/test_transcript.py`:

```python
from orca.orchestrator.transcript import render_incremental


class TestRenderIncremental:
    def _write_jsonl(self, tmp_path: Path, entries: list[dict[str, object]]) -> Path:
        path = tmp_path / "test.jsonl"
        path.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
        return path

    def test_from_zero_matches_full_render(self, tmp_path: Path) -> None:
        """render_incremental from offset=0 produces same output as render_transcript."""
        entries = [
            {"type": "system", "subtype": "init", "session_id": "abc", "model": "claude"},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "Hello"}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "content": "OK"}]}},
        ]
        path = self._write_jsonl(tmp_path, entries)
        full = render_transcript(path)
        md, new_offset, new_last_type = render_incremental(path, 0, "")
        assert md == full
        assert new_offset > 0
        assert new_last_type == "user"

    def test_incremental_two_chunks(self, tmp_path: Path) -> None:
        """Two incremental calls produce same result as one full render."""
        path = tmp_path / "test.jsonl"
        # Write first entry
        entry1 = {"type": "assistant", "message": {"content": [{"type": "text", "text": "First"}]}}
        path.write_text(json.dumps(entry1) + "\n")
        md1, offset, last_type = render_incremental(path, 0, "")
        assert "First" in md1

        # Append second entry
        entry2 = {"type": "assistant", "message": {"content": [{"type": "text", "text": "Second"}]}}
        with open(path, "a") as f:
            f.write(json.dumps(entry2) + "\n")
        md2, offset2, last_type2 = render_incremental(path, offset, last_type)
        assert "Second" in md2
        assert offset2 > offset
        # Separator should be present since both are assistant type
        assert "---" in md2

    def test_no_new_data_returns_empty(self, tmp_path: Path) -> None:
        """When no new data exists, returns empty string."""
        entry = {"type": "assistant", "message": {"content": [{"type": "text", "text": "Hi"}]}}
        path = self._write_jsonl(tmp_path, [entry])
        _, offset, last_type = render_incremental(path, 0, "")
        # Read again at same offset — nothing new
        md, offset2, last_type2 = render_incremental(path, offset, last_type)
        assert md == ""
        assert offset2 == offset
        assert last_type2 == last_type

    def test_truncated_line_not_consumed(self, tmp_path: Path) -> None:
        """A partial line at EOF is not consumed — offset stays before it."""
        path = tmp_path / "test.jsonl"
        complete = json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "Done"}]}})
        partial = '{"type": "assistant", "message": {"content": [{"type": "te'
        path.write_text(complete + "\n" + partial)
        md, offset, _ = render_incremental(path, 0, "")
        assert "Done" in md
        # Offset should be right after the complete line's newline, not at EOF
        assert offset == len(complete.encode("utf-8")) + 1  # +1 for newline

    def test_file_smaller_than_offset(self, tmp_path: Path) -> None:
        """If file is smaller than offset, reset to 0."""
        path = self._write_jsonl(tmp_path, [
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "Hi"}]}}
        ])
        md, offset, last_type = render_incremental(path, 99999, "assistant")
        # Should have re-read from 0
        assert "Hi" in md
        assert offset > 0
        assert last_type == "assistant"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/orchestrator/test_transcript.py::TestRenderIncremental -v`
Expected: FAIL — `render_incremental` not defined.

- [ ] **Step 3: Implement `render_incremental`**

Add to `src/orca/orchestrator/transcript.py`:

```python
def render_incremental(
    jsonl_path: Path, byte_offset: int, last_type: str
) -> tuple[str, int, str]:
    """Read new JSONL entries starting from byte_offset, render to markdown.

    Returns:
        (new_markdown, new_byte_offset, new_last_type) — the rendered fragment
        for new entries only, the byte position after the last consumed line,
        and the updated last_type for continuity across calls.
    """
    file_size = jsonl_path.stat().st_size
    if byte_offset > file_size:
        # File was replaced/truncated — reset
        byte_offset = 0

    entries: list[dict[str, Any]] = []
    current_offset = byte_offset

    with open(jsonl_path, "rb") as f:
        f.seek(byte_offset)
        for raw_line in f:
            line = raw_line.decode("utf-8").strip()
            if not line:
                current_offset += len(raw_line)
                continue
            try:
                entries.append(json.loads(line))
                current_offset += len(raw_line)
            except json.JSONDecodeError:
                # Truncated line — stop here, don't advance offset past it
                break

    if not entries:
        return "", current_offset, last_type

    parts: list[str] = []
    for entry in entries:
        entry_type = entry.get("type", "")

        if entry_type == "system" and entry.get("subtype") == "init":
            parts.append(_render_session_header(entry))
            continue

        if entry_type == "assistant" and last_type == "assistant":
            parts.append("---")

        if entry_type == "assistant":
            parts.extend(_render_assistant(entry))
        elif entry_type == "user":
            parts.extend(_render_user(entry))
        elif entry_type == "result":
            parts.extend(_render_result(entry))

        if entry_type in ("assistant", "user", "result"):
            last_type = entry_type

    md = "\n\n".join(parts) + "\n" if parts else ""
    return md, current_offset, last_type
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/orchestrator/test_transcript.py -v`
Expected: All pass, including existing tests (unchanged).

- [ ] **Step 5: Run lints**

Run: `uv run ruff check src/orca/orchestrator/transcript.py && uv run mypy src/orca/orchestrator/transcript.py`
Expected: Clean.

- [ ] **Step 6: Commit**

```bash
git add src/orca/orchestrator/transcript.py tests/orchestrator/test_transcript.py
git commit -m "feat: add render_incremental for append-only transcript rendering"
```

---

### Task 2: Update SessionSync for incremental rendering

**Files:**
- Modify: `src/orca/orchestrator/session_sync.py`
- Test: `tests/orchestrator/test_session_sync.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/orchestrator/test_session_sync.py`:

```python
class TestSessionSyncIncremental:
    def _setup_sync(self, tmp_path: Path) -> tuple[SessionSync, Path, Path]:
        """Create a SessionSync with a transcript JSONL file ready to go."""
        run_dir = tmp_path / "runs" / "main"
        transcripts_dir = tmp_path / "transcripts"
        claude_root = tmp_path / "claude-projects"
        sync = SessionSync(run_dir=run_dir, transcripts_dir=transcripts_dir, claude_projects_root=claude_root)
        # Register a session
        sync.manifest.append(
            issue_id="issue-1", state="implementing", session_id="sess-inc",
            worktree_path=str(tmp_path / "worktrees" / "main"), started_at="2026-03-22T10:00:00Z",
        )
        # Create transcript location
        projects_path = sync.claude_projects_path(tmp_path / "worktrees" / "main")
        projects_path.mkdir(parents=True, exist_ok=True)
        jsonl_path = projects_path / "sess-inc.jsonl"
        return sync, jsonl_path, sync.output_path("sess-inc")

    def test_incremental_append(self, tmp_path: Path) -> None:
        """Two syncs produce correct combined markdown via incremental append."""
        sync, jsonl_path, output = self._setup_sync(tmp_path)
        # First JSONL entry
        jsonl_path.write_text(
            '{"type":"assistant","message":{"content":[{"type":"text","text":"Hello"}]}}\n'
        )
        sync.sync()
        assert output.exists()
        content1 = output.read_text()
        assert "Hello" in content1

        # Append second entry to JSONL
        with open(jsonl_path, "a") as f:
            f.write('{"type":"assistant","message":{"content":[{"type":"text","text":"World"}]}}\n')
        sync.sync()
        content2 = output.read_text()
        assert "Hello" in content2
        assert "World" in content2
        # Separator between two assistant turns
        assert "---" in content2

    def test_no_new_data_no_change(self, tmp_path: Path) -> None:
        """Sync with no new JSONL data does not modify the .md file."""
        sync, jsonl_path, output = self._setup_sync(tmp_path)
        jsonl_path.write_text(
            '{"type":"assistant","message":{"content":[{"type":"text","text":"Hello"}]}}\n'
        )
        sync.sync()
        mtime1 = output.stat().st_mtime
        import time; time.sleep(0.05)
        sync.sync()
        mtime2 = output.stat().st_mtime
        assert mtime1 == mtime2

    def test_completed_session_final_render(self, tmp_path: Path) -> None:
        """Completed session gets a final render to capture trailing entries."""
        sync, jsonl_path, output = self._setup_sync(tmp_path)
        jsonl_path.write_text(
            '{"type":"assistant","message":{"content":[{"type":"text","text":"Start"}]}}\n'
        )
        sync.sync()
        assert "Start" in output.read_text()

        # Append more data, then mark session completed
        with open(jsonl_path, "a") as f:
            f.write('{"type":"result","result":"Done!","duration_ms":5000}\n')
        sync.manifest.mark_completed("sess-inc", "2026-03-22T10:10:00Z")

        # This sync should capture the trailing "result" entry
        sync.sync()
        content = output.read_text()
        assert "Start" in content
        assert "Done!" in content

    def test_restart_truncates_stale_md(self, tmp_path: Path) -> None:
        """A fresh SessionSync (offset=0) truncates an existing .md before re-rendering."""
        sync, jsonl_path, output = self._setup_sync(tmp_path)
        jsonl_path.write_text(
            '{"type":"assistant","message":{"content":[{"type":"text","text":"Fresh"}]}}\n'
        )
        # Pre-create stale output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("STALE CONTENT\n")
        sync.sync()
        content = output.read_text()
        assert "Fresh" in content
        assert "STALE" not in content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/orchestrator/test_session_sync.py::TestSessionSyncIncremental -v`
Expected: FAIL — `_sync_entry` still uses full render.

- [ ] **Step 3: Implement incremental sync**

Modify `src/orca/orchestrator/session_sync.py`:

1. Add import: `from dataclasses import dataclass`
2. Replace import: `from orca.orchestrator.transcript import render_transcript` → `from orca.orchestrator.transcript import render_incremental`
3. Add `_SessionRenderState` dataclass after the imports.
4. Add `self._render_states: dict[str, _SessionRenderState] = {}` to `SessionSync.__init__`.
5. Replace `needs_render` and `_sync_entry` methods.

```python
@dataclass
class _SessionRenderState:
    byte_offset: int = 0
    last_type: str = ""


# In SessionSync.__init__, add:
#     self._render_states: dict[str, _SessionRenderState] = {}

def needs_render(self, entry: dict[str, Any], target: Path) -> bool:
    """True if session needs syncing: still running, or completed with unread bytes."""
    if not target.exists():
        return True
    if entry["completed_at"] is None:
        return True
    # Completed + .md exists: check if there are unread bytes (final render)
    session_id = entry.get("session_id", "")
    rs = self._render_states.get(session_id)
    if rs is None:
        return False  # No render state = never synced by us, skip
    # If we have render state, check if JSONL has more bytes than we've read
    transcript = self.find_transcript(
        session_id=session_id,
        worktree_path=Path(entry["worktree_path"]),
    )
    if transcript is None:
        return False
    return transcript.stat().st_size > rs.byte_offset

def _sync_entry(self, entry: dict[str, Any]) -> None:
    target = self.output_path(entry["session_id"])
    if not self.needs_render(entry, target):
        return

    transcript = self.find_transcript(
        session_id=entry["session_id"],
        worktree_path=Path(entry["worktree_path"]),
    )
    if transcript is None:
        logger.warning(
            "Native transcript not found for session %s",
            entry["session_id"],
        )
        return

    target.parent.mkdir(parents=True, exist_ok=True)
    session_id = entry["session_id"]
    rs = self._render_states.get(session_id)

    if rs is None:
        # First sync for this session — if stale .md exists, truncate it
        rs = _SessionRenderState()
        self._render_states[session_id] = rs
        if target.exists():
            target.write_text("")

    md, new_offset, new_last_type = render_incremental(transcript, rs.byte_offset, rs.last_type)

    if not md:
        return

    rs.byte_offset = new_offset
    rs.last_type = new_last_type

    if target.exists() and target.stat().st_size > 0:
        with open(target, "a") as f:
            f.write("\n\n" + md)
    else:
        target.write_text(md)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/orchestrator/test_session_sync.py -v`
Expected: All pass — both new and existing tests.

- [ ] **Step 5: Run lints**

Run: `uv run ruff check src/orca/orchestrator/session_sync.py && uv run mypy src/orca/orchestrator/session_sync.py`
Expected: Clean.

- [ ] **Step 6: Commit**

```bash
git add src/orca/orchestrator/session_sync.py tests/orchestrator/test_session_sync.py
git commit -m "feat: incremental transcript rendering in SessionSync"
```

---

### Task 3: Reduce sync interval from 180s to 5s

**Files:**
- Modify: `src/orca/orchestrator/orchestrator.py:241`

- [ ] **Step 1: Change the interval**

In `src/orca/orchestrator/orchestrator.py`, change line 242:

```python
# Before:
await asyncio.sleep(180)
# After:
await asyncio.sleep(5)
```

- [ ] **Step 2: Run existing tests**

Run: `uv run pytest tests/ -x -q`
Expected: All pass.

- [ ] **Step 3: Commit**

```bash
git add src/orca/orchestrator/orchestrator.py
git commit -m "feat: reduce transcript sync interval from 180s to 5s"
```

---

### Task 4: Add `active` flag to `WorkerRunSelected` message

**Files:**
- Modify: `src/orca/tui/messages.py:25-30`
- Modify: `src/orca/tui/widgets/issue_tree.py:157-158`
- Test: `tests/tui/test_issue_tree.py`

- [ ] **Step 1: Update `WorkerRunSelected` message**

In `src/orca/tui/messages.py`, change `WorkerRunSelected`:

```python
class WorkerRunSelected(Message):
    """Posted when the user highlights a worker-run leaf in the tree."""

    def __init__(self, session_id: str, active: bool) -> None:
        super().__init__()
        self.session_id = session_id
        self.active = active
```

- [ ] **Step 2: Update `IssueTree` to pass `active` flag**

In `src/orca/tui/widgets/issue_tree.py`, update `on_tree_node_highlighted` (line 157-158):

```python
elif data.startswith("session:"):
    session_id = data[8:]
    active = any(
        s.get("session_id") == session_id and s.get("completed_at") is None
        for s in self._sessions
    )
    self.post_message(WorkerRunSelected(session_id, active=active))
```

- [ ] **Step 3: Fix any existing tests that construct `WorkerRunSelected`**

Search `tests/` for `WorkerRunSelected(` and add `active=False` where needed.

Run: `uv run pytest tests/tui/ -v`
Expected: All pass.

- [ ] **Step 4: Commit**

```bash
git add src/orca/tui/messages.py src/orca/tui/widgets/issue_tree.py tests/tui/
git commit -m "feat: add active flag to WorkerRunSelected message"
```

---

### Task 5: TUI auto-refresh for active transcripts

**Files:**
- Modify: `src/orca/tui/app.py`
- Modify: `src/orca/tui/widgets/issue_detail.py`
- Test: `tests/tui/test_issue_detail.py`

- [ ] **Step 1: Add `refresh_transcript` to `IssueDetail`**

In `src/orca/tui/widgets/issue_detail.py`, add a method and track current transcript state:

```python
# Add to __init__:
self._current_transcript_path: Path | None = None
self._transcript_mtime: float = 0.0

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
```

Update `show_transcript` to track the path:

```python
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
```

Update `show_issue` to call `self.stop_auto_refresh()` at the top of the method (before the existing logic). Update `clear` similarly:

```python
def show_issue(self, issue_id: str, state: State) -> None:
    self.stop_auto_refresh()
    # ... existing code unchanged ...

def clear(self) -> None:
    self.stop_auto_refresh()
    self._markdown.update(_PLACEHOLDER)
```

- [ ] **Step 2: Add transcript poll timer to `OrcaApp`**

In `src/orca/tui/app.py`:

Add import: `from textual.timer import Timer`

Add to `__init__`:
```python
self._transcript_timer: Timer | None = None
```

Update `on_worker_run_selected`:
```python
def on_worker_run_selected(self, message: WorkerRunSelected) -> None:
    detail = self.query_one(IssueDetail)
    detail.show_transcript(message.session_id)
    # Manage transcript auto-refresh timer
    self._stop_transcript_timer()
    if message.active:
        self._transcript_timer = self.set_interval(3.0, self._poll_transcript)

def _poll_transcript(self) -> None:
    detail = self.query_one(IssueDetail)
    detail.refresh_transcript()

def _stop_transcript_timer(self) -> None:
    if self._transcript_timer is not None:
        self._transcript_timer.stop()
        self._transcript_timer = None
```

Update `on_issue_selected` to stop the timer:
```python
def on_issue_selected(self, message: IssueSelected) -> None:
    self._stop_transcript_timer()
    if self._state:
        detail = self.query_one(IssueDetail)
        detail.show_issue(message.issue_id, self._state)
```

- [ ] **Step 3: Write test for auto-refresh**

Add to `tests/tui/test_issue_detail.py`:

```python
@pytest.mark.asyncio
async def test_refresh_transcript_detects_change(self, tmp_path: Path) -> None:
    transcripts_dir = tmp_path / "transcripts"
    transcripts_dir.mkdir()
    md_path = transcripts_dir / "session-r.md"
    md_path.write_text("# Initial\n\nFirst content\n")

    class RefreshApp(App[None]):
        def compose(self) -> ComposeResult:
            yield IssueDetail(transcripts_dir=transcripts_dir)

    app = RefreshApp()
    async with app.run_test() as pilot:
        detail = app.query_one(IssueDetail)
        detail.show_transcript("session-r")
        await pilot.pause()
        mtime_before = detail._transcript_mtime
        assert mtime_before > 0
        # Modify the file (sleep ensures mtime changes)
        import time; time.sleep(0.05)
        md_path.write_text("# Initial\n\nFirst content\n\nSecond content\n")
        detail.refresh_transcript()
        await pilot.pause()
        # Verify mtime was updated (proving the change was detected)
        assert detail._transcript_mtime > mtime_before
```

- [ ] **Step 4: Run all tests**

Run: `uv run pytest tests/ -x -q`
Expected: All pass.

- [ ] **Step 5: Run lints**

Run: `uv run ruff check src/orca/tui/ && uv run mypy src/orca/tui/`
Expected: Clean.

- [ ] **Step 6: Commit**

```bash
git add src/orca/tui/app.py src/orca/tui/widgets/issue_detail.py tests/tui/test_issue_detail.py
git commit -m "feat: auto-refresh transcript panel for active sessions"
```

---

### Task 6: Final integration verification

- [ ] **Step 1: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: All pass.

- [ ] **Step 2: Run full lints**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy src/`
Expected: All clean.

- [ ] **Step 3: Commit any fixups if needed**
