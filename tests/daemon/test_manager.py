from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from orca.daemon.manager import RunManager, RunStatus, _derive_eval_name
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
        run_context: Any = None,
        unblock_event: Any = None,
        unblock_message: Any = None,
        on_blocked: Any = None,
        on_unblocked: Any = None,
        prompt_text: str | None = None,
    ) -> WorkerOutcome:
        self.calls.append((effect.issue_id, effect.state))
        return self.outcomes.get(effect.state, WorkerSuccess(result={"outcome": "start"}))


@pytest.fixture()
def repo_root(tmp_path: Path) -> Path:
    """Create a tmp_path with .orca/default.yml config and .orca/prompts/ dir."""
    orca_dir = tmp_path / ".orca"
    orca_dir.mkdir()
    config_path = orca_dir / "default.yml"
    config_path.write_text(SIMPLE_CONFIG_YAML)
    prompts_dir = orca_dir / "prompts"
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

    @pytest.mark.asyncio()
    async def test_start_run_writes_config_source(self, repo_root: Path) -> None:
        """start_run persists config_source.json in the run directory."""
        mgr = RunManager(repo_root)
        task_file = repo_root / "task.md"

        mock_worker = MockWorker(
            outcomes={
                "todo": WorkerSuccess(result={"outcome": "start"}),
                "implementing": WorkerSuccess(result={"outcome": "complete"}),
            }
        )

        with (
            patch("orca.daemon.manager.resolve_branch", return_value="main"),
            patch("orca.daemon.manager.CliAgentWorker", return_value=mock_worker),
        ):
            run_id = await mgr.start_run(task_file)

        assert run_id == "main:default"
        run_dir = repo_root / ".orca-state" / "runs" / "main" / "default"
        source_file = run_dir / "config_source.json"
        assert source_file.exists()
        source = json.loads(source_file.read_text())
        assert source["config_path"] == str((repo_root / ".orca" / "default.yml").resolve())

        await mgr.stop_all()


class TestStartRunStateRef:
    @pytest.mark.asyncio()
    async def test_resets_worktree_when_state_ref_set(self, repo_root: Path) -> None:
        """Second run starts from state_ref's tip, not the previous worktree state."""
        import subprocess as _subp

        from orca.daemon.manager import _reset_eval_worktree

        _subp.run(["git", "init", str(repo_root)], check=True, capture_output=True)
        _subp.run(
            ["git", "-C", str(repo_root), "config", "user.email", "test@test.com"],
            check=True,
            capture_output=True,
        )
        _subp.run(
            ["git", "-C", str(repo_root), "config", "user.name", "Test"],
            check=True,
            capture_output=True,
        )
        (repo_root / "README.md").write_text("init\n")
        _subp.run(["git", "-C", str(repo_root), "add", "."], check=True, capture_output=True)
        _subp.run(
            ["git", "-C", str(repo_root), "commit", "-m", "init"],
            check=True,
            capture_output=True,
        )
        _subp.run(
            ["git", "-C", str(repo_root), "checkout", "-b", "orca-eval-state/foo"],
            check=True,
            capture_output=True,
        )
        (repo_root / "fixture.txt").write_text("fixture\n")
        _subp.run(["git", "-C", str(repo_root), "add", "."], check=True, capture_output=True)
        _subp.run(
            ["git", "-C", str(repo_root), "commit", "-m", "fixture"],
            check=True,
            capture_output=True,
        )
        _subp.run(
            ["git", "-C", str(repo_root), "checkout", "main"],
            capture_output=True,
        )

        # Simulate prior run: a worktree at the eval branch with extra files.
        wt = repo_root / ".orca-state" / "worktrees" / "eval-foo"
        wt.parent.mkdir(parents=True, exist_ok=True)
        _subp.run(
            [
                "git",
                "-C",
                str(repo_root),
                "worktree",
                "add",
                "-b",
                "eval-foo",
                str(wt),
                "orca-eval-state/foo",
            ],
            check=True,
            capture_output=True,
        )
        (wt / "junk.txt").write_text("garbage\n")
        _subp.run(["git", "-C", str(wt), "add", "."], check=True, capture_output=True)
        _subp.run(
            ["git", "-C", str(wt), "commit", "-m", "garbage"],
            check=True,
            capture_output=True,
        )
        assert (wt / "junk.txt").exists()

        await _reset_eval_worktree(repo_root, branch="eval-foo", worktree_path=wt)

        assert not wt.exists()
        rc = _subp.run(
            ["git", "-C", str(repo_root), "rev-parse", "--verify", "eval-foo"],
            capture_output=True,
        ).returncode
        assert rc != 0

    @pytest.mark.asyncio()
    async def test_state_ref_rejected_for_non_eval_config(self, repo_root: Path) -> None:
        """state_ref is only meaningful for eval runs; passing it with a non-eval config errors.

        Defense-in-depth: the CLI only sends state_ref for `orca eval <name>`, but the daemon
        should also refuse a hand-crafted request that pairs state_ref with `.orca/default.yml`.
        """
        import subprocess as _subp

        _subp.run(["git", "init", str(repo_root)], check=True, capture_output=True)
        _subp.run(
            ["git", "-C", str(repo_root), "config", "user.email", "t@t"],
            check=True,
            capture_output=True,
        )
        _subp.run(
            ["git", "-C", str(repo_root), "config", "user.name", "t"],
            check=True,
            capture_output=True,
        )
        (repo_root / "seed.txt").write_text("x\n")
        _subp.run(["git", "-C", str(repo_root), "add", "."], check=True, capture_output=True)
        _subp.run(
            ["git", "-C", str(repo_root), "commit", "-m", "init"],
            check=True,
            capture_output=True,
        )
        # Create a real branch named like a state branch so the existence check passes.
        _subp.run(
            ["git", "-C", str(repo_root), "branch", "orca-eval-state/foo"],
            check=True,
            capture_output=True,
        )

        mgr = RunManager(repo_root)
        task_file = repo_root / "task.md"
        with pytest.raises(ValueError, match="state_ref is only supported for eval runs"):
            await mgr.start_run(task_file, state_ref="orca-eval-state/foo")

    @pytest.mark.asyncio()
    async def test_state_ref_run_does_not_collide_with_current_branch(self, repo_root: Path) -> None:
        """Regression for issue #12.

        When a user runs `orca eval <name>` from their normal working branch,
        `resolve_branch()` returns the current (iteration) branch. Previously the
        daemon reused that branch as the eval-run worktree's branch, which:
        - fails because `git worktree add <path> <iter-branch>` refuses when the
          iter-branch is checked out in the main repo, AND
        - risks `git branch -D <iter-branch>` deleting the user's work in
          `_reset_eval_worktree`.

        After the fix, eval runs use an eval-specific ephemeral branch derived
        from the eval name, so the iteration branch is untouched.
        """
        import subprocess as _subp

        _subp.run(["git", "init", "-b", "main", str(repo_root)], check=True, capture_output=True)
        _subp.run(
            ["git", "-C", str(repo_root), "config", "user.email", "t@t"],
            check=True,
            capture_output=True,
        )
        _subp.run(
            ["git", "-C", str(repo_root), "config", "user.name", "t"],
            check=True,
            capture_output=True,
        )
        (repo_root / "main-only.txt").write_text("from main\n")
        _subp.run(["git", "-C", str(repo_root), "add", "."], check=True, capture_output=True)
        _subp.run(
            ["git", "-C", str(repo_root), "commit", "-m", "init"],
            check=True,
            capture_output=True,
        )

        # Build orca-eval-state/foo with a DIFFERENT file (so we can tell state vs main apart).
        tmp = repo_root / ".tmp-state"
        _subp.run(
            ["git", "-C", str(repo_root), "worktree", "add", "--detach", str(tmp), "HEAD"],
            check=True,
            capture_output=True,
        )
        _subp.run(
            ["git", "-C", str(tmp), "checkout", "--orphan", "orca-eval-state/foo"],
            check=True,
            capture_output=True,
        )
        _subp.run(["git", "-C", str(tmp), "rm", "-rf", "--quiet", "."], check=True, capture_output=True)
        (tmp / "fixture.txt").write_text("from state branch\n")
        _subp.run(["git", "-C", str(tmp), "add", "."], check=True, capture_output=True)
        _subp.run(
            ["git", "-C", str(tmp), "commit", "-m", "fixture"],
            check=True,
            capture_output=True,
        )
        _subp.run(
            ["git", "-C", str(repo_root), "worktree", "remove", str(tmp)],
            check=True,
            capture_output=True,
        )

        # Scaffold the eval config under .orca/evals/foo/ — derived eval_name = "foo".
        eval_dir = repo_root / ".orca" / "evals" / "foo"
        eval_dir.mkdir(parents=True)
        (eval_dir / "eval-flow.yml").write_text(SIMPLE_CONFIG_YAML)
        (eval_dir / "input.md").write_text("title: Test\ndescription: D\nstate_ref: orca-eval-state/foo\n")

        mgr = RunManager(repo_root)
        mock_worker = MockWorker(
            outcomes={
                "todo": WorkerSuccess(result={"outcome": "start"}),
                "implementing": WorkerSuccess(result={"outcome": "complete"}),
            }
        )

        # NO patch on resolve_branch — let it return the real current branch ("main").
        # This is the realistic scenario the issue reports.
        with patch("orca.daemon.manager.CliAgentWorker", return_value=mock_worker):
            await mgr.start_run(
                task_file=eval_dir / "input.md",
                workflow=str(eval_dir / "eval-flow.yml"),
                state_ref="orca-eval-state/foo",
            )
            await mgr.stop_all()

        # The user's iteration branch must be untouched.
        rc = _subp.run(
            ["git", "-C", str(repo_root), "rev-parse", "--verify", "main"],
            capture_output=True,
        ).returncode
        assert rc == 0, "main (iteration branch) was deleted — data loss bug"

        # The run worktree must exist and contain the state branch's fixture, NOT main's.
        # The fix uses an eval-specific branch name `orca-eval-run-foo`.
        run_worktree = repo_root / ".orca-state" / "worktrees" / "orca-eval-run-foo"
        assert run_worktree.exists(), f"expected run worktree at {run_worktree}"
        assert (run_worktree / "fixture.txt").exists(), "run worktree missing state branch fixture"
        assert (run_worktree / "fixture.txt").read_text() == "from state branch\n"
        assert not (run_worktree / "main-only.txt").exists(), (
            "run worktree contains main's content — branched off wrong tip"
        )

    @pytest.mark.asyncio()
    async def test_eval_start_after_completed_run_is_fresh(self, repo_root: Path) -> None:
        """A second eval invocation should read updated input.md and state_ref tip."""
        import subprocess as _subp

        _subp.run(["git", "init", "-b", "main", str(repo_root)], check=True, capture_output=True)
        _subp.run(["git", "-C", str(repo_root), "config", "user.email", "t@t"], check=True, capture_output=True)
        _subp.run(["git", "-C", str(repo_root), "config", "user.name", "t"], check=True, capture_output=True)
        _subp.run(["git", "-C", str(repo_root), "add", "."], check=True, capture_output=True)
        _subp.run(["git", "-C", str(repo_root), "commit", "-m", "init"], check=True, capture_output=True)

        author_worktree = repo_root / ".orca-state" / "eval-states" / "foo"
        _subp.run(
            ["git", "-C", str(repo_root), "worktree", "add", "--detach", str(author_worktree), "HEAD"],
            check=True,
            capture_output=True,
        )
        _subp.run(
            ["git", "-C", str(author_worktree), "checkout", "--orphan", "orca-eval-state/foo"],
            check=True,
            capture_output=True,
        )
        _subp.run(
            ["git", "-C", str(author_worktree), "rm", "-rf", "--quiet", "."],
            check=True,
            capture_output=True,
        )
        (author_worktree / "fixture.txt").write_text("seed one\n")
        _subp.run(["git", "-C", str(author_worktree), "add", "."], check=True, capture_output=True)
        _subp.run(
            ["git", "-C", str(author_worktree), "commit", "-m", "seed one"],
            check=True,
            capture_output=True,
        )

        eval_dir = repo_root / ".orca" / "evals" / "foo"
        eval_dir.mkdir(parents=True)
        (eval_dir / "eval-flow.yml").write_text(SIMPLE_CONFIG_YAML)
        input_file = eval_dir / "input.md"
        input_file.write_text("title: First\ndescription: D\nstate_ref: orca-eval-state/foo\n")

        class RecordingWorker(MockWorker):
            def __init__(self) -> None:
                super().__init__(
                    outcomes={
                        "todo": WorkerSuccess(result={"outcome": "start"}),
                        "implementing": WorkerSuccess(result={"outcome": "complete"}),
                    }
                )
                self.seen: list[tuple[str, str, str]] = []

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
            ) -> WorkerOutcome:
                self.seen.append(
                    (
                        effect.state,
                        str(effect.issue["fields"]["title"]),
                        (workdir / "fixture.txt").read_text(),
                    )
                )
                return await super().execute(
                    effect,
                    workdir,
                    result_path,
                    prompt_path,
                    inactivity_timeout,
                    pty_session,
                    env,
                    model,
                    extra_args,
                    session_manifest,
                    session_id,
                    run_context,
                    unblock_event,
                    unblock_message,
                    on_blocked,
                    on_unblocked,
                    prompt_text,
                )

        mgr = RunManager(repo_root)
        worker = RecordingWorker()

        with patch("orca.daemon.manager.CliAgentWorker", return_value=worker):
            run_id = await mgr.start_run(
                task_file=input_file,
                workflow=str(eval_dir / "eval-flow.yml"),
                state_ref="orca-eval-state/foo",
            )
            first_info = mgr.get_run(run_id)
            assert first_info is not None and first_info.task is not None
            await first_info.task

            (author_worktree / "fixture.txt").write_text("seed two\n")
            _subp.run(["git", "-C", str(author_worktree), "add", "fixture.txt"], check=True, capture_output=True)
            _subp.run(
                ["git", "-C", str(author_worktree), "commit", "-m", "seed two"],
                check=True,
                capture_output=True,
            )
            input_file.write_text("title: Second\ndescription: D\nstate_ref: orca-eval-state/foo\n")

            run_id_2 = await mgr.start_run(
                task_file=input_file,
                workflow=str(eval_dir / "eval-flow.yml"),
                state_ref="orca-eval-state/foo",
            )
            second_info = mgr.get_run(run_id_2)
            assert second_info is not None and second_info.task is not None
            await second_info.task

        assert run_id_2 == run_id == "orca-eval-run-foo:eval-flow"
        assert worker.seen == [
            ("todo", "First", "seed one\n"),
            ("implementing", "First", "seed one\n"),
            ("todo", "Second", "seed two\n"),
            ("implementing", "Second", "seed two\n"),
        ]

    @pytest.mark.asyncio()
    async def test_rejects_unresolved_state_ref(self, repo_root: Path) -> None:
        """If state_ref is set but the ref does not exist, start_run errors."""
        import subprocess as _subp

        _subp.run(["git", "init", str(repo_root)], check=True, capture_output=True)
        _subp.run(
            ["git", "-C", str(repo_root), "config", "user.email", "test@test.com"],
            check=True,
            capture_output=True,
        )
        _subp.run(
            ["git", "-C", str(repo_root), "config", "user.name", "Test"],
            check=True,
            capture_output=True,
        )

        mgr = RunManager(repo_root)
        task_file = repo_root / "task.md"
        with pytest.raises(ValueError, match="state ref 'orca-eval-state/ghost' not found"):
            await mgr.start_run(task_file, state_ref="orca-eval-state/ghost")


@pytest.fixture()
def external_flow(tmp_path: Path) -> tuple[Path, Path]:
    """Create an external flow directory with config and prompts, separate from repo_root."""
    flow_dir = tmp_path / "external-flows"
    flow_dir.mkdir()
    config = flow_dir / "develop.yml"
    config.write_text(SIMPLE_CONFIG_YAML)
    prompts = flow_dir / "prompts"
    prompts.mkdir()
    (prompts / "todo.md").write_text("External: {{ issue.fields.title }}")
    (prompts / "impl.md").write_text("External impl: {{ issue.fields.title }}")

    repo = tmp_path / "repo"
    repo.mkdir()
    task = repo / "task.md"
    task.write_text("title: Test Task\ndescription: A test task")
    return repo, config


class TestExternalFlow:
    @pytest.mark.asyncio()
    async def test_start_run_with_external_flow_path(self, external_flow: tuple[Path, Path]) -> None:
        """start_run with a path-like workflow stores config_source.json."""
        repo, config_path = external_flow
        mgr = RunManager(repo)

        mock_worker = MockWorker(
            outcomes={
                "todo": WorkerSuccess(result={"outcome": "start"}),
                "implementing": WorkerSuccess(result={"outcome": "complete"}),
            }
        )

        with (
            patch("orca.daemon.manager.resolve_branch", return_value="main"),
            patch("orca.daemon.manager.CliAgentWorker", return_value=mock_worker),
        ):
            run_id = await mgr.start_run(
                task_file=repo / "task.md",
                workflow=str(config_path),
            )

        run_info = mgr.get_run(run_id)
        assert run_info is not None
        # effective_workflow should be derived from "develop.yml" -> "develop"
        assert run_info.workflow == "develop"
        assert run_id == "main:develop"

        # Verify config_source.json was written
        run_dir = repo / ".orca-state" / "runs" / "main" / "develop"
        source_file = run_dir / "config_source.json"
        assert source_file.exists()
        source = json.loads(source_file.read_text())
        assert source["config_path"] == str(config_path.resolve())

        await mgr.stop_all()

    @pytest.mark.asyncio()
    async def test_external_flow_name_without_orca_prefix(self, tmp_path: Path) -> None:
        """External flow file without orca. prefix uses full stem as workflow name."""
        flow_dir = tmp_path / "flows"
        flow_dir.mkdir()
        config = flow_dir / "my-flow.yml"
        config.write_text(SIMPLE_CONFIG_YAML)
        prompts = flow_dir / "prompts"
        prompts.mkdir()
        (prompts / "todo.md").write_text("{{ issue.fields.title }}")
        (prompts / "impl.md").write_text("{{ issue.fields.title }}")

        repo = tmp_path / "repo"
        repo.mkdir()
        task = repo / "task.md"
        task.write_text("title: Test\ndescription: Test")

        mgr = RunManager(repo)
        mock_worker = MockWorker(
            outcomes={
                "todo": WorkerSuccess(result={"outcome": "start"}),
                "implementing": WorkerSuccess(result={"outcome": "complete"}),
            }
        )

        with (
            patch("orca.daemon.manager.resolve_branch", return_value="main"),
            patch("orca.daemon.manager.CliAgentWorker", return_value=mock_worker),
        ):
            run_id = await mgr.start_run(
                task_file=task,
                workflow=str(config),
            )

        assert run_id == "main:my-flow"
        run_info = mgr.get_run(run_id)
        assert run_info is not None
        assert run_info.workflow == "my-flow"

        await mgr.stop_all()

    @pytest.mark.asyncio()
    async def test_drop_run_cleans_config_source(self, external_flow: tuple[Path, Path]) -> None:
        """drop_run should remove config_source.json along with other state files."""
        repo, config_path = external_flow
        mgr = RunManager(repo)

        mock_worker = MockWorker(
            outcomes={
                "todo": WorkerSuccess(result={"outcome": "start"}),
                "implementing": WorkerSuccess(result={"outcome": "complete"}),
            }
        )

        with (
            patch("orca.daemon.manager.resolve_branch", return_value="main"),
            patch("orca.daemon.manager.CliAgentWorker", return_value=mock_worker),
        ):
            run_id = await mgr.start_run(
                task_file=repo / "task.md",
                workflow=str(config_path),
            )

        run_dir = repo / ".orca-state" / "runs" / "main" / "develop"
        assert (run_dir / "config_source.json").exists()

        await mgr.drop_run(run_id)
        assert not (run_dir / "config_source.json").exists()


class TestDeriveTestName:
    def test_matches_tests_layout(self) -> None:
        assert _derive_eval_name(Path("/repo/.orca/evals/foo/eval-flow.yml")) == "foo"

    def test_kebab_case_name(self) -> None:
        assert _derive_eval_name(Path("/repo/.orca/evals/scoping-decomposes/eval-flow.yml")) == "scoping-decomposes"

    def test_returns_none_for_regular_workflow(self) -> None:
        assert _derive_eval_name(Path("/repo/.orca/develop.yml")) is None

    def test_returns_none_for_unexpected_filename(self) -> None:
        assert _derive_eval_name(Path("/repo/.orca/evals/foo/orca.yml")) is None

    def test_returns_none_for_path_outside_tests_dir(self) -> None:
        assert _derive_eval_name(Path("/repo/.orca/flows/foo/eval-flow.yml")) is None

    def test_returns_none_for_short_path(self) -> None:
        assert _derive_eval_name(Path("eval-flow.yml")) is None


class TestScanInterruptedRuns:
    def test_scan_interrupted_external_flow(self, tmp_path: Path) -> None:
        """scan_interrupted_runs picks up runs that used an external flow file."""
        # Set up external flow
        flow_dir = tmp_path / "external-flows"
        flow_dir.mkdir()
        config = flow_dir / "orca.yml"
        config.write_text(SIMPLE_CONFIG_YAML)

        repo = tmp_path / "repo"
        repo.mkdir()

        # Set up a persisted run with config_source.json
        run_dir = repo / ".orca-state" / "runs" / "feat-x" / "default"
        run_dir.mkdir(parents=True)

        (run_dir / "config_source.json").write_text(json.dumps({"config_path": str(config)}))

        # Write a minimal non-terminal state
        from orca.engine.config import parse_config
        from orca.engine.reducer import reduce
        from orca.engine.types import CreateEvent, State

        sm_config = parse_config(config.read_text())
        state = State(issues={}, worker_queues={})
        event = CreateEvent(issue_id="issue-1", fields={"title": "Test"}, timestamp="2026-01-01T00:00:00Z")
        state, _ = reduce(sm_config, state, event, lambda: "id-1", lambda: "2026-01-01T00:00:00Z")
        (run_dir / "state.json").write_text(json.dumps(state.to_dict()))

        mgr = RunManager(repo)
        mgr.scan_interrupted_runs()

        runs = mgr.list_runs()
        assert len(runs) == 1
        assert runs[0].run_id == "feat-x:default"
        assert runs[0].status == RunStatus.INTERRUPTED


class TestCollectWaitingIssues:
    """`_collect_waiting_issues` walks each issue's event_log to find ones
    currently parked at a `worker_waiting` event (gh#14)."""

    @staticmethod
    def _make_issue(events: list[tuple[str, dict[str, Any]]], state: str = "doing") -> Any:
        from orca.engine.types import EventLogEntry, Issue

        return Issue(
            type="default",
            fields={},
            state=state,
            worker_active=False,
            decomposed_from=None,
            depends_on=[],
            event_log=[
                EventLogEntry(timestamp=f"2026-05-22T00:00:{i:02d}+00:00", type=t, data=d)
                for i, (t, d) in enumerate(events)
            ],
        )

    @staticmethod
    def _make_state(issues: dict[str, Any]) -> Any:
        from orca.engine.types import State

        return State(issues=issues, worker_queues={})

    def test_includes_issue_with_unresolved_worker_waiting(self) -> None:
        from orca.daemon.manager import _collect_waiting_issues

        issue = self._make_issue([("worker_waiting", {"reason": "needs PR approval"})])
        state = self._make_state({"issue-1": issue})

        out = _collect_waiting_issues(state)

        assert out == [{"issue_id": "issue-1", "state": "doing", "reason": "needs PR approval"}]

    def test_excludes_issue_already_resumed(self) -> None:
        from orca.daemon.manager import _collect_waiting_issues

        issue = self._make_issue(
            [
                ("worker_waiting", {"reason": "needs PR"}),
                ("worker_resumed", {"message": "done"}),
            ]
        )
        state = self._make_state({"issue-1": issue})

        out = _collect_waiting_issues(state)

        assert out == []

    def test_uses_most_recent_waiting_when_multiple(self) -> None:
        from orca.daemon.manager import _collect_waiting_issues

        issue = self._make_issue(
            [
                ("worker_waiting", {"reason": "first pause"}),
                ("worker_resumed", {"message": "ok"}),
                ("worker_waiting", {"reason": "second pause"}),
            ]
        )
        state = self._make_state({"issue-1": issue})

        out = _collect_waiting_issues(state)

        assert out == [{"issue_id": "issue-1", "state": "doing", "reason": "second pause"}]

    def test_returns_empty_when_no_issues_waiting(self) -> None:
        from orca.daemon.manager import _collect_waiting_issues

        issue = self._make_issue([("worker_result", {"outcome": "done"})])
        state = self._make_state({"issue-1": issue})

        assert _collect_waiting_issues(state) == []

    def test_aggregates_across_multiple_issues(self) -> None:
        from orca.daemon.manager import _collect_waiting_issues

        a = self._make_issue([("worker_waiting", {"reason": "A blocked"})], state="state-a")
        b = self._make_issue([("worker_result", {"outcome": "done"})], state="state-b")
        c = self._make_issue([("worker_waiting", {"reason": "C blocked"})], state="state-c")
        state = self._make_state({"a": a, "b": b, "c": c})

        out = _collect_waiting_issues(state)
        # Sort to make assertion order-independent.
        out_sorted = sorted(out, key=lambda d: d["issue_id"])

        assert out_sorted == [
            {"issue_id": "a", "state": "state-a", "reason": "A blocked"},
            {"issue_id": "c", "state": "state-c", "reason": "C blocked"},
        ]
