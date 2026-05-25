from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from orca.engine import parse_config, reduce
from orca.engine.types import CreateEvent, DispatchWorkerEffect, State, StateMachineConfig
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

    async def test_flow_root_prompt_resolution(self, tmp_path: Path) -> None:
        """When flow_root is set, prompt templates resolve relative to it, not repo_root."""
        flow_dir = tmp_path / "external-flows"
        flow_dir.mkdir()
        prompt_dir = flow_dir / "prompts"
        prompt_dir.mkdir()
        (prompt_dir / "todo.md").write_text("External: {{ issue.fields.title }}")
        (prompt_dir / "impl.md").write_text("External impl: {{ issue.fields.title }}")

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
            repo_root=tmp_path,
            flow_root=flow_dir,
        )

        await orchestrator.run("issue-1", initial_effects)
        assert orchestrator.state.issues["issue-1"].state == "done"

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


class TestOrchestratorAccessors:
    """Tests for Orchestrator public accessors and session control methods."""

    def _make_orchestrator(self, tmp_path: Path) -> Orchestrator:
        config = parse_config(SIMPLE_CONFIG)
        state = State(issues={}, worker_queues={})
        persistence = Persistence(tmp_path, "main")
        branches = BranchMap(tmp_path, "main")
        worker = MockWorker(outcomes={})
        return Orchestrator(
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

    def test_state_property(self, tmp_path: Path) -> None:
        orchestrator = self._make_orchestrator(tmp_path)
        state = orchestrator.state
        assert isinstance(state, State)
        assert state.issues == {}

    def test_config_property(self, tmp_path: Path) -> None:
        orchestrator = self._make_orchestrator(tmp_path)
        config = orchestrator.config
        assert isinstance(config, StateMachineConfig)
        # SIMPLE_CONFIG has one unnamed type, parsed as "default"
        assert "default" in config.types
        assert "todo" in config.types["default"].states

    def test_get_session_log_missing(self, tmp_path: Path) -> None:
        orchestrator = self._make_orchestrator(tmp_path)
        assert orchestrator.get_session_log("nonexistent") == ""

    def test_get_session_log_reads_file(self, tmp_path: Path) -> None:
        orchestrator = self._make_orchestrator(tmp_path)
        # Write a fake log file
        log_file = tmp_path / "session.log"
        lines = [f"line {i}" for i in range(1, 11)]
        log_file.write_text("\n".join(lines) + "\n")
        # Register the log path
        orchestrator.session_log_paths["tid-1"] = str(log_file)
        # Full log
        full = orchestrator.get_session_log("tid-1")
        assert "line 1" in full
        assert "line 10" in full
        # Tail 3 lines
        tail = orchestrator.get_session_log("tid-1", tail=3)
        tail_lines = tail.strip().split("\n")
        assert len(tail_lines) == 3
        assert "line 10" in tail

    def test_hot_cold_session(self, tmp_path: Path) -> None:
        orchestrator = self._make_orchestrator(tmp_path)
        assert "s1" not in orchestrator.hot_sessions
        orchestrator.set_hot_session("s1")
        assert "s1" in orchestrator.hot_sessions
        orchestrator.set_cold_session("s1")
        assert "s1" not in orchestrator.hot_sessions
