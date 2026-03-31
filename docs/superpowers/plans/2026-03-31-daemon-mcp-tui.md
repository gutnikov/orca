# Daemon + MCP + Detachable TUI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform orca from a foreground CLI into a per-repo background daemon with MCP tools and an attachable TUI.

**Architecture:** New `daemon/` package wraps existing Orchestrators in an HTTP server on a Unix domain socket. New `cli/` package replaces `runner.py`'s argparse with subcommands. TUI refactored from filesystem-polling to HTTP client. MCP exposed via stdio shim that proxies to the daemon.

**Tech Stack:** Python 3.12, uvicorn (UDS), starlette, mcp (FastMCP), aiohttp, textual — all existing dependencies.

---

## File Structure

### New files

| File | Responsibility |
|------|----------------|
| `src/orca/daemon/__init__.py` | Package init |
| `src/orca/daemon/manager.py` | `RunManager`: creates/tracks Orchestrator instances, maps run_id → run state |
| `src/orca/daemon/server.py` | Starlette HTTP app, route registration, daemon main loop |
| `src/orca/daemon/lifecycle.py` | Daemonize, pidfile, socket cleanup, signal handling |
| `src/orca/daemon/mcp_tools.py` | MCP tool definitions using FastMCP, delegates to RunManager |
| `src/orca/daemon/http_api.py` | Internal HTTP endpoints for TUI (state polling, hot session, logs) |
| `src/orca/cli/__init__.py` | Package init |
| `src/orca/cli/main.py` | Top-level CLI dispatcher with subcommands |
| `src/orca/cli/daemon_cmd.py` | `orca daemon start/stop/status` |
| `src/orca/cli/run_cmd.py` | `orca run <task.md>` — submit to daemon |
| `src/orca/cli/tui_cmd.py` | `orca tui` — attach TUI |
| `src/orca/cli/mcp_cmd.py` | `orca mcp` — stdio-to-UDS bridge |
| `src/orca/cli/list_cmd.py` | `orca runs` / `orca logs` — quick CLI queries |
| `tests/daemon/__init__.py` | Test package |
| `tests/daemon/test_manager.py` | RunManager unit tests |
| `tests/daemon/test_lifecycle.py` | Daemon lifecycle tests |
| `tests/daemon/test_mcp_tools.py` | MCP tool handler tests |
| `tests/daemon/test_http_api.py` | HTTP API tests |
| `tests/cli/__init__.py` | Test package |
| `tests/cli/test_main.py` | CLI subcommand dispatch tests |
| `tests/cli/test_daemon_cmd.py` | daemon start/stop/status tests |
| `tests/cli/test_run_cmd.py` | run submission tests |

### Modified files

| File | Changes |
|------|---------|
| `src/orca/orchestrator/orchestrator.py` | Add `state` property, `stop()` method, `get_session_log()`, `set_hot_session()`/`set_cold_session()` |
| `src/orca/tui/app.py` | Replace `StateReader` with `DaemonClient`, add run list screen |
| `src/orca/tui/state_reader.py` | Rewrite to fetch state from daemon HTTP API instead of filesystem |
| `pyproject.toml` | Update entry point from `orca.orchestrator.runner:main` to `orca.cli.main:main` |

### Unchanged files

- `src/orca/engine/` — entire directory untouched
- `src/orca/orchestrator/worker.py`, `persistence.py`, `branches.py`, `worktree.py`, `session_sync.py`, `pty_session.py`, `template.py`, `validation.py`, `log.py`, `config_types.py`
- `src/orca/mcp_servers/` — Slack HITL stays internal

---

### Task 1: Orchestrator State Accessors

Add minimal public interface to `Orchestrator` so the daemon can read state and control runs without reaching into internals.

**Files:**
- Modify: `src/orca/orchestrator/orchestrator.py:45-90`
- Test: `tests/orchestrator/test_orchestrator.py`

- [ ] **Step 1: Write tests for new Orchestrator accessors**

Add to `tests/orchestrator/test_orchestrator.py`:

```python
class TestOrchestratorAccessors:
    async def test_state_property(self, tmp_path: Path) -> None:
        """Orchestrator.state returns current state."""
        config = parse_config(SIMPLE_CONFIG)
        state = State(issues={}, worker_queues={})
        create_event = CreateEvent(issue_id="issue-1", fields={"title": "Test"}, timestamp=_now())
        state, initial_effects = reduce(config, state, create_event, _counter(), _now)

        orchestrator = Orchestrator(
            config=config,
            state=state,
            root_branch="main",
            persistence=Persistence(tmp_path, "main"),
            branches=BranchMap(tmp_path, "main"),
            workers={"claude-code": MockWorker(outcomes={})},
            generate_id=_counter(),
            now=_now,
            worktree_mgr=FakeWorktreeManager(tmp_path),
        )
        assert orchestrator.state is state
        assert "issue-1" in orchestrator.state.issues

    async def test_config_property(self, tmp_path: Path) -> None:
        """Orchestrator.config returns the state machine config."""
        config = parse_config(SIMPLE_CONFIG)
        state = State(issues={}, worker_queues={})

        orchestrator = Orchestrator(
            config=config,
            state=state,
            root_branch="main",
            persistence=Persistence(tmp_path, "main"),
            branches=BranchMap(tmp_path, "main"),
            workers={"claude-code": MockWorker(outcomes={})},
            generate_id=_counter(),
            now=_now,
            worktree_mgr=FakeWorktreeManager(tmp_path),
        )
        assert orchestrator.config is config

    async def test_get_session_log_missing(self, tmp_path: Path) -> None:
        """get_session_log returns empty string for unknown issue."""
        config = parse_config(SIMPLE_CONFIG)
        state = State(issues={}, worker_queues={})
        orchestrator = Orchestrator(
            config=config,
            state=state,
            root_branch="main",
            persistence=Persistence(tmp_path, "main"),
            branches=BranchMap(tmp_path, "main"),
            workers={"claude-code": MockWorker(outcomes={})},
            generate_id=_counter(),
            now=_now,
            worktree_mgr=FakeWorktreeManager(tmp_path),
        )
        assert orchestrator.get_session_log("nonexistent") == ""

    async def test_get_session_log_reads_file(self, tmp_path: Path) -> None:
        """get_session_log reads from session log path."""
        config = parse_config(SIMPLE_CONFIG)
        state = State(issues={}, worker_queues={})
        orchestrator = Orchestrator(
            config=config,
            state=state,
            root_branch="main",
            persistence=Persistence(tmp_path, "main"),
            branches=BranchMap(tmp_path, "main"),
            workers={"claude-code": MockWorker(outcomes={})},
            generate_id=_counter(),
            now=_now,
            worktree_mgr=FakeWorktreeManager(tmp_path),
            session_log_paths={"track-1": str(tmp_path / "log.txt")},
        )
        (tmp_path / "log.txt").write_text("line1\nline2\nline3\nline4\nline5\n")
        result = orchestrator.get_session_log("track-1", tail=3)
        assert result == "line3\nline4\nline5\n"

    async def test_hot_cold_session(self, tmp_path: Path) -> None:
        """set_hot_session/set_cold_session update hot_sessions set."""
        hot: set[str] = set()
        config = parse_config(SIMPLE_CONFIG)
        state = State(issues={}, worker_queues={})
        orchestrator = Orchestrator(
            config=config,
            state=state,
            root_branch="main",
            persistence=Persistence(tmp_path, "main"),
            branches=BranchMap(tmp_path, "main"),
            workers={"claude-code": MockWorker(outcomes={})},
            generate_id=_counter(),
            now=_now,
            worktree_mgr=FakeWorktreeManager(tmp_path),
            hot_sessions=hot,
        )
        orchestrator.set_hot_session("sess-1")
        assert "sess-1" in hot
        orchestrator.set_cold_session("sess-1")
        assert "sess-1" not in hot
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/orchestrator/test_orchestrator.py::TestOrchestratorAccessors -v`
Expected: FAIL — `state` property, `config` property, `get_session_log`, `set_hot_session`, `set_cold_session` don't exist.

- [ ] **Step 3: Implement accessors on Orchestrator**

In `src/orca/orchestrator/orchestrator.py`, add after the `__init__` method (around line 90):

```python
    @property
    def state(self) -> State:
        """Current state machine state."""
        return self._state

    @property
    def config(self) -> StateMachineConfig:
        """State machine configuration."""
        return self._config

    def get_session_log(self, tracking_id: str, tail: int = 100) -> str:
        """Read the last N lines of a worker session log.

        Returns empty string if the session or log file is not found.
        """
        log_path = self._session_log_paths.get(tracking_id)
        if log_path is None:
            return ""
        try:
            lines = Path(log_path).read_text().splitlines(keepends=True)
            return "".join(lines[-tail:])
        except OSError:
            return ""

    def set_hot_session(self, session_id: str) -> None:
        """Mark a session for frequent capture (TUI is viewing it)."""
        self._hot_sessions.add(session_id)

    def set_cold_session(self, session_id: str) -> None:
        """Mark a session for infrequent capture (TUI stopped viewing)."""
        self._hot_sessions.discard(session_id)
```

Also rename the internal `self.state` attribute to `self._state` and `self.config` to `self._config` throughout the class to avoid shadowing the new properties. Update all internal references (e.g., `self.state` → `self._state`). Similarly for `_hot_sessions` and `_session_log_paths` if they aren't already prefixed.

**Note:** Check if `self.state` and `self.config` are already used as attribute names in `__init__`. If so, rename the internal attributes to `self._state` and `self._config` and update all references within the class. The existing tests use `orchestrator.state` which will now hit the property instead — this is the desired behavior.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/orchestrator/test_orchestrator.py -v`
Expected: All pass including new and existing tests.

- [ ] **Step 5: Run type checker**

Run: `uv run mypy src/orca/orchestrator/orchestrator.py`
Expected: No errors.

- [ ] **Step 6: Commit**

```bash
git add src/orca/orchestrator/orchestrator.py tests/orchestrator/test_orchestrator.py
git commit -m "feat(orchestrator): add state accessors and session control methods"
```

---

### Task 2: RunManager

The core daemon component that creates and tracks Orchestrator instances per run.

**Files:**
- Create: `src/orca/daemon/__init__.py`
- Create: `src/orca/daemon/manager.py`
- Create: `tests/daemon/__init__.py`
- Create: `tests/daemon/test_manager.py`

- [ ] **Step 1: Create package init files**

Create `src/orca/daemon/__init__.py`:
```python
```

Create `tests/daemon/__init__.py`:
```python
```

- [ ] **Step 2: Write failing tests for RunManager**

Create `tests/daemon/test_manager.py`:

```python
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from orca.daemon.manager import RunInfo, RunManager, RunStatus


@pytest.fixture()
def repo_root(tmp_path: Path) -> Path:
    """Create a minimal repo-like directory with an orca.yml."""
    config = """\
issue:
  fields:
    title:
      type: string
      description: Title
states:
  todo:
    worker:
      kind: claude-code
      prompt: prompts/todo.md
      result_format:
        outcome:
          type: enum
          values: [done]
          description: Outcome
    on:
      done: complete
  complete:
    terminal: true
initial: todo
"""
    (tmp_path / "orca.yml").write_text(config)
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "todo.md").write_text("Do the thing: {{ issue.title }}")
    return tmp_path


class TestRunManager:
    def test_create(self, repo_root: Path) -> None:
        mgr = RunManager(repo_root)
        assert mgr.repo_root == repo_root
        assert mgr.list_runs() == []

    def test_run_id_format(self, repo_root: Path) -> None:
        mgr = RunManager(repo_root)
        run_id = mgr.make_run_id("feat/auth", "default")
        assert run_id == "feat/auth:default"

    @pytest.mark.asyncio()
    async def test_start_run(self, repo_root: Path) -> None:
        mgr = RunManager(repo_root)
        task_file = repo_root / "task.md"
        task_file.write_text("title: Test task\ndescription: A test")

        with patch("orca.daemon.manager.resolve_branch", return_value="main"):
            run_id = await mgr.start_run(
                task_file=task_file,
                workflow=None,
                branch="test-branch",
            )

        assert run_id == "test-branch:default"
        runs = mgr.list_runs()
        assert len(runs) == 1
        assert runs[0].run_id == "test-branch:default"
        assert runs[0].status == RunStatus.RUNNING

    @pytest.mark.asyncio()
    async def test_start_duplicate_run_errors(self, repo_root: Path) -> None:
        mgr = RunManager(repo_root)
        task_file = repo_root / "task.md"
        task_file.write_text("title: Test task")

        with patch("orca.daemon.manager.resolve_branch", return_value="main"):
            await mgr.start_run(task_file=task_file, branch="test-branch")

        with (
            patch("orca.daemon.manager.resolve_branch", return_value="main"),
            pytest.raises(ValueError, match="already running"),
        ):
            await mgr.start_run(task_file=task_file, branch="test-branch")

    def test_get_run_unknown(self, repo_root: Path) -> None:
        mgr = RunManager(repo_root)
        assert mgr.get_run("nonexistent:default") is None

    @pytest.mark.asyncio()
    async def test_stop_run(self, repo_root: Path) -> None:
        mgr = RunManager(repo_root)
        task_file = repo_root / "task.md"
        task_file.write_text("title: Test task")

        with patch("orca.daemon.manager.resolve_branch", return_value="main"):
            run_id = await mgr.start_run(task_file=task_file, branch="test-branch")

        await mgr.stop_run(run_id)
        info = mgr.get_run(run_id)
        assert info is not None
        assert info.status == RunStatus.STOPPED

    @pytest.mark.asyncio()
    async def test_stop_unknown_run_errors(self, repo_root: Path) -> None:
        mgr = RunManager(repo_root)
        with pytest.raises(ValueError, match="not found"):
            await mgr.stop_run("nonexistent:default")
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/daemon/test_manager.py -v`
Expected: FAIL — `orca.daemon.manager` doesn't exist.

- [ ] **Step 4: Implement RunManager**

Create `src/orca/daemon/manager.py`:

```python
from __future__ import annotations

import asyncio
import enum
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml

from orca.engine.config import parse_config
from orca.engine.dispatch import build_issue_context, build_result_format
from orca.engine.reducer import reduce
from orca.engine.types import (
    CreateEvent,
    Effect,
    State,
    StateMachineConfig,
)
from orca.orchestrator.branches import BranchMap
from orca.orchestrator.config_types import parse_integrations, parse_orchestrator_config
from orca.orchestrator.log import setup_logging
from orca.orchestrator.orchestrator import Orchestrator
from orca.orchestrator.persistence import Persistence
from orca.orchestrator.runner import (
    _find_root_issue,
    _recover_effects,
    parse_task_file,
    resolve_config_path,
)
from orca.orchestrator.session_sync import SessionManifest, SessionSync
from orca.orchestrator.worker import KIND_REGISTRY, CliAgentWorker
from orca.orchestrator.worktree import WorktreeManager

logger = logging.getLogger(__name__)


def _generate_id() -> str:
    return str(uuid4())


def _now() -> str:
    return datetime.now(UTC).isoformat()


class RunStatus(enum.Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"
    INTERRUPTED = "interrupted"


@dataclass
class RunInfo:
    run_id: str
    branch: str
    workflow: str
    status: RunStatus
    issue_count: int
    created_at: str
    config: StateMachineConfig | None = None
    orchestrator: Orchestrator | None = None
    task: asyncio.Task[None] | None = None

    def to_summary(self) -> dict[str, Any]:
        """Return a JSON-serializable summary."""
        state = self.orchestrator.state if self.orchestrator else None
        terminal_count = 0
        if state and self.config:
            for issue in state.issues.values():
                type_def = self.config.types.get(issue.type)
                if type_def:
                    state_def = type_def.states.get(issue.state)
                    if state_def and state_def.terminal:
                        terminal_count += 1
        return {
            "run_id": self.run_id,
            "branch": self.branch,
            "workflow": self.workflow,
            "status": self.status.value,
            "issue_count": state and len(state.issues) or self.issue_count,
            "terminal_count": terminal_count,
            "created_at": self.created_at,
        }


class RunManager:
    """Manages multiple Orchestrator instances for a single repo."""

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root
        self._runs: dict[str, RunInfo] = {}

    @staticmethod
    def make_run_id(branch: str, workflow: str) -> str:
        return f"{branch}:{workflow}"

    def list_runs(self) -> list[RunInfo]:
        return list(self._runs.values())

    def get_run(self, run_id: str) -> RunInfo | None:
        return self._runs.get(run_id)

    async def start_run(
        self,
        task_file: Path,
        workflow: str | None = None,
        branch: str | None = None,
        base: str | None = None,
        max_hops: int | None = None,
        max_retries: int | None = None,
    ) -> str:
        """Start a new orchestrator run. Returns the run_id."""
        from orca.orchestrator.runner import resolve_branch

        config_path = resolve_config_path(self.repo_root, workflow)
        raw_config: dict[str, Any] = yaml.safe_load(config_path.read_text())
        orch_config = parse_orchestrator_config(raw_config)

        branch_name = branch or resolve_branch()
        workflow_name = workflow or "default"
        run_id = self.make_run_id(branch_name, workflow_name)

        if run_id in self._runs and self._runs[run_id].status == RunStatus.RUNNING:
            msg = f"Run {run_id} is already running"
            raise ValueError(msg)

        config = parse_config(config_path.read_text())
        if max_hops is not None:
            object.__setattr__(config, "max_hops", max_hops)
        if max_retries is not None:
            object.__setattr__(config, "max_worker_retries", max_retries)

        integrations = parse_integrations(raw_config.get("integrations"))
        run_dir = self.repo_root / ".orca" / "runs" / branch_name / workflow_name
        persistence = Persistence(self.repo_root, branch_name, workflow_name)
        branches = BranchMap(self.repo_root, branch_name, workflow_name)
        worktree_mgr = WorktreeManager(self.repo_root, branch_name)

        setup_logging(run_dir / "orca.log.jsonl")

        fields = parse_task_file(task_file)
        initial_effects: list[Effect] = []

        if persistence.exists():
            state = persistence.load()
            if state is None:
                msg = "Failed to load state from persistence"
                raise RuntimeError(msg)
            branches.load()
            for issue in state.issues.values():
                type_def = config.types.get(issue.type)
                if type_def and issue.state in type_def.states and type_def.states[issue.state].terminal:
                    continue
                issue.hop_count = 0
                issue.failure_count = 0
            manifest = SessionManifest(run_dir)
            manifest.mark_orphans_completed(_now())
            recovered_events, recovered_effects = _recover_effects(
                config, state, branches, worktree_mgr, run_dir, _generate_id, _now
            )
            for event in recovered_events:
                state, new_effects = reduce(config, state, event, _generate_id, _now)
                initial_effects.extend(new_effects)
            initial_effects.extend(recovered_effects)
        else:
            root_issue_id = _generate_id()
            state = State(issues={}, worker_queues={})
            create_event = CreateEvent(issue_id=root_issue_id, fields=fields, timestamp=_now())
            state, initial_effects = reduce(config, state, create_event, _generate_id, _now)
            branches.set(root_issue_id, branch_name)
            branches.save()
            persistence.save(state)

        root_issue_id = _find_root_issue(state)
        workers = {name: CliAgentWorker(self.repo_root, kc) for name, kc in KIND_REGISTRY.items()}
        session_sync = SessionSync(run_dir=run_dir)

        orchestrator = Orchestrator(
            config=config,
            state=state,
            root_branch=branch_name,
            persistence=persistence,
            branches=branches,
            workers=workers,
            generate_id=_generate_id,
            now=_now,
            worktree_mgr=worktree_mgr,
            repo_root=self.repo_root,
            session_sync=session_sync,
            slack_mcp_url=None,
        )

        run_info = RunInfo(
            run_id=run_id,
            branch=branch_name,
            workflow=workflow_name,
            status=RunStatus.RUNNING,
            issue_count=len(state.issues),
            created_at=_now(),
            config=config,
            orchestrator=orchestrator,
        )

        async def _run_orchestrator() -> None:
            try:
                await orchestrator.run(root_issue_id, initial_effects)
                run_info.status = RunStatus.COMPLETED
            except asyncio.CancelledError:
                run_info.status = RunStatus.STOPPED
            except Exception:
                logger.exception("Run %s failed", run_id)
                run_info.status = RunStatus.FAILED

        task = asyncio.create_task(_run_orchestrator())
        run_info.task = task
        self._runs[run_id] = run_info

        return run_id

    async def stop_run(self, run_id: str) -> None:
        """Stop a running orchestrator."""
        info = self._runs.get(run_id)
        if info is None:
            msg = f"Run {run_id} not found"
            raise ValueError(msg)
        if info.task and not info.task.done():
            info.task.cancel()
            try:
                await info.task
            except asyncio.CancelledError:
                pass
        info.status = RunStatus.STOPPED

    async def stop_all(self) -> None:
        """Stop all running orchestrators. Used during daemon shutdown."""
        tasks = []
        for info in self._runs.values():
            if info.task and not info.task.done():
                info.task.cancel()
                tasks.append(info.task)
        for t in tasks:
            try:
                await t
            except asyncio.CancelledError:
                pass

    def scan_interrupted_runs(self) -> None:
        """Scan .orca/runs/ for non-terminal runs from a previous daemon session.

        Marks them as INTERRUPTED so they show up in `orca runs` but don't auto-resume.
        """
        runs_dir = self.repo_root / ".orca" / "runs"
        if not runs_dir.exists():
            return
        for branch_dir in runs_dir.iterdir():
            if not branch_dir.is_dir():
                continue
            for workflow_dir in branch_dir.iterdir():
                if not workflow_dir.is_dir():
                    continue
                state_path = workflow_dir / "state.json"
                if not state_path.exists():
                    continue
                import json

                try:
                    state = State.from_dict(json.loads(state_path.read_text()))
                except (json.JSONDecodeError, OSError, KeyError):
                    continue

                branch = branch_dir.name
                workflow = workflow_dir.name
                run_id = self.make_run_id(branch, workflow)
                if run_id in self._runs:
                    continue

                self._runs[run_id] = RunInfo(
                    run_id=run_id,
                    branch=branch,
                    workflow=workflow,
                    status=RunStatus.INTERRUPTED,
                    issue_count=len(state.issues),
                    created_at=_now(),
                )

    def get_run_state(self, run_id: str) -> dict[str, Any] | None:
        """Get full state dict for a run."""
        info = self._runs.get(run_id)
        if info is None or info.orchestrator is None:
            return None
        return info.orchestrator.state.to_dict()

    def get_issue(self, run_id: str, issue_id: str) -> dict[str, Any] | None:
        """Get a single issue from a run."""
        info = self._runs.get(run_id)
        if info is None or info.orchestrator is None:
            return None
        issue = info.orchestrator.state.issues.get(issue_id)
        if issue is None:
            return None
        return issue.to_dict()

    def get_worker_log(self, run_id: str, tracking_id: str, tail: int = 100) -> str:
        """Get worker session log lines."""
        info = self._runs.get(run_id)
        if info is None or info.orchestrator is None:
            return ""
        return info.orchestrator.get_session_log(tracking_id, tail=tail)

    def get_insights(self, run_id: str) -> str:
        """Get insights summary for a run."""
        info = self._runs.get(run_id)
        if info is None or info.orchestrator is None:
            return ""
        return info.orchestrator._insights_state.get("summary", "")

    def retry_issue(self, run_id: str, issue_id: str) -> None:
        """Signal retry for a failed issue."""
        info = self._runs.get(run_id)
        if info is None or info.orchestrator is None:
            msg = f"Run {run_id} not found"
            raise ValueError(msg)
        # Write retry signal file, same mechanism as TUI
        run_dir = self.repo_root / ".orca" / "runs" / info.branch / info.workflow
        retry_dir = run_dir / "retry"
        retry_dir.mkdir(parents=True, exist_ok=True)
        (retry_dir / issue_id).touch()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/daemon/test_manager.py -v`
Expected: All pass.

- [ ] **Step 6: Run type checker**

Run: `uv run mypy src/orca/daemon/`
Expected: No errors.

- [ ] **Step 7: Commit**

```bash
git add src/orca/daemon/ tests/daemon/
git commit -m "feat(daemon): add RunManager for multi-run orchestration"
```

---

### Task 3: Daemon Lifecycle

Daemonize process, pidfile management, UDS socket, signal handling.

**Files:**
- Create: `src/orca/daemon/lifecycle.py`
- Create: `tests/daemon/test_lifecycle.py`

- [ ] **Step 1: Write failing tests**

Create `tests/daemon/test_lifecycle.py`:

```python
from __future__ import annotations

import os
import signal
from pathlib import Path
from unittest.mock import patch

import pytest

from orca.daemon.lifecycle import (
    DaemonAlreadyRunningError,
    check_daemon_running,
    cleanup_stale_socket,
    read_pidfile,
    socket_path,
    pidfile_path,
    write_pidfile,
    remove_pidfile,
)


class TestPidfile:
    def test_write_and_read(self, tmp_path: Path) -> None:
        pf = tmp_path / ".orca" / "daemon.pid"
        write_pidfile(pf, 12345)
        assert read_pidfile(pf) == 12345

    def test_read_missing(self, tmp_path: Path) -> None:
        pf = tmp_path / ".orca" / "daemon.pid"
        assert read_pidfile(pf) is None

    def test_remove(self, tmp_path: Path) -> None:
        pf = tmp_path / ".orca" / "daemon.pid"
        write_pidfile(pf, 12345)
        remove_pidfile(pf)
        assert not pf.exists()


class TestPaths:
    def test_socket_path(self, tmp_path: Path) -> None:
        assert socket_path(tmp_path) == tmp_path / ".orca" / "daemon.sock"

    def test_pidfile_path(self, tmp_path: Path) -> None:
        assert pidfile_path(tmp_path) == tmp_path / ".orca" / "daemon.pid"


class TestCheckDaemonRunning:
    def test_not_running_no_pidfile(self, tmp_path: Path) -> None:
        assert check_daemon_running(tmp_path) is False

    def test_not_running_stale_pid(self, tmp_path: Path) -> None:
        pf = pidfile_path(tmp_path)
        write_pidfile(pf, 999999999)  # PID that almost certainly doesn't exist
        assert check_daemon_running(tmp_path) is False
        # Stale pidfile should be cleaned up
        assert not pf.exists()

    def test_running(self, tmp_path: Path) -> None:
        pf = pidfile_path(tmp_path)
        write_pidfile(pf, os.getpid())  # Current process IS running
        assert check_daemon_running(tmp_path) is True


class TestCleanupStaleSocket:
    def test_removes_stale_socket(self, tmp_path: Path) -> None:
        sock = socket_path(tmp_path)
        sock.parent.mkdir(parents=True, exist_ok=True)
        sock.touch()
        cleanup_stale_socket(tmp_path)
        assert not sock.exists()

    def test_noop_when_no_socket(self, tmp_path: Path) -> None:
        cleanup_stale_socket(tmp_path)  # Should not raise
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/daemon/test_lifecycle.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement lifecycle**

Create `src/orca/daemon/lifecycle.py`:

```python
from __future__ import annotations

import logging
import os
import signal
from pathlib import Path

logger = logging.getLogger(__name__)


class DaemonAlreadyRunningError(Exception):
    def __init__(self, pid: int) -> None:
        self.pid = pid
        super().__init__(f"Daemon already running (PID: {pid})")


def socket_path(repo_root: Path) -> Path:
    return repo_root / ".orca" / "daemon.sock"


def pidfile_path(repo_root: Path) -> Path:
    return repo_root / ".orca" / "daemon.pid"


def write_pidfile(path: Path, pid: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(pid))


def read_pidfile(path: Path) -> int | None:
    try:
        return int(path.read_text().strip())
    except (FileNotFoundError, ValueError):
        return None


def remove_pidfile(path: Path) -> None:
    path.unlink(missing_ok=True)


def _is_process_alive(pid: int) -> bool:
    """Check if a process with the given PID is running."""
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def check_daemon_running(repo_root: Path) -> bool:
    """Check if a daemon is already running for this repo.

    Returns True if running, False otherwise.
    Cleans up stale pidfile if the process is dead.
    """
    pid = read_pidfile(pidfile_path(repo_root))
    if pid is None:
        return False
    if _is_process_alive(pid):
        return True
    # Stale pidfile — process is dead
    remove_pidfile(pidfile_path(repo_root))
    return False


def cleanup_stale_socket(repo_root: Path) -> None:
    """Remove a leftover socket file from a previous daemon."""
    sock = socket_path(repo_root)
    sock.unlink(missing_ok=True)


def send_stop_signal(repo_root: Path) -> bool:
    """Send SIGTERM to the running daemon. Returns True if signal was sent."""
    pid = read_pidfile(pidfile_path(repo_root))
    if pid is None:
        return False
    try:
        os.kill(pid, signal.SIGTERM)
        return True
    except OSError:
        # Process already dead
        remove_pidfile(pidfile_path(repo_root))
        cleanup_stale_socket(repo_root)
        return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/daemon/test_lifecycle.py -v`
Expected: All pass.

- [ ] **Step 5: Run type checker**

Run: `uv run mypy src/orca/daemon/lifecycle.py`
Expected: No errors.

- [ ] **Step 6: Commit**

```bash
git add src/orca/daemon/lifecycle.py tests/daemon/test_lifecycle.py
git commit -m "feat(daemon): add lifecycle management (pidfile, socket, process detection)"
```

---

### Task 4: Daemon HTTP Server

Starlette app serving on UDS. Internal JSON API for TUI and MCP tools.

**Files:**
- Create: `src/orca/daemon/http_api.py`
- Create: `src/orca/daemon/server.py`
- Create: `tests/daemon/test_http_api.py`

- [ ] **Step 1: Write failing tests for HTTP API routes**

Create `tests/daemon/test_http_api.py`:

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from starlette.testclient import TestClient

from orca.daemon.http_api import create_app
from orca.daemon.manager import RunInfo, RunManager, RunStatus


@pytest.fixture()
def manager(tmp_path: Path) -> RunManager:
    return RunManager(tmp_path)


@pytest.fixture()
def client(manager: RunManager) -> TestClient:
    app = create_app(manager)
    return TestClient(app)


class TestStatusEndpoint:
    def test_status(self, client: TestClient) -> None:
        resp = client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "uptime" in data
        assert data["active_runs"] == 0


class TestListRuns:
    def test_empty(self, client: TestClient) -> None:
        resp = client.get("/api/runs")
        assert resp.status_code == 200
        assert resp.json() == []


class TestGetRun:
    def test_not_found(self, client: TestClient) -> None:
        resp = client.get("/api/runs/nonexistent:default")
        assert resp.status_code == 404


class TestGetIssue:
    def test_not_found(self, client: TestClient) -> None:
        resp = client.get("/api/runs/nonexistent:default/issues/issue-1")
        assert resp.status_code == 404


class TestWorkerLog:
    def test_not_found(self, client: TestClient) -> None:
        resp = client.get("/api/runs/nonexistent:default/logs/track-1")
        assert resp.status_code == 200
        assert resp.text == ""


class TestRetryIssue:
    def test_not_found(self, client: TestClient) -> None:
        resp = client.post("/api/runs/nonexistent:default/retry/issue-1")
        assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/daemon/test_http_api.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement HTTP API**

Create `src/orca/daemon/http_api.py`:

```python
from __future__ import annotations

import time
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route

from orca.daemon.manager import RunManager, RunStatus

_start_time: float = 0.0


def create_app(manager: RunManager) -> Starlette:
    """Create the daemon HTTP API application."""
    global _start_time
    _start_time = time.monotonic()

    async def status(request: Request) -> JSONResponse:
        active = sum(1 for r in manager.list_runs() if r.status == RunStatus.RUNNING)
        return JSONResponse({
            "uptime": time.monotonic() - _start_time,
            "active_runs": active,
            "total_runs": len(manager.list_runs()),
        })

    async def list_runs(request: Request) -> JSONResponse:
        return JSONResponse([r.to_summary() for r in manager.list_runs()])

    async def get_run(request: Request) -> JSONResponse:
        run_id = request.path_params["run_id"]
        state = manager.get_run_state(run_id)
        if state is None:
            return JSONResponse({"error": f"Run {run_id} not found"}, status_code=404)
        info = manager.get_run(run_id)
        return JSONResponse({
            "run_id": run_id,
            "status": info.status.value if info else "unknown",
            "state": state,
        })

    async def get_issue(request: Request) -> JSONResponse:
        run_id = request.path_params["run_id"]
        issue_id = request.path_params["issue_id"]
        issue = manager.get_issue(run_id, issue_id)
        if issue is None:
            return JSONResponse({"error": "Issue not found"}, status_code=404)
        return JSONResponse(issue)

    async def get_insights(request: Request) -> PlainTextResponse:
        run_id = request.path_params["run_id"]
        return PlainTextResponse(manager.get_insights(run_id))

    async def get_worker_log(request: Request) -> PlainTextResponse:
        run_id = request.path_params["run_id"]
        tracking_id = request.path_params["tracking_id"]
        tail = int(request.query_params.get("tail", "100"))
        return PlainTextResponse(manager.get_worker_log(run_id, tracking_id, tail=tail))

    async def start_run(request: Request) -> JSONResponse:
        body = await request.json()
        try:
            run_id = await manager.start_run(
                task_file=manager.repo_root / body["task_file"],
                workflow=body.get("workflow"),
                branch=body.get("branch"),
                base=body.get("base"),
                max_hops=body.get("max_hops"),
                max_retries=body.get("max_retries"),
            )
            return JSONResponse({"run_id": run_id, "status": "running"})
        except (ValueError, RuntimeError) as e:
            return JSONResponse({"error": str(e)}, status_code=400)

    async def stop_run(request: Request) -> JSONResponse:
        run_id = request.path_params["run_id"]
        try:
            await manager.stop_run(run_id)
            return JSONResponse({"run_id": run_id, "status": "stopped"})
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=404)

    async def retry_issue(request: Request) -> JSONResponse:
        run_id = request.path_params["run_id"]
        issue_id = request.path_params["issue_id"]
        try:
            manager.retry_issue(run_id, issue_id)
            return JSONResponse({"run_id": run_id, "issue_id": issue_id, "status": "retrying"})
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=404)

    async def hot_session(request: Request) -> JSONResponse:
        run_id = request.path_params["run_id"]
        body = await request.json()
        session_id = body["session_id"]
        info = manager.get_run(run_id)
        if info is None or info.orchestrator is None:
            return JSONResponse({"error": "Run not found"}, status_code=404)
        if body.get("hot", True):
            info.orchestrator.set_hot_session(session_id)
        else:
            info.orchestrator.set_cold_session(session_id)
        return JSONResponse({"ok": True})

    routes = [
        Route("/api/status", status, methods=["GET"]),
        Route("/api/runs", list_runs, methods=["GET"]),
        Route("/api/runs/start", start_run, methods=["POST"]),
        Route("/api/runs/{run_id:path}", get_run, methods=["GET"]),
        Route("/api/runs/{run_id:path}/issues/{issue_id}", get_issue, methods=["GET"]),
        Route("/api/runs/{run_id:path}/insights", get_insights, methods=["GET"]),
        Route("/api/runs/{run_id:path}/logs/{tracking_id}", get_worker_log, methods=["GET"]),
        Route("/api/runs/{run_id:path}/stop", stop_run, methods=["POST"]),
        Route("/api/runs/{run_id:path}/retry/{issue_id}", retry_issue, methods=["POST"]),
        Route("/api/runs/{run_id:path}/hot-session", hot_session, methods=["POST"]),
    ]

    return Starlette(routes=routes)
```

- [ ] **Step 4: Implement daemon server entry point**

Create `src/orca/daemon/server.py`:

```python
from __future__ import annotations

import asyncio
import logging
import signal
from pathlib import Path

import uvicorn

from orca.daemon.http_api import create_app
from orca.daemon.lifecycle import (
    DaemonAlreadyRunningError,
    check_daemon_running,
    cleanup_stale_socket,
    pidfile_path,
    remove_pidfile,
    socket_path,
    write_pidfile,
)
from orca.daemon.manager import RunManager

logger = logging.getLogger(__name__)


async def serve(repo_root: Path) -> None:
    """Start the daemon HTTP server on a Unix domain socket."""
    import os

    if check_daemon_running(repo_root):
        pid = int(pidfile_path(repo_root).read_text().strip())
        raise DaemonAlreadyRunningError(pid)

    cleanup_stale_socket(repo_root)
    sock = socket_path(repo_root)
    sock.parent.mkdir(parents=True, exist_ok=True)

    manager = RunManager(repo_root)
    manager.scan_interrupted_runs()
    app = create_app(manager)

    write_pidfile(pidfile_path(repo_root), os.getpid())

    config = uvicorn.Config(
        app,
        uds=str(sock),
        log_level="warning",
    )
    server = uvicorn.Server(config)

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def handle_sigterm(*_: object) -> None:
        logger.info("Received SIGTERM, shutting down")
        stop_event.set()

    loop.add_signal_handler(signal.SIGTERM, handle_sigterm)
    loop.add_signal_handler(signal.SIGINT, handle_sigterm)

    server_task = asyncio.create_task(server.serve())

    await stop_event.wait()

    # Graceful shutdown
    await manager.stop_all()
    server.should_exit = True
    await server_task

    # Cleanup
    remove_pidfile(pidfile_path(repo_root))
    sock.unlink(missing_ok=True)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/daemon/test_http_api.py -v`
Expected: All pass.

- [ ] **Step 6: Run type checker**

Run: `uv run mypy src/orca/daemon/http_api.py src/orca/daemon/server.py`
Expected: No errors.

- [ ] **Step 7: Commit**

```bash
git add src/orca/daemon/http_api.py src/orca/daemon/server.py tests/daemon/test_http_api.py
git commit -m "feat(daemon): add HTTP API and server entry point"
```

---

### Task 5: MCP Tools

FastMCP server that exposes orca tools, delegating to RunManager.

**Files:**
- Create: `src/orca/daemon/mcp_tools.py`
- Create: `tests/daemon/test_mcp_tools.py`

- [ ] **Step 1: Write failing tests**

Create `tests/daemon/test_mcp_tools.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest

from orca.daemon.manager import RunManager
from orca.daemon.mcp_tools import create_mcp_server


class TestMcpTools:
    def test_server_has_tools(self, tmp_path: Path) -> None:
        manager = RunManager(tmp_path)
        server = create_mcp_server(manager)
        tool_names = [t.name for t in server._tool_manager.list_tools()]
        assert "orca_daemon_status" in tool_names
        assert "orca_start_run" in tool_names
        assert "orca_list_runs" in tool_names
        assert "orca_get_run" in tool_names
        assert "orca_get_issue" in tool_names
        assert "orca_get_insights" in tool_names
        assert "orca_get_worker_log" in tool_names
        assert "orca_retry_issue" in tool_names
        assert "orca_stop_run" in tool_names

    @pytest.mark.asyncio()
    async def test_daemon_status(self, tmp_path: Path) -> None:
        manager = RunManager(tmp_path)
        server = create_mcp_server(manager)
        result = await server._tool_manager.call_tool("orca_daemon_status", {})
        data = json.loads(result[0].text)
        assert data["active_runs"] == 0

    @pytest.mark.asyncio()
    async def test_list_runs_empty(self, tmp_path: Path) -> None:
        manager = RunManager(tmp_path)
        server = create_mcp_server(manager)
        result = await server._tool_manager.call_tool("orca_list_runs", {})
        data = json.loads(result[0].text)
        assert data == []

    @pytest.mark.asyncio()
    async def test_get_run_not_found(self, tmp_path: Path) -> None:
        manager = RunManager(tmp_path)
        server = create_mcp_server(manager)
        result = await server._tool_manager.call_tool("orca_get_run", {"run_id": "nope:default"})
        data = json.loads(result[0].text)
        assert "error" in data
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/daemon/test_mcp_tools.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement MCP tools**

Create `src/orca/daemon/mcp_tools.py`:

```python
from __future__ import annotations

import json
import time
from typing import Any

from mcp.server.fastmcp import FastMCP

from orca.daemon.manager import RunManager, RunStatus

_start_time: float = 0.0


def create_mcp_server(manager: RunManager) -> FastMCP:
    """Create an MCP server with orca daemon tools."""
    global _start_time
    _start_time = time.monotonic()

    server = FastMCP("orca")

    async def orca_daemon_status() -> str:
        """Get daemon health: uptime, active run count, total runs."""
        active = sum(1 for r in manager.list_runs() if r.status == RunStatus.RUNNING)
        return json.dumps({
            "uptime": time.monotonic() - _start_time,
            "active_runs": active,
            "total_runs": len(manager.list_runs()),
        })

    async def orca_start_run(
        task_file: str,
        workflow: str | None = None,
        branch: str | None = None,
    ) -> str:
        """Start a new orca workflow run.

        Args:
            task_file: Path to the task file (relative to repo root).
            workflow: Workflow name (e.g. "develop" -> orca.develop.yml). Omit for default.
            branch: Git branch name for this run. Omit to use current branch.

        Returns:
            JSON with run_id and status.
        """
        try:
            run_id = await manager.start_run(
                task_file=manager.repo_root / task_file,
                workflow=workflow,
                branch=branch,
            )
            return json.dumps({"run_id": run_id, "status": "running"})
        except (ValueError, RuntimeError) as e:
            return json.dumps({"error": str(e)})

    async def orca_list_runs() -> str:
        """List all runs in this repo with status, branch, and issue counts."""
        return json.dumps([r.to_summary() for r in manager.list_runs()])

    async def orca_get_run(run_id: str) -> str:
        """Get detailed state for a run: all issues, phases, progress.

        Args:
            run_id: Run identifier (format: "branch:workflow").
        """
        state = manager.get_run_state(run_id)
        if state is None:
            return json.dumps({"error": f"Run {run_id} not found"})
        info = manager.get_run(run_id)
        return json.dumps({
            "run_id": run_id,
            "status": info.status.value if info else "unknown",
            "state": state,
        })

    async def orca_get_issue(run_id: str, issue_id: str) -> str:
        """Get details for a single issue: fields, state, event log, children.

        Args:
            run_id: Run identifier.
            issue_id: Issue UUID.
        """
        issue = manager.get_issue(run_id, issue_id)
        if issue is None:
            return json.dumps({"error": "Issue not found"})
        return json.dumps(issue)

    async def orca_get_insights(run_id: str) -> str:
        """Get current insights agent summary for a run.

        Args:
            run_id: Run identifier.
        """
        return manager.get_insights(run_id)

    async def orca_get_worker_log(
        run_id: str,
        issue_id: str,
        tail: int = 100,
    ) -> str:
        """Get worker session log output.

        Args:
            run_id: Run identifier.
            issue_id: Issue UUID (used to find the tracking ID).
            tail: Number of lines from the end (default: 100).
        """
        return manager.get_worker_log(run_id, issue_id, tail=tail)

    async def orca_retry_issue(run_id: str, issue_id: str) -> str:
        """Retry a failed issue.

        Args:
            run_id: Run identifier.
            issue_id: Issue UUID to retry.
        """
        try:
            manager.retry_issue(run_id, issue_id)
            return json.dumps({"run_id": run_id, "issue_id": issue_id, "status": "retrying"})
        except ValueError as e:
            return json.dumps({"error": str(e)})

    async def orca_stop_run(run_id: str) -> str:
        """Stop a running workflow.

        Args:
            run_id: Run identifier.
        """
        try:
            await manager.stop_run(run_id)
            return json.dumps({"run_id": run_id, "status": "stopped"})
        except ValueError as e:
            return json.dumps({"error": str(e)})

    server.add_tool(orca_daemon_status, name="orca_daemon_status")
    server.add_tool(orca_start_run, name="orca_start_run")
    server.add_tool(orca_list_runs, name="orca_list_runs")
    server.add_tool(orca_get_run, name="orca_get_run")
    server.add_tool(orca_get_issue, name="orca_get_issue")
    server.add_tool(orca_get_insights, name="orca_get_insights")
    server.add_tool(orca_get_worker_log, name="orca_get_worker_log")
    server.add_tool(orca_retry_issue, name="orca_retry_issue")
    server.add_tool(orca_stop_run, name="orca_stop_run")

    return server
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/daemon/test_mcp_tools.py -v`
Expected: All pass.

- [ ] **Step 5: Run type checker**

Run: `uv run mypy src/orca/daemon/mcp_tools.py`
Expected: No errors.

- [ ] **Step 6: Commit**

```bash
git add src/orca/daemon/mcp_tools.py tests/daemon/test_mcp_tools.py
git commit -m "feat(daemon): add MCP tool definitions"
```

---

### Task 6: CLI Subcommand Structure

Replace the current argparse entrypoint with subcommand dispatch.

**Files:**
- Create: `src/orca/cli/__init__.py`
- Create: `src/orca/cli/main.py`
- Create: `src/orca/cli/daemon_cmd.py`
- Create: `src/orca/cli/run_cmd.py`
- Create: `src/orca/cli/mcp_cmd.py`
- Create: `src/orca/cli/tui_cmd.py`
- Create: `src/orca/cli/list_cmd.py`
- Create: `tests/cli/__init__.py`
- Create: `tests/cli/test_main.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: Write failing tests for CLI dispatch**

Create `tests/cli/__init__.py`:
```python
```

Create `tests/cli/test_main.py`:

```python
from __future__ import annotations

from unittest.mock import patch

import pytest


class TestCliDispatch:
    def test_no_subcommand_shows_help(self, capsys: pytest.CaptureFixture[str]) -> None:
        from orca.cli.main import build_parser

        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([])

    def test_daemon_start_subcommand(self) -> None:
        from orca.cli.main import build_parser

        parser = build_parser()
        args = parser.parse_args(["daemon", "start"])
        assert args.daemon_action == "start"

    def test_daemon_stop_subcommand(self) -> None:
        from orca.cli.main import build_parser

        parser = build_parser()
        args = parser.parse_args(["daemon", "stop"])
        assert args.daemon_action == "stop"

    def test_run_subcommand(self) -> None:
        from orca.cli.main import build_parser

        parser = build_parser()
        args = parser.parse_args(["run", "task.md", "-b", "feature", "-w", "dev"])
        assert args.task_file.name == "task.md"
        assert args.branch == "feature"
        assert args.workflow == "dev"

    def test_tui_subcommand(self) -> None:
        from orca.cli.main import build_parser

        parser = build_parser()
        args = parser.parse_args(["tui"])
        assert args.subcommand == "tui"

    def test_mcp_subcommand(self) -> None:
        from orca.cli.main import build_parser

        parser = build_parser()
        args = parser.parse_args(["mcp"])
        assert args.subcommand == "mcp"

    def test_runs_subcommand(self) -> None:
        from orca.cli.main import build_parser

        parser = build_parser()
        args = parser.parse_args(["runs"])
        assert args.subcommand == "runs"

    def test_logs_subcommand(self) -> None:
        from orca.cli.main import build_parser

        parser = build_parser()
        args = parser.parse_args(["logs", "feat:default", "--tail", "50"])
        assert args.run_id == "feat:default"
        assert args.tail == 50
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/cli/test_main.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement CLI main and subcommands**

Create `src/orca/cli/__init__.py`:
```python
```

Create `src/orca/cli/main.py`:

```python
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="orca", description="Orca workflow orchestrator")
    sub = parser.add_subparsers(dest="subcommand", required=True)

    # orca daemon start|stop|status
    daemon_parser = sub.add_parser("daemon", help="Manage the orca daemon")
    daemon_parser.add_argument("daemon_action", choices=["start", "stop", "status"])

    # orca run <task.md>
    run_parser = sub.add_parser("run", help="Submit a workflow run to the daemon")
    run_parser.add_argument("task_file", type=Path, help="Path to the task file")
    run_parser.add_argument("-w", "--workflow", type=str, default=None, help="Workflow name")
    run_parser.add_argument("-b", "--branch", type=str, default=None, help="Branch name")
    run_parser.add_argument("--base", type=str, default=None, help="Base ref to branch from")
    run_parser.add_argument("--max-hops", type=int, default=10, help="Max state transitions per issue")
    run_parser.add_argument("--max-retries", type=int, default=3, help="Max worker crash retries")

    # orca tui
    sub.add_parser("tui", help="Attach the TUI to the daemon")

    # orca mcp
    sub.add_parser("mcp", help="MCP stdio bridge to the daemon")

    # orca runs
    sub.add_parser("runs", help="List all runs")

    # orca logs <run_id>
    logs_parser = sub.add_parser("logs", help="Print worker logs")
    logs_parser.add_argument("run_id", type=str, help="Run ID (branch:workflow)")
    logs_parser.add_argument("issue_id", type=str, nargs="?", default=None, help="Issue ID")
    logs_parser.add_argument("--tail", type=int, default=100, help="Number of lines")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.subcommand == "daemon":
        from orca.cli.daemon_cmd import daemon_command

        daemon_command(args.daemon_action)

    elif args.subcommand == "run":
        from orca.cli.run_cmd import run_command

        run_command(args)

    elif args.subcommand == "tui":
        from orca.cli.tui_cmd import tui_command

        tui_command()

    elif args.subcommand == "mcp":
        from orca.cli.mcp_cmd import mcp_command

        mcp_command()

    elif args.subcommand == "runs":
        from orca.cli.list_cmd import runs_command

        runs_command()

    elif args.subcommand == "logs":
        from orca.cli.list_cmd import logs_command

        logs_command(args)
```

Create `src/orca/cli/daemon_cmd.py`:

```python
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path


def _repo_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print("Error: not in a git repository", file=sys.stderr)
        raise SystemExit(1)
    return Path(result.stdout.strip())


def daemon_command(action: str) -> None:
    from orca.daemon.lifecycle import (
        check_daemon_running,
        pidfile_path,
        read_pidfile,
        send_stop_signal,
    )

    repo_root = _repo_root()

    if action == "start":
        if check_daemon_running(repo_root):
            pid = read_pidfile(pidfile_path(repo_root))
            print(f"Daemon already running (PID: {pid})")
            raise SystemExit(1)

        from orca.daemon.server import serve

        print(f"Starting orca daemon for {repo_root} (PID: {os.getpid()})")
        asyncio.run(serve(repo_root))

    elif action == "stop":
        if not check_daemon_running(repo_root):
            print("Daemon is not running")
            raise SystemExit(1)
        if send_stop_signal(repo_root):
            print("Stop signal sent to daemon")
        else:
            print("Failed to send stop signal", file=sys.stderr)
            raise SystemExit(1)

    elif action == "status":
        if check_daemon_running(repo_root):
            pid = read_pidfile(pidfile_path(repo_root))
            print(f"Daemon running (PID: {pid})")
        else:
            print("Daemon not running")
```

Create `src/orca/cli/run_cmd.py`:

```python
from __future__ import annotations

import json
import sys
from argparse import Namespace
from pathlib import Path

import aiohttp


def _daemon_url(repo_root: Path) -> str:
    sock = repo_root / ".orca" / "daemon.sock"
    return str(sock)


def _repo_root() -> Path:
    from orca.cli.daemon_cmd import _repo_root

    return _repo_root()


def run_command(args: Namespace) -> None:
    import asyncio

    repo_root = _repo_root()

    from orca.daemon.lifecycle import check_daemon_running

    if not check_daemon_running(repo_root):
        print("Error: daemon not running. Start with: orca daemon start", file=sys.stderr)
        raise SystemExit(1)

    async def submit() -> None:
        sock = _daemon_url(repo_root)
        conn = aiohttp.UnixConnector(path=sock)
        async with aiohttp.ClientSession(connector=conn) as session:
            payload = {
                "task_file": str(args.task_file),
                "workflow": args.workflow,
                "branch": args.branch,
                "base": getattr(args, "base", None),
                "max_hops": args.max_hops,
                "max_retries": args.max_retries,
            }
            async with session.post("http://localhost/api/runs/start", json=payload) as resp:
                data = await resp.json()
                if "error" in data:
                    print(f"Error: {data['error']}", file=sys.stderr)
                    raise SystemExit(1)
                print(f"Run started: {data['run_id']}")

    asyncio.run(submit())
```

Create `src/orca/cli/mcp_cmd.py`:

```python
from __future__ import annotations

import asyncio
import sys
from pathlib import Path


def mcp_command() -> None:
    from orca.cli.daemon_cmd import _repo_root
    from orca.daemon.lifecycle import check_daemon_running
    from orca.daemon.mcp_tools import create_mcp_server
    from orca.daemon.manager import RunManager

    repo_root = _repo_root()

    if not check_daemon_running(repo_root):
        print("Error: daemon not running. Start with: orca daemon start", file=sys.stderr)
        raise SystemExit(1)

    # First iteration: `orca mcp` creates an in-process RunManager that talks
    # to the daemon's HTTP API for run state. A full stdio-to-UDS bridge
    # (where the MCP server runs inside the daemon process and `orca mcp` is
    # pure plumbing) is deferred to a follow-up task — this works correctly
    # but means `orca mcp` is heavier than it needs to be.
    manager = RunManager(repo_root)
    server = create_mcp_server(manager)
    server.run(transport="stdio")
```

Create `src/orca/cli/tui_cmd.py`:

```python
from __future__ import annotations

import sys
from pathlib import Path


def tui_command() -> None:
    from orca.cli.daemon_cmd import _repo_root
    from orca.daemon.lifecycle import check_daemon_running

    repo_root = _repo_root()

    if not check_daemon_running(repo_root):
        print("Error: daemon not running. Start with: orca daemon start", file=sys.stderr)
        raise SystemExit(1)

    from orca.tui.app import OrcaApp

    sock_path = repo_root / ".orca" / "daemon.sock"
    app = OrcaApp.from_daemon(sock_path)
    app.run()
```

Create `src/orca/cli/list_cmd.py`:

```python
from __future__ import annotations

import asyncio
import json
import sys
from argparse import Namespace
from pathlib import Path

import aiohttp


def _repo_root() -> Path:
    from orca.cli.daemon_cmd import _repo_root

    return _repo_root()


def _daemon_sock(repo_root: Path) -> str:
    return str(repo_root / ".orca" / "daemon.sock")


def runs_command() -> None:
    repo_root = _repo_root()

    from orca.daemon.lifecycle import check_daemon_running

    if not check_daemon_running(repo_root):
        print("Error: daemon not running. Start with: orca daemon start", file=sys.stderr)
        raise SystemExit(1)

    async def fetch() -> None:
        conn = aiohttp.UnixConnector(path=_daemon_sock(repo_root))
        async with aiohttp.ClientSession(connector=conn) as session:
            async with session.get("http://localhost/api/runs") as resp:
                runs = await resp.json()
                if not runs:
                    print("No runs")
                    return
                # Simple table output
                print(f"{'RUN ID':<30} {'STATUS':<12} {'ISSUES':<8} {'BRANCH':<20}")
                print("-" * 70)
                for r in runs:
                    print(f"{r['run_id']:<30} {r['status']:<12} {r['issue_count']:<8} {r['branch']:<20}")

    asyncio.run(fetch())


def logs_command(args: Namespace) -> None:
    repo_root = _repo_root()

    from orca.daemon.lifecycle import check_daemon_running

    if not check_daemon_running(repo_root):
        print("Error: daemon not running. Start with: orca daemon start", file=sys.stderr)
        raise SystemExit(1)

    async def fetch() -> None:
        conn = aiohttp.UnixConnector(path=_daemon_sock(repo_root))
        tracking_id = args.issue_id or "unknown"
        async with aiohttp.ClientSession(connector=conn) as session:
            url = f"http://localhost/api/runs/{args.run_id}/logs/{tracking_id}?tail={args.tail}"
            async with session.get(url) as resp:
                text = await resp.text()
                if text:
                    print(text, end="")
                else:
                    print("No logs found")

    asyncio.run(fetch())
```

- [ ] **Step 4: Update pyproject.toml entry point**

In `pyproject.toml`, change:

```toml
[project.scripts]
orca = "orca.cli.main:main"
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/cli/test_main.py -v`
Expected: All pass.

- [ ] **Step 6: Run type checker**

Run: `uv run mypy src/orca/cli/`
Expected: No errors.

- [ ] **Step 7: Run all existing tests to check nothing is broken**

Run: `uv run pytest -v`
Expected: All pass. The old `runner.py` tests still pass because `runner.py` still exists.

- [ ] **Step 8: Commit**

```bash
git add src/orca/cli/ tests/cli/ pyproject.toml
git commit -m "feat(cli): add subcommand structure (daemon, run, tui, mcp, runs, logs)"
```

---

### Task 7: TUI Daemon Client

Refactor the TUI to connect to the daemon instead of polling the filesystem. Add a run list screen.

**Files:**
- Modify: `src/orca/tui/state_reader.py`
- Modify: `src/orca/tui/app.py`
- Modify: `tests/tui/test_state_reader.py`
- Modify: `tests/tui/test_app.py`

- [ ] **Step 1: Write failing test for DaemonStateReader**

In `tests/tui/test_state_reader.py`, add:

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from orca.engine.types import State
from orca.tui.state_reader import DaemonStateReader


class TestDaemonStateReader:
    @pytest.mark.asyncio()
    async def test_read_returns_state_from_http(self) -> None:
        state = State(issues={}, worker_queues={})
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={
            "run_id": "main:default",
            "status": "running",
            "state": state.to_dict(),
        })
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_resp)

        reader = DaemonStateReader.__new__(DaemonStateReader)
        reader._session = mock_session
        reader._run_id = "main:default"
        reader._last_state_dict = None
        reader._sessions = []

        result = await reader.read()
        assert result is not None
        s, sessions = result
        assert isinstance(s, State)

    @pytest.mark.asyncio()
    async def test_read_returns_none_when_unchanged(self) -> None:
        state_dict = State(issues={}, worker_queues={}).to_dict()
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={
            "run_id": "main:default",
            "status": "running",
            "state": state_dict,
        })
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_resp)

        reader = DaemonStateReader.__new__(DaemonStateReader)
        reader._session = mock_session
        reader._run_id = "main:default"
        reader._last_state_dict = state_dict  # Same as what server returns
        reader._sessions = []

        result = await reader.read()
        assert result is None  # No change
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/tui/test_state_reader.py::TestDaemonStateReader -v`
Expected: FAIL — `DaemonStateReader` doesn't exist.

- [ ] **Step 3: Add DaemonStateReader to state_reader.py**

In `src/orca/tui/state_reader.py`, add a new class below the existing `StateReader`:

```python
class DaemonStateReader:
    """Reads orchestrator state from the daemon HTTP API."""

    def __init__(self, session: aiohttp.ClientSession, run_id: str) -> None:
        self._session = session
        self._run_id = run_id
        self._last_state_dict: dict[str, Any] | None = None
        self._sessions: list[dict[str, Any]] = []

    async def read(self) -> tuple[State, list[dict[str, Any]]] | None:
        """Fetch state from daemon. Returns None if unchanged."""
        async with self._session.get(f"http://localhost/api/runs/{self._run_id}") as resp:
            if resp.status != 200:
                return None
            data = await resp.json()

        state_dict = data.get("state")
        if state_dict == self._last_state_dict:
            return None

        self._last_state_dict = state_dict
        state = State.from_dict(state_dict)
        return state, self._sessions

    @property
    def sessions(self) -> list[dict[str, Any]]:
        return self._sessions

    def reset(self) -> None:
        self._last_state_dict = None
```

Add the import at the top of `state_reader.py`:

```python
from typing import Any

import aiohttp
```

- [ ] **Step 4: Add from_daemon classmethod to OrcaApp**

In `src/orca/tui/app.py`, add a classmethod:

```python
    @classmethod
    def from_daemon(cls, sock_path: Path) -> OrcaApp:
        """Create an OrcaApp that connects to the daemon."""
        app = cls.__new__(cls)
        app._daemon_sock = sock_path
        app._daemon_mode = True
        return app
```

This is a stub for now. The full TUI refactor (run list screen, daemon-connected polling) will be iterated on once the daemon is running end-to-end.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/tui/test_state_reader.py -v`
Expected: All pass (both old and new tests).

- [ ] **Step 6: Run type checker**

Run: `uv run mypy src/orca/tui/state_reader.py`
Expected: No errors.

- [ ] **Step 7: Commit**

```bash
git add src/orca/tui/state_reader.py src/orca/tui/app.py tests/tui/test_state_reader.py
git commit -m "feat(tui): add DaemonStateReader for daemon-connected TUI"
```

---

### Task 8: Integration Test

End-to-end test: start daemon in-process, submit a run via HTTP, query state via MCP tools.

**Files:**
- Create: `tests/daemon/test_integration.py`

- [ ] **Step 1: Write integration test**

Create `tests/daemon/test_integration.py`:

```python
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient

from orca.daemon.http_api import create_app
from orca.daemon.manager import RunManager, RunStatus
from orca.daemon.mcp_tools import create_mcp_server


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """Minimal repo with orca.yml and task file."""
    config = """\
issue:
  fields:
    title:
      type: string
      description: Title
states:
  todo:
    worker:
      kind: claude-code
      prompt: prompts/todo.md
      result_format:
        outcome:
          type: enum
          values: [done]
          description: Outcome
    on:
      done: complete
  complete:
    terminal: true
initial: todo
"""
    (tmp_path / "orca.yml").write_text(config)
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "todo.md").write_text("Do: {{ issue.title }}")
    (tmp_path / "task.md").write_text("title: Integration test task")
    return tmp_path


class TestDaemonIntegration:
    def test_http_status_and_list(self, repo: Path) -> None:
        """Status endpoint works, list runs starts empty."""
        manager = RunManager(repo)
        client = TestClient(create_app(manager))

        resp = client.get("/api/status")
        assert resp.status_code == 200
        assert resp.json()["active_runs"] == 0

        resp = client.get("/api/runs")
        assert resp.json() == []

    def test_mcp_status_and_list(self, repo: Path) -> None:
        """MCP tools match HTTP API results."""
        manager = RunManager(repo)
        server = create_mcp_server(manager)

        async def check() -> None:
            result = await server._tool_manager.call_tool("orca_daemon_status", {})
            data = json.loads(result[0].text)
            assert data["active_runs"] == 0

            result = await server._tool_manager.call_tool("orca_list_runs", {})
            data = json.loads(result[0].text)
            assert data == []

        asyncio.run(check())
```

- [ ] **Step 2: Run the integration test**

Run: `uv run pytest tests/daemon/test_integration.py -v`
Expected: All pass.

- [ ] **Step 3: Commit**

```bash
git add tests/daemon/test_integration.py
git commit -m "test(daemon): add integration test for HTTP API and MCP tools"
```

---

### Task 9: Linting and Type-Checking Pass

Final cleanup: run all linters, fix any issues, ensure full test suite passes.

**Files:**
- Potentially any file from previous tasks

- [ ] **Step 1: Run ruff**

Run: `uv run ruff check .`
Expected: No errors. If any, fix them.

- [ ] **Step 2: Run ruff format check**

Run: `uv run ruff format --check .`
Expected: No reformatting needed. If needed, run `uv run ruff format .`.

- [ ] **Step 3: Run mypy**

Run: `uv run mypy src/`
Expected: No errors.

- [ ] **Step 4: Run full test suite**

Run: `uv run pytest -v`
Expected: All tests pass.

- [ ] **Step 5: Fix any issues and commit**

If any linting/typing/test issues were found:

```bash
git add -u
git commit -m "fix: resolve linting and type-checking issues"
```

- [ ] **Step 6: Final commit if clean**

If no issues found, no commit needed. Verify git status is clean.

Run: `git status`
Expected: nothing to commit, working tree clean.
