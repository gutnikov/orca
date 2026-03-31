from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from orca.daemon.manager import RunManager, RunStatus
from orca.engine.types import DispatchWorkerEffect
from orca.orchestrator.worker import WorkerOutcome, WorkerSuccess

SIMPLE_CONFIG_YAML = """\
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
    ) -> WorkerOutcome:
        self.calls.append((effect.issue_id, effect.state))
        return self.outcomes.get(effect.state, WorkerSuccess(result={"outcome": "start"}))


@pytest.fixture()
def repo_root(tmp_path: Path) -> Path:
    """Create a tmp_path with an orca.yml config and a prompts/ dir."""
    config_path = tmp_path / "orca.yml"
    config_path.write_text(SIMPLE_CONFIG_YAML)
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "todo.md").write_text("Do the todo: {{ issue.fields.title }}")
    (prompts_dir / "impl.md").write_text("Implement: {{ issue.fields.title }}")
    # Create a minimal task file
    task_file = tmp_path / "task.md"
    task_file.write_text("title: Test Task\ndescription: A test task")
    return tmp_path


class TestRunManager:
    def test_create(self, repo_root: Path) -> None:
        """Empty list after creation."""
        mgr = RunManager(repo_root)
        assert mgr.list_runs() == []

    def test_run_id_format(self, repo_root: Path) -> None:
        """Run ID has format 'branch:workflow'."""
        assert RunManager.make_run_id("feat/auth", "default") == "feat/auth:default"
        assert RunManager.make_run_id("main", "develop") == "main:develop"

    @pytest.mark.asyncio()
    async def test_start_run(self, repo_root: Path) -> None:
        """Starts a run, appears in list, status RUNNING."""
        mgr = RunManager(repo_root)
        task_file = repo_root / "task.md"

        mock_worker = MockWorker(
            outcomes={
                "todo": WorkerSuccess(result={"outcome": "start"}),
                "implementing": WorkerSuccess(result={"outcome": "complete"}),
            }
        )

        with (
            patch("orca.daemon.manager.resolve_branch", return_value="feat/test"),
            patch("orca.daemon.manager.CliAgentWorker", return_value=mock_worker),
        ):
            run_id = await mgr.start_run(task_file)

        assert run_id == "feat/test:default"
        runs = mgr.list_runs()
        assert len(runs) == 1
        assert runs[0].run_id == run_id
        assert runs[0].status == RunStatus.RUNNING

        # Clean up
        await mgr.stop_all()

    @pytest.mark.asyncio()
    async def test_start_duplicate_run_errors(self, repo_root: Path) -> None:
        """ValueError when starting a run with the same ID."""
        mgr = RunManager(repo_root)
        task_file = repo_root / "task.md"

        mock_worker = MockWorker(
            outcomes={
                "todo": WorkerSuccess(result={"outcome": "start"}),
                "implementing": WorkerSuccess(result={"outcome": "complete"}),
            }
        )

        with (
            patch("orca.daemon.manager.resolve_branch", return_value="feat/dup"),
            patch("orca.daemon.manager.CliAgentWorker", return_value=mock_worker),
        ):
            await mgr.start_run(task_file)

            with pytest.raises(ValueError, match="already running"):
                await mgr.start_run(task_file)

        # Clean up
        await mgr.stop_all()

    def test_get_run_unknown(self, repo_root: Path) -> None:
        """Returns None for unknown run ID."""
        mgr = RunManager(repo_root)
        assert mgr.get_run("nonexistent:default") is None

    @pytest.mark.asyncio()
    async def test_stop_run(self, repo_root: Path) -> None:
        """Status becomes STOPPED after stop_run."""
        mgr = RunManager(repo_root)
        task_file = repo_root / "task.md"

        mock_worker = MockWorker(
            outcomes={
                "todo": WorkerSuccess(result={"outcome": "start"}),
                "implementing": WorkerSuccess(result={"outcome": "complete"}),
            }
        )

        with (
            patch("orca.daemon.manager.resolve_branch", return_value="feat/stop"),
            patch("orca.daemon.manager.CliAgentWorker", return_value=mock_worker),
        ):
            run_id = await mgr.start_run(task_file)
            await mgr.stop_run(run_id)

        info = mgr.get_run(run_id)
        assert info is not None
        assert info.status == RunStatus.STOPPED

    @pytest.mark.asyncio()
    async def test_stop_unknown_run_errors(self, repo_root: Path) -> None:
        """ValueError when stopping unknown run."""
        mgr = RunManager(repo_root)

        with pytest.raises(ValueError, match="not found"):
            await mgr.stop_run("nonexistent:default")
