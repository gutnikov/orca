from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from orca.daemon.manager import RunManager, RunStatus, _pair_debug_attempts
from orca.engine.types import DispatchWorkerEffect, EventLogEntry
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
        effort: str | None = None,
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


def _entry(t: str, type_: str, data: dict) -> EventLogEntry:
    return EventLogEntry(timestamp=t, type=type_, data=data)


class TestPairDebugAttempts:
    def test_empty_log(self) -> None:
        assert _pair_debug_attempts([], drop_pending_tail=False) == []

    def test_no_debug_events(self) -> None:
        log = [
            _entry("t1", "created", {"state": "scoping"}),
            _entry("t2", "advanced", {"from": "scoping", "to": "planning"}),
            _entry("t3", "worker_result", {}),
        ]
        assert _pair_debug_attempts(log, drop_pending_tail=False) == []

    def test_single_pause_and_decision(self) -> None:
        log = [
            _entry("t1", "created", {"state": "planning"}),
            _entry("t2", "debug_review_required", {"snapshot": {}}),
            _entry("t3", "debug_decision", {"action": "accept", "comments": []}),
        ]
        out = _pair_debug_attempts(log, drop_pending_tail=False)
        assert out == [
            {
                "attempt": 0,
                "state": "planning",
                "state_local_index": 1,
                "paused_at": "t2",
                "decision": "accept",
                "decided_at": "t3",
            }
        ]

    def test_modify_restart_cycle_two_attempts_same_state(self) -> None:
        log = [
            _entry("t1", "created", {"state": "planning"}),
            _entry("t2", "debug_review_required", {"snapshot": {}}),
            _entry("t3", "debug_decision", {"action": "modify_restart", "comments": []}),
            _entry("t4", "debug_review_required", {"snapshot": {}}),
            _entry("t5", "debug_decision", {"action": "accept", "comments": []}),
        ]
        out = _pair_debug_attempts(log, drop_pending_tail=False)
        assert [a["attempt"] for a in out] == [0, 1]
        assert all(a["state"] == "planning" for a in out)
        assert [a["state_local_index"] for a in out] == [1, 2]
        assert [a["decision"] for a in out] == ["modify_restart", "accept"]

    def test_state_changes_between_attempts(self) -> None:
        log = [
            _entry("t1", "created", {"state": "planning"}),
            _entry("t2", "debug_review_required", {"snapshot": {}}),
            _entry("t3", "debug_decision", {"action": "accept", "comments": []}),
            _entry("t4", "advanced", {"from": "planning", "to": "implementing"}),
            _entry("t5", "debug_review_required", {"snapshot": {}}),
            _entry("t6", "debug_decision", {"action": "accept", "comments": []}),
        ]
        out = _pair_debug_attempts(log, drop_pending_tail=False)
        assert [a["state"] for a in out] == ["planning", "implementing"]
        # Each state restarts its own local counter
        assert [a["state_local_index"] for a in out] == [1, 1]

    def test_transitioned_event_also_tracks_state(self) -> None:
        log = [
            _entry("t1", "created", {"state": "planning"}),
            _entry("t2", "transitioned", {"from": "planning", "to": "reviewing"}),
            _entry("t3", "debug_review_required", {"snapshot": {}}),
            _entry("t4", "debug_decision", {"action": "stop", "comments": []}),
        ]
        out = _pair_debug_attempts(log, drop_pending_tail=False)
        assert out[0]["state"] == "reviewing"

    def test_undecided_pause_when_drop_pending_false(self) -> None:
        log = [
            _entry("t1", "created", {"state": "planning"}),
            _entry("t2", "debug_review_required", {"snapshot": {}}),
        ]
        out = _pair_debug_attempts(log, drop_pending_tail=False)
        assert out == [
            {
                "attempt": 0,
                "state": "planning",
                "state_local_index": 1,
                "paused_at": "t2",
                "decision": None,
                "decided_at": None,
            }
        ]

    def test_drops_pending_tail_when_flag_true(self) -> None:
        log = [
            _entry("t1", "created", {"state": "planning"}),
            _entry("t2", "debug_review_required", {"snapshot": {}}),
            _entry("t3", "debug_decision", {"action": "accept", "comments": []}),
            _entry("t4", "debug_review_required", {"snapshot": {}}),
        ]
        out = _pair_debug_attempts(log, drop_pending_tail=True)
        assert len(out) == 1
        assert out[0]["decision"] == "accept"
