from __future__ import annotations

import asyncio
import contextlib
import enum
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from orca.engine.config import parse_config
from orca.engine.reducer import reduce
from orca.engine.types import CreateEvent, Effect, State, StateMachineConfig
from orca.orchestrator.branches import BranchMap
from orca.orchestrator.log import setup_logging
from orca.orchestrator.orchestrator import Orchestrator
from orca.orchestrator.persistence import Persistence
from orca.orchestrator.runner import (
    _find_root_issue,
    _recover_effects,
    parse_task_file,
    resolve_branch,
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
    task: asyncio.Task[None] | None = field(default=None, repr=False)

    def to_summary(self) -> dict[str, Any]:
        """JSON-serializable summary."""
        terminal_count = 0
        if self.orchestrator is not None and self.config is not None:
            for issue in self.orchestrator.state.issues.values():
                type_def = self.config.types.get(issue.type)
                if type_def is not None:
                    state_def = type_def.states.get(issue.state)
                    if state_def is not None and state_def.terminal:
                        terminal_count += 1
        # Update issue_count from live state if available
        issue_count = self.issue_count
        if self.orchestrator is not None:
            issue_count = len(self.orchestrator.state.issues)
        return {
            "run_id": self.run_id,
            "branch": self.branch,
            "workflow": self.workflow,
            "status": self.status.value,
            "issue_count": issue_count,
            "terminal_count": terminal_count,
            "created_at": self.created_at,
        }


class RunManager:
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
        """Start a new orchestrator run. Returns run_id.

        Resolves config, sets up persistence/branches/worktrees/orchestrator,
        then launches orchestrator.run() as an asyncio task.
        """
        # Resolve config
        effective_workflow = workflow or "default"
        config_path = resolve_config_path(self.repo_root, workflow)
        config = parse_config(config_path.read_text())
        if max_hops is not None:
            object.__setattr__(config, "max_hops", max_hops)
        if max_retries is not None:
            object.__setattr__(config, "max_worker_retries", max_retries)

        # Resolve branch
        if branch is None:
            branch = resolve_branch()

        run_id = self.make_run_id(branch, effective_workflow)

        # Check for duplicate
        existing = self._runs.get(run_id)
        if existing is not None and existing.status == RunStatus.RUNNING:
            msg = f"Run '{run_id}' is already running"
            raise ValueError(msg)

        # Set up run directory and persistence
        run_dir = self.repo_root / ".orca" / "runs" / branch / effective_workflow
        persistence = Persistence(self.repo_root, branch, effective_workflow)
        branches = BranchMap(self.repo_root, branch, effective_workflow)
        worktree_mgr = WorktreeManager(self.repo_root, branch)

        log_path = run_dir / "orca.log.jsonl"
        setup_logging(log_path)

        # Read task file
        fields = parse_task_file(task_file)

        initial_effects: list[Effect] = []

        if persistence.exists():
            # Resume: load state and branches, recover effects
            state = persistence.load()
            if state is None:
                msg = "Failed to load state from persistence"
                raise RuntimeError(msg)
            branches.load()

            # Reset hop_count and failure_count on non-terminal issues
            for issue in state.issues.values():
                type_def = config.types.get(issue.type)
                if type_def and issue.state in type_def.states and type_def.states[issue.state].terminal:
                    continue
                issue.hop_count = 0
                issue.failure_count = 0

            # Clean up sessions from previous run
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
            # Fresh start
            root_issue_id = _generate_id()
            state = State(issues={}, worker_queues={})
            create_event = CreateEvent(
                issue_id=root_issue_id,
                fields=fields,
                timestamp=_now(),
            )
            state, initial_effects = reduce(config, state, create_event, _generate_id, _now)

            branches.set(root_issue_id, branch)
            branches.save()
            persistence.save(state)

        # Find root issue ID
        root_issue_id = _find_root_issue(state)

        # Set up workers and orchestrator
        workers = {name: CliAgentWorker(self.repo_root, kc) for name, kc in KIND_REGISTRY.items()}

        session_sync = SessionSync(run_dir=run_dir)

        orchestrator = Orchestrator(
            config=config,
            state=state,
            root_branch=branch,
            persistence=persistence,
            branches=branches,
            workers=workers,
            generate_id=_generate_id,
            now=_now,
            worktree_mgr=worktree_mgr,
            repo_root=self.repo_root,
            session_sync=session_sync,
        )

        # Create RunInfo and launch
        now_str = _now()
        run_info = RunInfo(
            run_id=run_id,
            branch=branch,
            workflow=effective_workflow,
            status=RunStatus.RUNNING,
            issue_count=len(state.issues),
            created_at=now_str,
            config=config,
            orchestrator=orchestrator,
        )

        async def _run_wrapper() -> None:
            try:
                await orchestrator.run(root_issue_id, initial_effects)
                run_info.status = RunStatus.COMPLETED
            except asyncio.CancelledError:
                run_info.status = RunStatus.STOPPED
                raise
            except Exception:
                run_info.status = RunStatus.FAILED
                logger.error(
                    "Run %s failed",
                    run_id,
                    exc_info=True,
                    extra={"event": "run_failed", "run_id": run_id},
                )

        task: asyncio.Task[None] = asyncio.create_task(_run_wrapper())
        run_info.task = task
        self._runs[run_id] = run_info

        logger.info(
            "Run %s started",
            run_id,
            extra={"event": "run_started", "run_id": run_id, "branch": branch, "workflow": effective_workflow},
        )

        return run_id

    async def stop_run(self, run_id: str) -> None:
        """Cancel the run's asyncio task, set status STOPPED."""
        run_info = self._runs.get(run_id)
        if run_info is None:
            msg = f"Run '{run_id}' not found"
            raise ValueError(msg)

        if run_info.task is not None and not run_info.task.done():
            run_info.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await run_info.task

        run_info.status = RunStatus.STOPPED

    async def stop_all(self) -> None:
        """Stop all running orchestrators (daemon shutdown)."""
        tasks: list[asyncio.Task[None]] = []
        for run_info in self._runs.values():
            if run_info.task is not None and not run_info.task.done():
                run_info.task.cancel()
                tasks.append(run_info.task)

        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task

        for run_info in self._runs.values():
            if run_info.status == RunStatus.RUNNING:
                run_info.status = RunStatus.STOPPED

    def get_run_state(self, run_id: str) -> dict[str, Any] | None:
        """Get the current state of a run as a JSON-serializable dict."""
        run_info = self._runs.get(run_id)
        if run_info is None or run_info.orchestrator is None:
            return None
        return run_info.orchestrator.state.to_dict()

    def get_issue(self, run_id: str, issue_id: str) -> dict[str, Any] | None:
        """Get a specific issue from a run."""
        run_info = self._runs.get(run_id)
        if run_info is None or run_info.orchestrator is None:
            return None
        issue = run_info.orchestrator.state.issues.get(issue_id)
        if issue is None:
            return None
        return issue.to_dict()

    def get_worker_log(self, run_id: str, tracking_id: str, tail: int = 100) -> str:
        """Get worker log content for a tracking ID in the given run."""
        run_info = self._runs.get(run_id)
        if run_info is None or run_info.orchestrator is None:
            return ""
        return run_info.orchestrator.get_session_log(tracking_id, tail)

    def get_insights(self, run_id: str) -> str:
        """Get insights log content for the given run."""
        run_info = self._runs.get(run_id)
        if run_info is None or run_info.orchestrator is None:
            return ""
        tid = run_info.orchestrator.insights_tracking_id
        if not tid:
            return ""
        return run_info.orchestrator.get_session_log(tid)

    def retry_issue(self, run_id: str, issue_id: str) -> None:
        """Write retry signal file (same as TUI mechanism)."""
        run_info = self._runs.get(run_id)
        if run_info is None:
            msg = f"Run '{run_id}' not found"
            raise ValueError(msg)

        retry_dir = self.repo_root / ".orca" / "runs" / run_info.branch / run_info.workflow / "retry"
        retry_dir.mkdir(parents=True, exist_ok=True)
        (retry_dir / issue_id).touch()

    def scan_interrupted_runs(self) -> None:
        """Scan .orca/runs/ for non-terminal runs from previous session.

        Mark as INTERRUPTED (don't auto-resume).
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

                branch = branch_dir.name
                workflow_name = workflow_dir.name
                run_id = self.make_run_id(branch, workflow_name)

                # Skip runs we're already tracking
                if run_id in self._runs:
                    continue

                # Try to load config to check if terminal
                try:
                    config_path = resolve_config_path(
                        self.repo_root, workflow_name if workflow_name != "default" else None
                    )
                    config = parse_config(config_path.read_text())
                except (SystemExit, Exception):
                    continue

                state = Persistence(self.repo_root, branch, workflow_name).load()
                if state is None:
                    continue

                # Check if the root issue is terminal
                all_terminal = True
                for issue in state.issues.values():
                    type_def = config.types.get(issue.type)
                    if type_def is None:
                        continue
                    state_def = type_def.states.get(issue.state)
                    if state_def is None or not state_def.terminal:
                        all_terminal = False
                        break

                if all_terminal:
                    continue  # Run was completed, skip

                self._runs[run_id] = RunInfo(
                    run_id=run_id,
                    branch=branch,
                    workflow=workflow_name,
                    status=RunStatus.INTERRUPTED,
                    issue_count=len(state.issues),
                    created_at=_now(),
                    config=config,
                )
