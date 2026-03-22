# Session Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Periodically render Claude Code session transcripts to markdown so orca users can browse `.orca/transcripts/` for worker progress and debugging.

**Architecture:** Worker extracts `session_id` from Claude's stream-json, returns it via `WorkerOutcome`. Orchestrator maintains a session manifest (`sessions.json`) and runs a background sync task every 3 minutes that invokes `claude-code-log --format md` to render native transcripts.

**Tech Stack:** Python 3.12, asyncio, `claude-code-log` (external CLI via subprocess)

**Spec:** `docs/superpowers/specs/2026-03-22-session-sync-design.md`

---

## File Structure

| File | Responsibility |
|------|---------------|
| Create: `src/orca/orchestrator/session_sync.py` | `SessionManifest` (read/write `sessions.json`) and `SessionSync` (render transcripts to markdown) |
| Create: `tests/orchestrator/test_session_sync.py` | Tests for manifest and sync logic |

**Note:** The spec references changes to `worker.py` and `orchestrator.py`, but those modules don't exist yet (they're part of the worker protocol plan). This plan implements only the session sync components — `SessionManifest` and `SessionSync` — as standalone, testable units. Integration with the orchestrator and worker happens when those modules are built.

**Sync/async note:** `SessionSync.sync()` is implemented as a synchronous method. It calls `subprocess.run()` which blocks. At orchestrator integration time, the async loop should call it via `asyncio.to_thread(sync.sync)` to avoid blocking the event loop. The final sync on orchestrator exit is also deferred to integration time — `sync()` is idempotent and can be called as a final sweep.

---

### Task 1: SessionManifest — append and read entries

**Files:**
- Create: `src/orca/orchestrator/session_sync.py`
- Create: `tests/orchestrator/test_session_sync.py`

The manifest manages `.orca/runs/{branch}/sessions.json` — a JSON file containing a list of session entries. Each entry records which issue/state a Claude session belongs to. Uses atomic writes (tmp + rename) consistent with `persistence.py`.

- [ ] **Step 1: Write the failing test for append and read**

```python
# tests/orchestrator/test_session_sync.py
from __future__ import annotations

from pathlib import Path

from orca.orchestrator.session_sync import SessionManifest


class TestSessionManifest:
    def test_append_and_read(self, tmp_path: Path) -> None:
        """Append an entry, read it back."""
        manifest = SessionManifest(tmp_path / "runs" / "main")
        manifest.append(
            issue_id="issue-1",
            state="implementing",
            session_id="sess-aaa",
            worktree_path="/tmp/wt/main",
            started_at="2026-03-22T10:00:00Z",
        )

        entries = manifest.read()

        assert len(entries) == 1
        assert entries[0]["issue_id"] == "issue-1"
        assert entries[0]["session_id"] == "sess-aaa"
        assert entries[0]["worktree_path"] == "/tmp/wt/main"
        assert entries[0]["completed_at"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/orchestrator/test_session_sync.py::TestSessionManifest::test_append_and_read -v`
Expected: FAIL — `ImportError: cannot import name 'SessionManifest'`

- [ ] **Step 3: Implement SessionManifest**

```python
# src/orca/orchestrator/session_sync.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class SessionManifest:
    """Read/write .orca/runs/{branch}/sessions.json."""

    def __init__(self, run_dir: Path) -> None:
        self.path = run_dir / "sessions.json"

    def read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return json.loads(self.path.read_text())  # type: ignore[no-any-return]

    def append(
        self,
        *,
        issue_id: str,
        state: str,
        session_id: str,
        worktree_path: str,
        started_at: str,
    ) -> None:
        entries = self.read()
        entries.append(
            {
                "issue_id": issue_id,
                "state": state,
                "session_id": session_id,
                "worktree_path": worktree_path,
                "started_at": started_at,
                "completed_at": None,
            }
        )
        self._write(entries)

    def mark_completed(self, session_id: str, completed_at: str) -> None:
        entries = self.read()
        for entry in entries:
            if entry["session_id"] == session_id:
                entry["completed_at"] = completed_at
                break
        self._write(entries)

    def _write(self, entries: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(entries, indent=2))
        tmp.rename(self.path)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/orchestrator/test_session_sync.py::TestSessionManifest::test_append_and_read -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/orca/orchestrator/session_sync.py tests/orchestrator/test_session_sync.py
git commit -m "feat: add SessionManifest for session tracking"
```

---

### Task 2: SessionManifest — multiple entries, mark_completed, edge cases

**Files:**
- Modify: `tests/orchestrator/test_session_sync.py`

- [ ] **Step 1: Write tests**

```python
    def test_multiple_entries(self, tmp_path: Path) -> None:
        """Append two entries, read both back."""
        manifest = SessionManifest(tmp_path / "runs" / "main")
        manifest.append(
            issue_id="issue-1",
            state="planning",
            session_id="sess-aaa",
            worktree_path="/tmp/wt/main",
            started_at="2026-03-22T10:00:00Z",
        )
        manifest.append(
            issue_id="issue-1",
            state="implementing",
            session_id="sess-bbb",
            worktree_path="/tmp/wt/main",
            started_at="2026-03-22T10:05:00Z",
        )

        entries = manifest.read()

        assert len(entries) == 2
        assert entries[0]["session_id"] == "sess-aaa"
        assert entries[1]["session_id"] == "sess-bbb"

    def test_mark_completed(self, tmp_path: Path) -> None:
        """Mark a session as completed, verify completed_at is set."""
        manifest = SessionManifest(tmp_path / "runs" / "main")
        manifest.append(
            issue_id="issue-1",
            state="implementing",
            session_id="sess-aaa",
            worktree_path="/tmp/wt/main",
            started_at="2026-03-22T10:00:00Z",
        )

        manifest.mark_completed("sess-aaa", "2026-03-22T10:10:00Z")

        entries = manifest.read()
        assert entries[0]["completed_at"] == "2026-03-22T10:10:00Z"

    def test_read_empty(self, tmp_path: Path) -> None:
        """Read from nonexistent file returns empty list."""
        manifest = SessionManifest(tmp_path / "runs" / "main")

        entries = manifest.read()

        assert entries == []

    def test_mark_completed_unknown_session(self, tmp_path: Path) -> None:
        """mark_completed with unknown session_id is a no-op."""
        manifest = SessionManifest(tmp_path / "runs" / "main")
        manifest.append(
            issue_id="issue-1",
            state="implementing",
            session_id="sess-aaa",
            worktree_path="/tmp/wt/main",
            started_at="2026-03-22T10:00:00Z",
        )

        manifest.mark_completed("nonexistent", "2026-03-22T10:10:00Z")

        entries = manifest.read()
        assert entries[0]["completed_at"] is None

    def test_atomic_write(self, tmp_path: Path) -> None:
        """No .tmp file left after write."""
        manifest = SessionManifest(tmp_path / "runs" / "main")
        manifest.append(
            issue_id="issue-1",
            state="implementing",
            session_id="sess-aaa",
            worktree_path="/tmp/wt/main",
            started_at="2026-03-22T10:00:00Z",
        )

        assert manifest.path.exists()
        assert not manifest.path.with_suffix(".tmp").exists()
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `uv run pytest tests/orchestrator/test_session_sync.py::TestSessionManifest -v`
Expected: PASS (all 6 tests)

- [ ] **Step 3: Commit**

```bash
git add tests/orchestrator/test_session_sync.py
git commit -m "test: add manifest tests for edge cases, atomic writes"
```

---

### Task 3: SessionSync — project path resolution with fallback

**Files:**
- Modify: `src/orca/orchestrator/session_sync.py`
- Modify: `tests/orchestrator/test_session_sync.py`

The sync needs to find native transcripts at `~/.claude/projects/{project-hash}/{session_id}.jsonl`. The project-hash is derived from the worktree path, with a fallback scan if the derived path doesn't exist.

- [ ] **Step 1: Write failing tests**

```python
from orca.orchestrator.session_sync import SessionManifest, SessionSync


class TestSessionSync:
    def test_claude_projects_path(self) -> None:
        """Derive project hash from worktree path."""
        sync = SessionSync(
            run_dir=Path("/tmp/runs/main"),
            transcripts_dir=Path("/tmp/transcripts"),
        )

        result = sync.claude_projects_path(Path("/Users/alice/work/myproject"))

        expected = Path.home() / ".claude" / "projects" / "-Users-alice-work-myproject"
        assert result == expected

    def test_claude_projects_path_nested_worktree(self) -> None:
        """Worktree paths produce their own project hash."""
        sync = SessionSync(
            run_dir=Path("/tmp/runs/main"),
            transcripts_dir=Path("/tmp/transcripts"),
        )

        result = sync.claude_projects_path(
            Path("/Users/alice/work/myproject/.orca/worktrees/feat/db")
        )

        expected = (
            Path.home()
            / ".claude"
            / "projects"
            / "-Users-alice-work-myproject-.orca-worktrees-feat-db"
        )
        assert result == expected

    def test_find_transcript_direct_path(self, tmp_path: Path) -> None:
        """Find transcript at the derived project path."""
        sync = SessionSync(
            run_dir=tmp_path / "runs" / "main",
            transcripts_dir=tmp_path / "transcripts",
            claude_projects_root=tmp_path / "claude-projects",
        )
        # Create transcript at expected location
        projects_dir = tmp_path / "claude-projects" / "-tmp-worktrees-main"
        projects_dir.mkdir(parents=True)
        transcript = projects_dir / "sess-aaa.jsonl"
        transcript.write_text('{"type":"system"}\n')

        result = sync.find_transcript(
            session_id="sess-aaa",
            worktree_path=Path("/tmp/worktrees/main"),
        )

        assert result == transcript

    def test_find_transcript_fallback_scan(self, tmp_path: Path) -> None:
        """Fall back to scanning all project dirs when derived path is wrong."""
        sync = SessionSync(
            run_dir=tmp_path / "runs" / "main",
            transcripts_dir=tmp_path / "transcripts",
            claude_projects_root=tmp_path / "claude-projects",
        )
        # Create transcript in an unexpected project dir (simulates changed hash algo)
        other_dir = tmp_path / "claude-projects" / "some-other-hash"
        other_dir.mkdir(parents=True)
        transcript = other_dir / "sess-aaa.jsonl"
        transcript.write_text('{"type":"system"}\n')

        result = sync.find_transcript(
            session_id="sess-aaa",
            worktree_path=Path("/tmp/worktrees/main"),
        )

        assert result == transcript

    def test_find_transcript_not_found(self, tmp_path: Path) -> None:
        """Return None when transcript doesn't exist anywhere."""
        sync = SessionSync(
            run_dir=tmp_path / "runs" / "main",
            transcripts_dir=tmp_path / "transcripts",
            claude_projects_root=tmp_path / "claude-projects",
        )
        (tmp_path / "claude-projects").mkdir(parents=True)

        result = sync.find_transcript(
            session_id="sess-aaa",
            worktree_path=Path("/tmp/worktrees/main"),
        )

        assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/orchestrator/test_session_sync.py::TestSessionSync -v`
Expected: FAIL — `ImportError: cannot import name 'SessionSync'`

- [ ] **Step 3: Implement SessionSync with project path resolution and fallback**

Add to `src/orca/orchestrator/session_sync.py`:

```python
import logging

logger = logging.getLogger(__name__)


class SessionSync:
    """Render Claude Code session transcripts to markdown."""

    def __init__(
        self,
        run_dir: Path,
        transcripts_dir: Path,
        claude_projects_root: Path | None = None,
    ) -> None:
        self.manifest = SessionManifest(run_dir)
        self.transcripts_dir = transcripts_dir
        self.claude_projects_root = (
            claude_projects_root or Path.home() / ".claude" / "projects"
        )

    def claude_projects_path(self, worktree_path: Path) -> Path:
        """Derive ~/.claude/projects/{hash}/ from worktree path."""
        project_hash = str(worktree_path).replace("/", "-")
        return self.claude_projects_root / project_hash

    def find_transcript(
        self, *, session_id: str, worktree_path: Path
    ) -> Path | None:
        """Find native transcript, trying derived path then fallback scan."""
        filename = f"{session_id}.jsonl"

        # Try derived path first
        derived = self.claude_projects_path(worktree_path) / filename
        if derived.exists():
            return derived

        # Fallback: scan all project directories
        if self.claude_projects_root.exists():
            for project_dir in self.claude_projects_root.iterdir():
                if not project_dir.is_dir():
                    continue
                candidate = project_dir / filename
                if candidate.exists():
                    logger.info(
                        "Transcript %s found via fallback scan at %s",
                        session_id,
                        candidate,
                    )
                    return candidate

        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/orchestrator/test_session_sync.py::TestSessionSync -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/orca/orchestrator/session_sync.py tests/orchestrator/test_session_sync.py
git commit -m "feat: add SessionSync with project path resolution and fallback"
```

---

### Task 4: SessionSync — output path and needs_render logic

**Files:**
- Modify: `src/orca/orchestrator/session_sync.py`
- Modify: `tests/orchestrator/test_session_sync.py`

- [ ] **Step 1: Write failing tests**

```python
    def test_output_path(self) -> None:
        """Build .orca/transcripts/{issue_id}/{state}-{timestamp}.md"""
        sync = SessionSync(
            run_dir=Path("/tmp/runs/main"),
            transcripts_dir=Path("/tmp/transcripts"),
        )

        result = sync.output_path("issue-1", "implementing", "2026-03-22T10:36:00Z")

        expected = Path("/tmp/transcripts/issue-1/implementing-2026-03-22T10-36-00Z.md")
        assert result == expected

    def test_needs_render_no_target(self, tmp_path: Path) -> None:
        """Needs render when target markdown doesn't exist."""
        sync = SessionSync(
            run_dir=tmp_path / "runs" / "main",
            transcripts_dir=tmp_path / "transcripts",
        )
        entry: dict[str, Any] = {"completed_at": None}

        assert sync.needs_render(entry, tmp_path / "nonexistent.md")

    def test_needs_render_completed_and_exists(self, tmp_path: Path) -> None:
        """Skip render when completed and target exists."""
        sync = SessionSync(
            run_dir=tmp_path / "runs" / "main",
            transcripts_dir=tmp_path / "transcripts",
        )
        target = tmp_path / "output.md"
        target.write_text("rendered")
        entry: dict[str, Any] = {"completed_at": "2026-03-22T10:10:00Z"}

        assert not sync.needs_render(entry, target)

    def test_needs_render_still_running(self, tmp_path: Path) -> None:
        """Re-render when session still running even if target exists."""
        sync = SessionSync(
            run_dir=tmp_path / "runs" / "main",
            transcripts_dir=tmp_path / "transcripts",
        )
        target = tmp_path / "output.md"
        target.write_text("partial render")
        entry: dict[str, Any] = {"completed_at": None}

        assert sync.needs_render(entry, target)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/orchestrator/test_session_sync.py::TestSessionSync -v`
Expected: FAIL — `AttributeError: 'SessionSync' object has no attribute 'output_path'`

- [ ] **Step 3: Implement output_path and needs_render**

Add to `SessionSync`:

```python
    def output_path(self, issue_id: str, state: str, started_at: str) -> Path:
        """Build .orca/transcripts/{issue_id}/{state}-{timestamp}.md"""
        safe_ts = started_at.replace(":", "-")
        return self.transcripts_dir / issue_id / f"{state}-{safe_ts}.md"

    def needs_render(self, entry: dict[str, Any], target: Path) -> bool:
        """True if session is still running or completed but not yet rendered."""
        if not target.exists():
            return True
        return entry["completed_at"] is None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/orchestrator/test_session_sync.py::TestSessionSync -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/orca/orchestrator/session_sync.py tests/orchestrator/test_session_sync.py
git commit -m "feat: add output path building and render-skip logic"
```

---

### Task 5: SessionSync — sync method (renders transcripts via claude-code-log)

**Files:**
- Modify: `src/orca/orchestrator/session_sync.py`
- Modify: `tests/orchestrator/test_session_sync.py`

This is the core: read manifest, find native transcripts, invoke `claude-code-log`, write markdown. Tests use a fake filesystem with a mock subprocess.

- [ ] **Step 1: Write the failing tests**

```python
import subprocess
from typing import Any
from unittest.mock import patch


class TestSessionSyncSync:
    def test_sync_renders_new_session(self, tmp_path: Path) -> None:
        """Sync invokes claude-code-log for a session that needs rendering."""
        run_dir = tmp_path / "runs" / "main"
        transcripts_dir = tmp_path / "transcripts"
        claude_root = tmp_path / "claude-projects"
        sync = SessionSync(
            run_dir=run_dir,
            transcripts_dir=transcripts_dir,
            claude_projects_root=claude_root,
        )

        # Set up manifest with one entry
        sync.manifest.append(
            issue_id="issue-1",
            state="implementing",
            session_id="sess-aaa",
            worktree_path=str(tmp_path / "worktrees" / "main"),
            started_at="2026-03-22T10:00:00Z",
        )

        # Create the native transcript file
        projects_path = sync.claude_projects_path(tmp_path / "worktrees" / "main")
        projects_path.mkdir(parents=True, exist_ok=True)
        transcript = projects_path / "sess-aaa.jsonl"
        transcript.write_text('{"type":"system"}\n')

        expected_output = sync.output_path(
            "issue-1", "implementing", "2026-03-22T10:00:00Z"
        )

        with patch("orca.orchestrator.session_sync.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
            sync.sync()

        mock_run.assert_called_once_with(
            [
                "uv", "tool", "run", "claude-code-log",
                str(transcript),
                "--format", "md",
                "-o", str(expected_output),
            ],
            check=True,
            capture_output=True,
        )

    def test_sync_skips_completed_and_rendered(self, tmp_path: Path) -> None:
        """Sync skips sessions that are completed and already rendered."""
        run_dir = tmp_path / "runs" / "main"
        transcripts_dir = tmp_path / "transcripts"
        sync = SessionSync(
            run_dir=run_dir,
            transcripts_dir=transcripts_dir,
            claude_projects_root=tmp_path / "claude-projects",
        )

        sync.manifest.append(
            issue_id="issue-1",
            state="implementing",
            session_id="sess-aaa",
            worktree_path=str(tmp_path / "worktrees" / "main"),
            started_at="2026-03-22T10:00:00Z",
        )
        sync.manifest.mark_completed("sess-aaa", "2026-03-22T10:10:00Z")

        # Pre-create the rendered output
        output = sync.output_path("issue-1", "implementing", "2026-03-22T10:00:00Z")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("already rendered")

        with patch("orca.orchestrator.session_sync.subprocess.run") as mock_run:
            sync.sync()

        mock_run.assert_not_called()

    def test_sync_skips_missing_transcript(self, tmp_path: Path) -> None:
        """Sync skips sessions where native transcript doesn't exist."""
        run_dir = tmp_path / "runs" / "main"
        transcripts_dir = tmp_path / "transcripts"
        sync = SessionSync(
            run_dir=run_dir,
            transcripts_dir=transcripts_dir,
            claude_projects_root=tmp_path / "claude-projects",
        )
        (tmp_path / "claude-projects").mkdir(parents=True)

        sync.manifest.append(
            issue_id="issue-1",
            state="implementing",
            session_id="sess-aaa",
            worktree_path=str(tmp_path / "worktrees" / "main"),
            started_at="2026-03-22T10:00:00Z",
        )

        with patch("orca.orchestrator.session_sync.subprocess.run") as mock_run:
            sync.sync()  # should not raise

        mock_run.assert_not_called()

    def test_sync_continues_on_per_entry_failure(self, tmp_path: Path) -> None:
        """If one entry fails, remaining entries are still processed."""
        run_dir = tmp_path / "runs" / "main"
        transcripts_dir = tmp_path / "transcripts"
        claude_root = tmp_path / "claude-projects"
        sync = SessionSync(
            run_dir=run_dir,
            transcripts_dir=transcripts_dir,
            claude_projects_root=claude_root,
        )

        # Two entries
        for sid in ["sess-aaa", "sess-bbb"]:
            sync.manifest.append(
                issue_id=f"issue-{sid}",
                state="implementing",
                session_id=sid,
                worktree_path=str(tmp_path / "worktrees" / "main"),
                started_at="2026-03-22T10:00:00Z",
            )
            projects_path = sync.claude_projects_path(tmp_path / "worktrees" / "main")
            projects_path.mkdir(parents=True, exist_ok=True)
            (projects_path / f"{sid}.jsonl").write_text('{"type":"system"}\n')

        with patch("orca.orchestrator.session_sync.subprocess.run") as mock_run:
            # First call fails, second succeeds
            mock_run.side_effect = [
                subprocess.CalledProcessError(1, "claude-code-log"),
                subprocess.CompletedProcess(args=[], returncode=0),
            ]
            sync.sync()  # should not raise

        assert mock_run.call_count == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/orchestrator/test_session_sync.py::TestSessionSyncSync -v`
Expected: FAIL — `AttributeError: 'SessionSync' object has no attribute 'sync'`

- [ ] **Step 3: Implement sync method**

Add to `session_sync.py` (top-level import):

```python
import subprocess
```

Add to `SessionSync`:

```python
    def sync(self) -> None:
        """Render new/updated session transcripts to markdown."""
        entries = self.manifest.read()
        for entry in entries:
            try:
                self._sync_entry(entry)
            except Exception:
                logger.exception(
                    "Failed to render session %s", entry.get("session_id")
                )

    def _sync_entry(self, entry: dict[str, Any]) -> None:
        target = self.output_path(
            entry["issue_id"], entry["state"], entry["started_at"]
        )
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
        subprocess.run(
            [
                "uv", "tool", "run", "claude-code-log",
                str(transcript),
                "--format", "md",
                "-o", str(target),
            ],
            check=True,
            capture_output=True,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/orchestrator/test_session_sync.py::TestSessionSyncSync -v`
Expected: PASS

- [ ] **Step 5: Run all tests**

Run: `uv run pytest tests/orchestrator/test_session_sync.py -v`
Expected: PASS (all tests)

- [ ] **Step 6: Run linter and type checker**

Run: `uv run ruff check src/orca/orchestrator/session_sync.py tests/orchestrator/test_session_sync.py && uv run mypy src/orca/orchestrator/session_sync.py`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/orca/orchestrator/session_sync.py tests/orchestrator/test_session_sync.py
git commit -m "feat: add sync method — renders transcripts via claude-code-log"
```

---

### Task 6: Update orchestrator exports

**Files:**
- Modify: `src/orca/orchestrator/__init__.py`

- [ ] **Step 1: Read current exports**

Read `src/orca/orchestrator/__init__.py` to see existing exports.

- [ ] **Step 2: Add session_sync exports**

Add to `__init__.py`:

```python
from orca.orchestrator.session_sync import SessionManifest, SessionSync
```

(Adjust based on what's already exported — the current `__init__.py` may only have a docstring.)

- [ ] **Step 3: Run type checker**

Run: `uv run mypy src/orca/orchestrator/`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/orca/orchestrator/__init__.py
git commit -m "chore: export SessionManifest and SessionSync from orchestrator"
```
