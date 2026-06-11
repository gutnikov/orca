"""Regression tests for run-loop lifecycle bugs.

Covers:
- Debug pause skipped (not crashed) when the review snapshot can't be built.
- stop() racing run()'s asyncio.wait must not KeyError or surface
  CancelledError as a worker failure.
- run() must tear down the capture task and in-flight workers on
  exceptional exit (DeadlockError, external cancellation).
- restart_state() must mutate the *current* issue object after awaiting
  the worktree reset, not a stale pre-await copy.
"""

from __future__ import annotations

import asyncio
import copy
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from orca.engine import parse_config, reduce
from orca.engine.types import CreateEvent, DispatchWorkerEffect, State
from orca.orchestrator.branches import BranchMap
from orca.orchestrator.orchestrator import DeadlockError, Orchestrator
from orca.orchestrator.persistence import Persistence
from orca.orchestrator.worker import WorkerFailure, WorkerOutcome, WorkerSuccess
from orca.orchestrator.worktree import WorktreeManager

SIMPLE_CONFIG = """\
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
          values: [start]
          description: Decision
    on:
      start: implementing
  implementing:
    worker:
      kind: claude-code
      prompt: prompts/impl.md
      result_format:
        outcome:
          type: enum
          values: [complete]
          description: Outcome
    on:
      complete: done
initial: todo
"""


class FakeWorktreeManager(WorktreeManager):
    """WorktreeManager substitute that creates plain directories instead of git worktrees."""

    def __init__(self, base: Path) -> None:
        super().__init__(base, "main")

    async def create(self, issue_id: str, branch_name: str, parent_branch: str) -> Path:
        p = self.resolve(branch_name)
        p.mkdir(parents=True, exist_ok=True)
        return p


class GitWorktreeManager(WorktreeManager):
    """WorktreeManager that returns the (real git) repo root for every issue."""

    def __init__(self, repo: Path) -> None:
        super().__init__(repo, "main")
        self._repo = repo

    async def create(self, issue_id: str, branch_name: str, parent_branch: str) -> Path:
        return self._repo

    def resolve(self, branch_name: str) -> Path:
        return self._repo


class MockWorker:
    """Worker that returns predefined outcomes by issue state."""

    def __init__(self, outcomes: dict[str, WorkerOutcome]) -> None:
        self.outcomes = outcomes
        self.calls: list[tuple[str, str]] = []

    async def execute(
        self,
        effect: DispatchWorkerEffect,
        workdir: Path,
        result_path: Path,
        prompt_path: Path | None = None,
        inactivity_timeout: int | None = None,
        pty_session: Any = None,
        env: dict[str, str] | None = None,
        model: str | None = None,
        extra_args: list[str] | None = None,
        session_manifest: Any = None,
        session_id: str | None = None,
        run_context: Any = None,
        unblock_event: Any = None,
        unblock_message: Any = None,
        on_blocked: Any = None,
        on_unblocked: Any = None,
        prompt_text: str | None = None,
        effort: str | None = None,
        max_prompt_chars: int | None = None,
    ) -> WorkerOutcome:
        self.calls.append((effect.issue_id, effect.state))
        return self.outcomes.get(effect.state, WorkerFailure(error="no mock"))


class HangingWorker:
    """Worker that never returns — used to keep a task in flight."""

    async def execute(self, *args: Any, **kwargs: Any) -> WorkerOutcome:
        await asyncio.Event().wait()
        return WorkerFailure(error="unreachable")


def _counter(start: int = 0) -> Any:
    n = start

    def gen() -> str:
        nonlocal n
        n += 1
        return f"issue-{n}"

    return gen


def _now() -> str:
    return "2026-01-01T00:00:00Z"


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=path, check=True)
    (path / "README.md").write_text("# test\n")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=path, check=True)


def _make_orchestrator(
    tmp_path: Path,
    workers: dict[str, Any],
    *,
    debug: bool = False,
    worktree_mgr: WorktreeManager | None = None,
    repo_root: Path | None = None,
) -> tuple[Orchestrator, list[Any]]:
    config = parse_config(SIMPLE_CONFIG)
    state = State(issues={}, worker_queues={})
    create_event = CreateEvent(issue_id="issue-1", fields={"title": "Test"}, timestamp=_now())
    state, initial_effects = reduce(config, state, create_event, _counter(), _now)

    persistence = Persistence(tmp_path, "main")
    persistence.save(state)
    branches = BranchMap(tmp_path, "main")

    orchestrator = Orchestrator(
        config=config,
        state=state,
        root_branch="main",
        persistence=persistence,
        branches=branches,
        workers=workers,
        generate_id=_counter(),
        now=_now,
        worktree_mgr=worktree_mgr or FakeWorktreeManager(tmp_path),
        repo_root=repo_root,
    )
    orchestrator.debug = debug
    return orchestrator, initial_effects


def _live_capture_tasks() -> list[asyncio.Task[Any]]:
    return [
        t
        for t in asyncio.all_tasks()
        if not t.done() and t.get_coro().__qualname__.endswith("_session_capture_loop")  # type: ignore[union-attr]
    ]


# ---------------------------------------------------------------------------
# Bug 1: debug pause must be skipped (not crash) when snapshot is unavailable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_debug_pause_skipped_when_snapshot_is_none(tmp_path: Path) -> None:
    """No git repo → state_base_commit is None → snapshot is None.

    Pre-fix: _pause_for_debug_review returned early without registering a
    decision event and run() crashed with KeyError. The run must instead
    fall through to the normal transition and complete.
    """
    worker = MockWorker(
        outcomes={
            "todo": WorkerSuccess(result={"outcome": "start"}),
            "implementing": WorkerSuccess(result={"outcome": "complete"}),
        }
    )
    orch, initial_effects = _make_orchestrator(tmp_path, {"claude-code": worker}, debug=True)

    await asyncio.wait_for(orch.run("issue-1", initial_effects), timeout=30)

    assert orch.state.issues["issue-1"].state == "done"
    assert not orch.is_debug_pending("issue-1")


@pytest.mark.asyncio()
async def test_debug_pause_skipped_when_snapshot_build_raises(tmp_path: Path) -> None:
    """build_snapshot raising must not fail the whole run in debug mode."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)

    worker = MockWorker(
        outcomes={
            "todo": WorkerSuccess(result={"outcome": "start"}),
            "implementing": WorkerSuccess(result={"outcome": "complete"}),
        }
    )
    orch, initial_effects = _make_orchestrator(
        repo,
        {"claude-code": worker},
        debug=True,
        worktree_mgr=GitWorktreeManager(repo),
        repo_root=repo,
    )

    with patch(
        "orca.orchestrator.snapshot.build_snapshot",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ):
        await asyncio.wait_for(orch.run("issue-1", initial_effects), timeout=30)

    assert orch.state.issues["issue-1"].state == "done"
    assert not orch.is_debug_pending("issue-1")


# ---------------------------------------------------------------------------
# Bug 2: stop() racing run()'s asyncio.wait
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_stop_during_run_does_not_keyerror(tmp_path: Path) -> None:
    """stop() clears _in_flight while run() is parked in asyncio.wait.

    Pre-fix: run() crashed with KeyError on _in_flight.pop(task), or the
    cancelled task's CancelledError escaped the `except Exception`. The
    run loop must reap the cancelled worker quietly; the subsequent
    DeadlockError (nothing left in flight) is the expected exit.
    """
    orch, initial_effects = _make_orchestrator(tmp_path, {"claude-code": HangingWorker()})

    run_task = asyncio.create_task(orch.run("issue-1", initial_effects))

    for _ in range(100):
        if orch._in_flight:
            break
        await asyncio.sleep(0.05)
    assert orch._in_flight, "Worker never went in-flight"

    await orch.stop()

    with pytest.raises(DeadlockError):
        await asyncio.wait_for(run_task, timeout=15)

    # No failure event recorded for the cancelled worker
    issue = orch.state.issues["issue-1"]
    assert issue.failure_count == 0


# ---------------------------------------------------------------------------
# Bug 3: run() must clean up capture task and workers on exceptional exit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_deadlock_exit_cancels_capture_task(tmp_path: Path) -> None:
    """DeadlockError must not leak the session-capture background task."""
    orch, _ = _make_orchestrator(tmp_path, {"claude-code": MockWorker(outcomes={})})

    with pytest.raises(DeadlockError):
        # No initial effects, nothing in flight → immediate deadlock.
        await orch.run("issue-1", [])

    assert _live_capture_tasks() == []


@pytest.mark.asyncio()
async def test_external_cancellation_cleans_up_workers(tmp_path: Path) -> None:
    """Cancelling the run task (daemon stop path) must reap workers and sessions."""
    orch, initial_effects = _make_orchestrator(tmp_path, {"claude-code": HangingWorker()})

    run_task = asyncio.create_task(orch.run("issue-1", initial_effects))

    for _ in range(100):
        if orch._in_flight:
            break
        await asyncio.sleep(0.05)
    assert orch._in_flight, "Worker never went in-flight"
    worker_tasks = list(orch._in_flight.keys())

    run_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await run_task

    assert orch._in_flight == {}
    assert all(t.done() for t in worker_tasks)
    assert orch._tmux_sessions == {}
    assert _live_capture_tasks() == []


@pytest.mark.asyncio()
async def test_stop_after_run_finished_is_safe(tmp_path: Path) -> None:
    """stop() after run() already cleaned up must not raise (no double-cancel issues)."""
    worker = MockWorker(
        outcomes={
            "todo": WorkerSuccess(result={"outcome": "start"}),
            "implementing": WorkerSuccess(result={"outcome": "complete"}),
        }
    )
    orch, initial_effects = _make_orchestrator(tmp_path, {"claude-code": worker})

    await asyncio.wait_for(orch.run("issue-1", initial_effects), timeout=30)
    await orch.stop()

    assert orch.state.issues["issue-1"].state == "done"


# ---------------------------------------------------------------------------
# Bug 7: restart_state must re-fetch the issue after awaiting the reset
# ---------------------------------------------------------------------------


def _make_modify_pending_orchestrator(tmp_path: Path, workers: dict[str, Any]) -> Orchestrator:
    flow_dir = tmp_path / "flow"
    flow_dir.mkdir()
    (flow_dir / "default.yml").write_text(SIMPLE_CONFIG)

    config = parse_config(SIMPLE_CONFIG)
    state = State(issues={}, worker_queues={})
    create_event = CreateEvent(issue_id="issue-1", fields={"title": "Test"}, timestamp=_now())
    state, _ = reduce(config, state, create_event, _counter(), _now)

    issue = state.issues["issue-1"]
    issue.modify_pending = True
    issue.worker_active = False

    persistence = Persistence(tmp_path, "main")
    persistence.save(state)

    return Orchestrator(
        config=config,
        state=state,
        root_branch="main",
        persistence=persistence,
        branches=BranchMap(tmp_path, "main"),
        workers=workers,
        generate_id=_counter(),
        now=_now,
        worktree_mgr=FakeWorktreeManager(tmp_path),
        repo_root=tmp_path,
        flow_root=flow_dir,
    )


@pytest.mark.asyncio()
async def test_restart_state_mutates_current_issue_after_await(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A reduce during the worktree-reset await replaces self._state.

    Pre-fix: restart_state mutated the stale pre-await Issue object, so
    the persisted state kept modify_pending=True (possible double dispatch).
    """
    worker = MockWorker(outcomes={"todo": WorkerSuccess(result={"outcome": "start"})})
    orch = _make_modify_pending_orchestrator(tmp_path, {"claude-code": worker})

    async def fake_reset(issue_id: str) -> None:
        # Simulate a concurrent reduce replacing the state (reducer deep-copies)
        orch._state = copy.deepcopy(orch._state)

    monkeypatch.setattr(orch, "_reset_worktree_for_issue", fake_reset)

    try:
        await orch.restart_state("issue-1")
        issue = orch.state.issues["issue-1"]
        assert issue.modify_pending is False
        assert issue.worker_active is True
        assert issue.failure_count == 0
    finally:
        await orch.stop()


@pytest.mark.asyncio()
async def test_restart_state_handles_issue_disappearing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """If the issue vanishes during the await, restart_state must not crash."""
    worker = MockWorker(outcomes={"todo": WorkerSuccess(result={"outcome": "start"})})
    orch = _make_modify_pending_orchestrator(tmp_path, {"claude-code": worker})

    async def fake_reset(issue_id: str) -> None:
        orch._state = State(issues={}, worker_queues={})

    monkeypatch.setattr(orch, "_reset_worktree_for_issue", fake_reset)

    try:
        await orch.restart_state("issue-1")  # must not raise
        assert orch._in_flight == {}, "No worker should be dispatched for a vanished issue"
    finally:
        await orch.stop()
