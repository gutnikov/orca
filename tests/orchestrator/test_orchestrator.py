from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from orca.engine import parse_config, reduce
from orca.engine.types import CreateEvent, DispatchWorkerEffect, State
from orca.orchestrator.branches import BranchMap
from orca.orchestrator.orchestrator import Orchestrator
from orca.orchestrator.persistence import Persistence
from orca.orchestrator.worker import WorkerFailure, WorkerOutcome, WorkerSuccess
from orca.orchestrator.worktree import WorktreeManager


class FakeWorktreeManager(WorktreeManager):
    """WorktreeManager substitute that creates plain directories instead of git worktrees."""

    def __init__(self, base: Path) -> None:
        super().__init__(base, "main")

    async def create(self, issue_id: str, branch_name: str, parent_branch: str) -> Path:
        p = self.resolve(branch_name)
        p.mkdir(parents=True, exist_ok=True)
        return p


class MockWorker:
    """Worker that returns predefined outcomes by issue state."""

    def __init__(self, outcomes: dict[str, WorkerOutcome]) -> None:
        self.outcomes = outcomes
        self.calls: list[tuple[str, str]] = []  # (issue_id, state)

    async def execute(
        self,
        effect: DispatchWorkerEffect,
        workdir: Path,
        result_path: Path,
        prompt_path: Path | None = None,
    ) -> WorkerOutcome:
        self.calls.append((effect.issue_id, effect.state))
        return self.outcomes.get(effect.state, WorkerFailure(error="no mock"))


def _counter(start: int = 0) -> Any:
    n = start

    def gen() -> str:
        nonlocal n
        n += 1
        return f"issue-{n}"

    return gen


def _now() -> str:
    return "2026-01-01T00:00:00Z"


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
  done:
    terminal: true
initial: todo
"""


@pytest.mark.asyncio()
class TestOrchestrator:
    async def test_simple_run_to_completion(self, tmp_path: Path) -> None:
        """Create issue, run orchestrator with mock worker that returns success for both states,
        assert root issue reaches 'done'."""
        config = parse_config(SIMPLE_CONFIG)
        state = State(issues={}, worker_queues={})

        # Create the issue via reducer to get initial effects
        create_event = CreateEvent(issue_id="issue-1", fields={"title": "Test"}, timestamp=_now())
        state, initial_effects = reduce(config, state, create_event, _counter(), _now)

        persistence = Persistence(tmp_path, "main")
        persistence.save(state)

        branches = BranchMap(tmp_path, "main")

        worker = MockWorker(
            outcomes={
                "todo": WorkerSuccess(result={"outcome": "start"}),
                "implementing": WorkerSuccess(result={"outcome": "complete"}),
            }
        )
        workers = {"claude-code": worker}

        orchestrator = Orchestrator(
            config=config,
            state=state,
            root_branch="main",
            persistence=persistence,
            branches=branches,
            workers=workers,
            generate_id=_counter(),
            now=_now,
            worktree_mgr=FakeWorktreeManager(tmp_path),
        )

        await orchestrator.run("issue-1", initial_effects)

        final_state = orchestrator.state
        assert "issue-1" in final_state.issues
        assert final_state.issues["issue-1"].state == "done"

    async def test_worker_failure_retries(self, tmp_path: Path) -> None:
        """Mock worker that fails first time on 'todo' then succeeds,
        assert eventually reaches terminal."""
        config = parse_config(SIMPLE_CONFIG)
        state = State(issues={}, worker_queues={})

        create_event = CreateEvent(issue_id="issue-1", fields={"title": "Test"}, timestamp=_now())
        state, initial_effects = reduce(config, state, create_event, _counter(), _now)

        persistence = Persistence(tmp_path, "main")
        persistence.save(state)

        branches = BranchMap(tmp_path, "main")

        # Stateful mock: fail first call on 'todo', then succeed
        call_count: dict[str, int] = {}

        class StatefulMockWorker:
            calls: list[tuple[str, str]] = []

            async def execute(
                self,
                effect: DispatchWorkerEffect,
                workdir: Path,
                result_path: Path,
                prompt_path: Path | None = None,
            ) -> WorkerOutcome:
                self.calls.append((effect.issue_id, effect.state))
                count = call_count.get(effect.state, 0)
                call_count[effect.state] = count + 1
                if effect.state == "todo" and count == 0:
                    return WorkerFailure(error="transient failure")
                if effect.state == "todo":
                    return WorkerSuccess(result={"outcome": "start"})
                if effect.state == "implementing":
                    return WorkerSuccess(result={"outcome": "complete"})
                return WorkerFailure(error="no mock")

        stateful_worker = StatefulMockWorker()
        workers = {"claude-code": stateful_worker}

        orchestrator = Orchestrator(
            config=config,
            state=state,
            root_branch="main",
            persistence=persistence,
            branches=branches,
            workers=workers,
            generate_id=_counter(),
            now=_now,
            worktree_mgr=FakeWorktreeManager(tmp_path),
        )

        await orchestrator.run("issue-1", initial_effects)

        final_state = orchestrator.state
        assert "issue-1" in final_state.issues
        assert final_state.issues["issue-1"].state == "done"
        # Verify we had at least 2 calls on 'todo' (one failure + one success)
        assert call_count.get("todo", 0) >= 2


@pytest.mark.asyncio()
class TestInsightsLoop:
    async def test_insights_not_started_when_no_worker(self, tmp_path: Path) -> None:
        """Default (no insights_worker) means no insights.md created."""
        config = parse_config(SIMPLE_CONFIG)
        state = State(issues={}, worker_queues={})
        create_event = CreateEvent(issue_id="issue-1", fields={"title": "Test"}, timestamp=_now())
        state, initial_effects = reduce(config, state, create_event, _counter(), _now)

        persistence = Persistence(tmp_path, "main")
        persistence.save(state)
        branches = BranchMap(tmp_path, "main")

        worker = MockWorker(
            outcomes={
                "todo": WorkerSuccess(result={"outcome": "start"}),
                "implementing": WorkerSuccess(result={"outcome": "complete"}),
            }
        )

        orchestrator = Orchestrator(
            config=config,
            state=state,
            root_branch="main",
            persistence=persistence,
            branches=branches,
            workers={"claude-code": worker},
            generate_id=_counter(),
            now=_now,
            worktree_mgr=FakeWorktreeManager(tmp_path),
        )

        await orchestrator.run("issue-1", initial_effects)
        assert orchestrator.state.issues["issue-1"].state == "done"
        # No insights.md should exist
        run_dir = tmp_path / ".orca" / "runs" / "main"
        insights_path = run_dir / "insights.md"
        assert not insights_path.exists()

    async def test_insights_worker_called_when_provided(self, tmp_path: Path) -> None:
        """With insights_worker provided, execute_raw is called."""
        config = parse_config(SIMPLE_CONFIG)
        state = State(issues={}, worker_queues={})
        create_event = CreateEvent(issue_id="issue-1", fields={"title": "Test"}, timestamp=_now())
        state, initial_effects = reduce(config, state, create_event, _counter(), _now)

        persistence = Persistence(tmp_path, "main")
        persistence.save(state)
        branches = BranchMap(tmp_path, "main")

        worker = MockWorker(
            outcomes={
                "todo": WorkerSuccess(result={"outcome": "start"}),
                "implementing": WorkerSuccess(result={"outcome": "complete"}),
            }
        )

        mock_insights = MagicMock()
        mock_insights.execute_raw = AsyncMock(return_value=WorkerSuccess(result={}))

        orchestrator = Orchestrator(
            config=config,
            state=state,
            root_branch="main",
            persistence=persistence,
            branches=branches,
            workers={"claude-code": worker},
            generate_id=_counter(),
            now=_now,
            worktree_mgr=FakeWorktreeManager(tmp_path),
            repo_root=tmp_path,
            insights_worker=mock_insights,
            insights_interval=0.05,
        )

        await orchestrator.run("issue-1", initial_effects)
        assert orchestrator.state.issues["issue-1"].state == "done"
        # The final insights run should have been called at minimum
        assert mock_insights.execute_raw.call_count >= 1
