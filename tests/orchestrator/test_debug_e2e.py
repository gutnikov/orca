"""E2E coverage of --debug mode. Uses a fake worker; exercises the accept branch.

restart and modify_restart variants are skipped pending fuller harness wiring
(they require worktree reset which needs real git branching via WorktreeManager).
"""

from __future__ import annotations

import asyncio
import contextlib
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from orca.engine import parse_config, reduce
from orca.engine.types import CreateEvent, DebugReviewSnapshot, DispatchWorkerEffect, State
from orca.orchestrator.branches import BranchMap
from orca.orchestrator.orchestrator import Orchestrator
from orca.orchestrator.persistence import Persistence
from orca.orchestrator.worker import WorkerOutcome, WorkerSuccess
from orca.orchestrator.worktree import WorktreeManager

# ---------------------------------------------------------------------------
# Minimal single-state workflow: implementing -> done
# ---------------------------------------------------------------------------

SIMPLE_DEBUG_CONFIG = """\
issue:
  fields:
    title:
      type: string
      description: Title
states:
  implementing:
    worker:
      kind: claude-code
      prompt: prompts/implementing.md
      result_format:
        outcome:
          type: enum
          values: [done]
          description: outcome
    on:
      done: done
initial: implementing
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class GitWorktreeManager(WorktreeManager):
    """WorktreeManager that creates plain directories backed by the test repo.

    Returns the repo root for every issue so that git commands (current_head,
    build_snapshot) work against a real git repository.
    """

    def __init__(self, repo: Path) -> None:
        super().__init__(repo, "main")
        self._repo = repo

    async def create(self, issue_id: str, branch_name: str, parent_branch: str) -> Path:
        # Return the repo root — it's a real git repo, so current_head works.
        return self._repo

    def resolve(self, branch_name: str) -> Path:
        return self._repo


class MockWorker:
    """Worker that returns a scripted outcome on each call.

    Satisfies the Worker Protocol so that it can be passed to Orchestrator.
    """

    def __init__(self, outcome: WorkerOutcome) -> None:
        self.outcome = outcome
        self.call_count = 0

    async def execute(  # noqa: PLR0913
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
        run_context: dict[str, Any] | None = None,
        unblock_event: Any = None,
        unblock_message: Any = None,
        on_blocked: Any = None,
        on_unblocked: Any = None,
        prompt_text: str | None = None,
        effort: str | None = None,
    ) -> WorkerOutcome:
        self.call_count += 1
        return self.outcome


def _now() -> str:
    return "2026-01-01T00:00:00Z"


def _counter(start: int = 0) -> Any:
    n = start

    def gen() -> str:
        nonlocal n
        n += 1
        return f"issue-{n}"

    return gen


def _init_git_repo(path: Path) -> None:
    """Create a minimal git repo with one commit at *path*."""
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=path, check=True)
    (path / "README.md").write_text("# test\n")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=path, check=True)


def _make_fake_snapshot() -> DebugReviewSnapshot:
    return DebugReviewSnapshot(
        rendered_prompt="# Implement\n",
        worker_result={"outcome": "done"},
        config_slice="",
        diff_files=[],
        base_commit="HEAD",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_debug_accept_completes_run(tmp_path: Path) -> None:
    """Start a debug run; accept the worker's output → run transitions to done."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)

    config = parse_config(SIMPLE_DEBUG_CONFIG)
    state = State(issues={}, worker_queues={})

    create_event = CreateEvent(issue_id="issue-1", fields={"title": "Test task"}, timestamp=_now())
    state, initial_effects = reduce(config, state, create_event, _counter(), _now)

    persistence = Persistence(repo, "main")
    persistence.save(state)
    branches = BranchMap(repo, "main")

    worker = MockWorker(outcome=WorkerSuccess(result={"outcome": "done"}))
    workers = {"claude-code": worker}

    orch = Orchestrator(
        config=config,
        state=state,
        root_branch="main",
        persistence=persistence,
        branches=branches,
        workers=workers,
        generate_id=_counter(),
        now=_now,
        worktree_mgr=GitWorktreeManager(repo),
        repo_root=repo,
    )
    orch.debug = True

    # Patch build_snapshot at its definition site so we don't need a full
    # worktree diff setup.  The orchestrator imports it lazily inside
    # _pause_for_debug_review, so we must patch the source module.
    fake_snapshot = _make_fake_snapshot()
    with patch(
        "orca.orchestrator.snapshot.build_snapshot",
        new=AsyncMock(return_value=fake_snapshot),
    ):
        run_task = asyncio.create_task(orch.run("issue-1", initial_effects))

        # Wait up to 10 s for the debug pause
        for _ in range(100):
            if orch.is_debug_pending("issue-1"):
                break
            await asyncio.sleep(0.1)

        assert orch.is_debug_pending("issue-1"), "Orchestrator never paused for debug review"

        # Submit accept — no inline comments
        orch.submit_debug_decision("issue-1", "accept", [])

        # Run should finish promptly after the decision
        await asyncio.wait_for(run_task, timeout=15)

    assert orch.state.issues["issue-1"].state == "done", f"Expected 'done', got {orch.state.issues['issue-1'].state!r}"
    assert worker.call_count == 1, f"Expected worker called once, got {worker.call_count}"


@pytest.mark.asyncio()
async def test_debug_restart_re_dispatches(tmp_path: Path) -> None:
    pytest.skip(
        "E2E harness wiring TBD — exercises orchestrator restart path; "
        "needs WorktreeManager.reset_to with real git branching. "
        "Use orch.submit_debug_decision(_, 'restart', []) and assert worker.call_count == 2."
    )


@pytest.mark.asyncio()
async def test_debug_modify_restart_path(tmp_path: Path) -> None:
    pytest.skip(
        "E2E harness wiring TBD — exercises modify_restart + orca_restart_state path; "
        "needs WorktreeManager.reset_to with real git branching."
    )


@pytest.mark.asyncio()
async def test_debug_modify_restart_does_not_deadlock(tmp_path: Path) -> None:
    """After modify_restart, the run loop must wait (not raise DeadlockError).

    Regression for 0.5.11: the user clicked "Modify prompt + restart" in the
    web UI and the daemon flipped the run to FAILED status because the
    orchestrator's deadlock check saw empty _in_flight + no pending effects
    and bailed out. modify_pending is an external-unblock waiting state —
    the host calls orca_restart_state which spawns the worker directly.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)

    config = parse_config(SIMPLE_DEBUG_CONFIG)
    state = State(issues={}, worker_queues={})

    create_event = CreateEvent(issue_id="issue-1", fields={"title": "Test task"}, timestamp=_now())
    state, initial_effects = reduce(config, state, create_event, _counter(), _now)

    persistence = Persistence(repo, "main")
    persistence.save(state)
    branches = BranchMap(repo, "main")

    worker = MockWorker(outcome=WorkerSuccess(result={"outcome": "done"}))
    workers = {"claude-code": worker}

    orch = Orchestrator(
        config=config,
        state=state,
        root_branch="main",
        persistence=persistence,
        branches=branches,
        workers=workers,
        generate_id=_counter(),
        now=_now,
        worktree_mgr=GitWorktreeManager(repo),
        repo_root=repo,
    )
    orch.debug = True

    fake_snapshot = _make_fake_snapshot()
    with patch(
        "orca.orchestrator.snapshot.build_snapshot",
        new=AsyncMock(return_value=fake_snapshot),
    ):
        run_task = asyncio.create_task(orch.run("issue-1", initial_effects))

        for _ in range(100):
            if orch.is_debug_pending("issue-1"):
                break
            await asyncio.sleep(0.1)

        assert orch.is_debug_pending("issue-1"), "Orchestrator never paused for debug review"

        orch.submit_debug_decision("issue-1", "modify_restart", [])

        # The run loop should NOT crash after the modify_restart decision —
        # it should sit idle waiting for orca_restart_state. Give it 2s to
        # demonstrate that. Pre-fix, this raised DeadlockError immediately.
        await asyncio.sleep(2.0)
        assert not run_task.done(), (
            "Run task ended after modify_restart — orchestrator should wait for restart_state. "
            f"Exception: {run_task.exception() if run_task.done() else None}"
        )

        issue = orch.state.issues["issue-1"]
        assert issue.modify_pending, "Issue should be in modify_pending state"
        assert not issue.debug_pending, "debug_pending should be cleared after modify_restart"

        # Cancel the run cleanly so the test exits.
        run_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await run_task
