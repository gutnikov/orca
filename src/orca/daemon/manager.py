from __future__ import annotations

import asyncio
import contextlib
import enum
import json as _json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from orca.engine.config import parse_config
from orca.engine.reducer import reduce
from orca.engine.types import CreateEvent, Effect, State, StateMachineConfig, WorkerFailedEvent
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


def _collect_waiting_issues(state: Any) -> list[dict[str, Any]]:
    """Return per-issue `worker_waiting` records that have no subsequent
    `worker_resumed` — i.e. issues currently parked awaiting human input.

    Each record: `{issue_id, state, reason}`. Used by `RunInfo.to_summary`
    to surface stuck runs in `orca runs` without forcing the user to
    `tmux capture-pane` for the worker's actual blocker (gh#14).
    """
    result: list[dict[str, Any]] = []
    for issue_id, issue in state.issues.items():
        for entry in reversed(issue.event_log):
            if entry.type == "worker_resumed":
                break  # Most recent waiting was already resumed.
            if entry.type == "worker_waiting":
                result.append(
                    {
                        "issue_id": issue_id,
                        "state": issue.state,
                        "reason": entry.data.get("reason", ""),
                    }
                )
                break
    return result


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
    insights: bool = False

    def to_summary(self) -> dict[str, Any]:
        """JSON-serializable summary."""
        terminal_count = 0
        waiting_issues: list[dict[str, Any]] = []
        if self.orchestrator is not None:
            terminal_count = sum(1 for issue in self.orchestrator.state.issues.values() if issue.state == "done")
            waiting_issues = _collect_waiting_issues(self.orchestrator.state)
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
            "waiting_issues": waiting_issues,
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
        run_id: str | None = None,
        max_hops: int | None = None,
        max_retries: int | None = None,
        *,
        insights: bool = False,
    ) -> str:
        """Start a new orchestrator run. Returns run_id.

        Resolves config, sets up persistence/branches/worktrees/orchestrator,
        then launches orchestrator.run() as an asyncio task.
        """
        # Resolve config
        config_path = resolve_config_path(self.repo_root, workflow)
        config = parse_config(config_path.read_text())
        flow_root = config_path.parent

        # Derive effective_workflow name (short name for run directory)
        if workflow and ("/" in workflow or workflow.endswith(".yml")):
            # External flow — derive name from filename
            effective_workflow = config_path.stem
        else:
            effective_workflow = workflow or "default"
        if max_hops is not None:
            object.__setattr__(config, "max_hops", max_hops)
        if max_retries is not None:
            object.__setattr__(config, "max_worker_retries", max_retries)

        if branch is None:
            branch = resolve_branch()

        run_id = run_id or self.make_run_id(branch, effective_workflow)

        # Check for duplicate
        existing = self._runs.get(run_id)
        if existing is not None and existing.status == RunStatus.RUNNING:
            msg = f"Run '{run_id}' is already running"
            raise ValueError(msg)

        run_dir = self.repo_root / ".orca-state" / "runs" / branch / effective_workflow
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "config_source.json").write_text(_json.dumps({"config_path": str(config_path.resolve())}))
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

            # Reset hop_count on non-terminal issues (failure_count is handled by _recover_effects)
            for issue in state.issues.values():
                if issue.state == "done":
                    continue
                issue.hop_count = 0

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
            # Fresh start — clear stale session manifest
            (run_dir / "sessions.json").unlink(missing_ok=True)
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
            flow_root=flow_root,
            session_sync=session_sync,
            insights_enabled=insights,
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
            insights=insights,
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

    def _restart_run(self, run_info: RunInfo) -> None:
        """Restart the orchestrator loop for a finished run (e.g. after retry)."""
        orchestrator = run_info.orchestrator
        if orchestrator is None:
            return
        root_issue_id = _find_root_issue(orchestrator.state)
        run_info.status = RunStatus.RUNNING

        async def _run_wrapper() -> None:
            try:
                await orchestrator.run(root_issue_id, [])
                run_info.status = RunStatus.COMPLETED
            except asyncio.CancelledError:
                run_info.status = RunStatus.STOPPED
                raise
            except Exception:
                run_info.status = RunStatus.FAILED
                logger.error(
                    "Run %s failed (restart)",
                    run_info.run_id,
                    exc_info=True,
                    extra={"event": "run_failed", "run_id": run_info.run_id},
                )

        run_info.task = asyncio.create_task(_run_wrapper())
        logger.info(
            "Run %s restarted via retry",
            run_info.run_id,
            extra={"event": "run_restarted", "run_id": run_info.run_id},
        )

    def _mark_stopped(self, run_info: RunInfo) -> None:
        """Mark orphan sessions as failed and reduce failure events for active workers."""
        run_dir = self.repo_root / ".orca-state" / "runs" / run_info.branch / run_info.workflow
        manifest = SessionManifest(run_dir)
        manifest.mark_orphans_completed(_now(), failed=True)

        if run_info.orchestrator is not None and run_info.config is not None:
            state = run_info.orchestrator.state
            config = run_info.config
            for issue_id, issue in list(state.issues.items()):
                if issue.worker_active:
                    event = WorkerFailedEvent(
                        issue_id=issue_id,
                        error="run stopped",
                        timestamp=_now(),
                    )
                    state, _ = reduce(config, state, event, _generate_id, _now)
            # Force worker_active=False — the reducer may leave it True for auto-retry,
            # but no dispatch will happen since the run is stopped
            for issue in state.issues.values():
                if issue.worker_active:
                    issue.worker_active = False
            run_info.orchestrator._state = state
            run_info.orchestrator.persistence.save(state)

    async def stop_run(self, run_id: str) -> None:
        """Cancel the run's asyncio task, kill workers, set status STOPPED."""
        run_info = self._runs.get(run_id)
        if run_info is None:
            msg = f"Run '{run_id}' not found"
            raise ValueError(msg)

        # Stop the orchestrator's workers/tmux sessions first
        if run_info.orchestrator is not None:
            await run_info.orchestrator.stop()

        if run_info.task is not None and not run_info.task.done():
            run_info.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await run_info.task

        self._mark_stopped(run_info)
        run_info.status = RunStatus.STOPPED

    async def drop_run(self, run_id: str) -> None:
        """Stop (if running), clean up run state, and remove from tracking."""
        run_info = self._runs.get(run_id)
        if run_info is None:
            msg = f"Run '{run_id}' not found"
            raise ValueError(msg)

        if run_info.orchestrator is not None:
            await run_info.orchestrator.stop()

        if run_info.task is not None and not run_info.task.done():
            run_info.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await run_info.task

        # Clean up persisted state so a fresh run doesn't inherit old data
        run_dir = self.repo_root / ".orca-state" / "runs" / run_info.branch / run_info.workflow
        for name in ("state.json", "sessions.json", "branches.json", "config_source.json"):
            (run_dir / name).unlink(missing_ok=True)

        del self._runs[run_id]

    async def resume_run(self, run_id: str) -> None:
        """Resume a stopped, failed, or interrupted run."""
        run_info = self._runs.get(run_id)
        if run_info is None:
            msg = f"Run '{run_id}' not found"
            raise ValueError(msg)
        if run_info.status == RunStatus.RUNNING:
            msg = f"Run '{run_id}' is already running"
            raise ValueError(msg)

        if run_info.orchestrator is not None:
            self._restart_run(run_info)
            return

        # Rebuild orchestrator from persistence (e.g. interrupted runs)
        branch = run_info.branch
        workflow = run_info.workflow
        config = run_info.config

        # Resolve config path from config_source.json (external flows) or repo root
        run_dir = self.repo_root / ".orca-state" / "runs" / branch / workflow
        source_file = run_dir / "config_source.json"
        if source_file.exists():
            try:
                config_path = Path(_json.loads(source_file.read_text())["config_path"])
            except (KeyError, _json.JSONDecodeError):
                config_path = resolve_config_path(self.repo_root, workflow if workflow != "default" else None)
        else:
            config_path = resolve_config_path(self.repo_root, workflow if workflow != "default" else None)
        flow_root = config_path.parent

        if config is None:
            if not config_path.exists():
                msg = f"External flow file no longer exists: {config_path}"
                raise ValueError(msg)
            config = parse_config(config_path.read_text())
            run_info.config = config

        persistence = Persistence(self.repo_root, branch, workflow)
        if not persistence.exists():
            msg = f"Run '{run_id}' has no persisted state to resume"
            raise ValueError(msg)

        state = persistence.load()
        if state is None:
            msg = f"Run '{run_id}': failed to load persisted state"
            raise ValueError(msg)

        branches = BranchMap(self.repo_root, branch, workflow)
        branches.load()
        worktree_mgr = WorktreeManager(self.repo_root, branch)

        log_path = run_dir / "orca.log.jsonl"
        setup_logging(log_path)

        # Reset hop_count on non-terminal issues
        for issue in state.issues.values():
            if issue.state == "done":
                continue
            issue.hop_count = 0

        # Clean up sessions from previous run
        manifest = SessionManifest(run_dir)
        manifest.mark_orphans_completed(_now())

        recovered_events, recovered_effects = _recover_effects(
            config, state, branches, worktree_mgr, run_dir, _generate_id, _now
        )
        initial_effects: list[Effect] = []
        for event in recovered_events:
            state, new_effects = reduce(config, state, event, _generate_id, _now)
            initial_effects.extend(new_effects)
        initial_effects.extend(recovered_effects)

        root_issue_id = _find_root_issue(state)

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
            flow_root=flow_root,
            session_sync=session_sync,
            insights_enabled=run_info.insights,
        )
        run_info.orchestrator = orchestrator
        run_info.issue_count = len(state.issues)
        run_info.status = RunStatus.RUNNING

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
                    "Run %s failed (resume)",
                    run_id,
                    exc_info=True,
                    extra={"event": "run_failed", "run_id": run_id},
                )

        run_info.task = asyncio.create_task(_run_wrapper())
        logger.info(
            "Run %s resumed",
            run_id,
            extra={"event": "run_resumed", "run_id": run_id, "branch": branch, "workflow": workflow},
        )

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
        if run_info is None:
            return None
        if run_info.orchestrator is not None:
            return run_info.orchestrator.state.to_dict()
        # Fall back to persisted state on disk (e.g. interrupted runs)
        persistence = Persistence(self.repo_root, run_info.branch, run_info.workflow)
        state = persistence.load()
        if state is not None:
            return state.to_dict()
        return None

    def get_sessions(self, run_id: str) -> list[dict[str, Any]]:
        """Get session manifest entries for a run."""
        run_info = self._runs.get(run_id)
        if run_info is None:
            return []
        run_dir = self.repo_root / ".orca-state" / "runs" / run_info.branch / run_info.workflow
        manifest = SessionManifest(run_dir)
        return manifest.read()

    def get_issue(self, run_id: str, issue_id: str) -> dict[str, Any] | None:
        """Get a specific issue from a run."""
        run_info = self._runs.get(run_id)
        if run_info is None:
            return None
        state = None
        if run_info.orchestrator is not None:
            state = run_info.orchestrator.state
        else:
            persistence = Persistence(self.repo_root, run_info.branch, run_info.workflow)
            state = persistence.load()
        if state is None:
            return None
        issue = state.issues.get(issue_id)
        if issue is None:
            return None
        return issue.to_dict()

    def get_worker_log(self, run_id: str, issue_id: str, tail: int = 100) -> str:
        """Get worker log content for the latest session of the given issue."""
        run_info = self._runs.get(run_id)
        if run_info is None or run_info.orchestrator is None:
            return ""
        return run_info.orchestrator.get_session_log_by_issue(issue_id, tail)

    def get_all_worker_logs(self, run_id: str, tail: int = 100) -> str:
        """Get worker logs for all issues in a run."""
        run_info = self._runs.get(run_id)
        if run_info is None:
            return ""
        state = None
        if run_info.orchestrator is not None:
            state = run_info.orchestrator.state
        else:
            persistence = Persistence(self.repo_root, run_info.branch, run_info.workflow)
            state = persistence.load()
        if state is None:
            return ""
        parts: list[str] = []
        for issue_id, issue in state.issues.items():
            header = f"=== {issue_id[:12]} [{issue.state}] ==="
            if run_info.orchestrator is not None:
                log = run_info.orchestrator.get_session_log_by_issue(issue_id, tail)
            else:
                log = ""
            if log:
                parts.append(f"{header}\n{log}")
            else:
                parts.append(f"{header}\n(no log)")
        return "\n\n".join(parts)

    def get_insights(self, run_id: str) -> str:
        """Get insights log content for the given run."""
        run_info = self._runs.get(run_id)
        if run_info is None or run_info.orchestrator is None:
            return ""
        tid = run_info.orchestrator.insights_tracking_id
        if not tid:
            return ""
        return run_info.orchestrator.get_session_log(tid)

    def unblock_worker(self, run_id: str, issue_id: str, message: str) -> None:
        """Unblock a blocked worker in a run."""
        run_info = self._runs.get(run_id)
        if run_info is None:
            msg = f"Run '{run_id}' not found"
            raise ValueError(msg)
        if run_info.orchestrator is None:
            msg = f"Run '{run_id}' has no orchestrator"
            raise ValueError(msg)
        if not run_info.orchestrator.unblock_worker(issue_id, message):
            msg = f"Issue '{issue_id}' is not waiting in run '{run_id}'"
            raise ValueError(msg)

    def retry_issue(self, run_id: str, issue_id: str) -> None:
        """Retry a failed issue. If the orchestrator loop has finished, restart it."""
        run_info = self._runs.get(run_id)
        if run_info is None:
            msg = f"Run '{run_id}' not found"
            raise ValueError(msg)

        run_dir = self.repo_root / ".orca-state" / "runs" / run_info.branch / run_info.workflow

        # Write retry signal file
        retry_dir = run_dir / "retry"
        retry_dir.mkdir(parents=True, exist_ok=True)
        (retry_dir / issue_id).touch()

        # If the run has finished (not RUNNING), restart the orchestrator loop
        if run_info.status != RunStatus.RUNNING and run_info.orchestrator is not None:
            self._restart_run(run_info)

    def scan_interrupted_runs(self) -> None:
        """Scan .orca-state/runs/ for non-terminal runs from previous session.

        Mark as INTERRUPTED (don't auto-resume).
        """
        runs_dir = self.repo_root / ".orca-state" / "runs"
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

                # Try to load config — check config_source.json first (external flows)
                try:
                    source_file = workflow_dir / "config_source.json"
                    if source_file.exists():
                        config_path = Path(_json.loads(source_file.read_text())["config_path"])
                    else:
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
                all_terminal = all(issue.state == "done" for issue in state.issues.values())

                if all_terminal:
                    continue  # Run was completed, skip

                # Mark orphan sessions as completed+interrupted so TUI shows them distinctly
                manifest = SessionManifest(workflow_dir)
                manifest.mark_orphans_completed(_now(), interrupted=True)

                # Treat in-flight workers as failures so retry machinery applies
                persistence = Persistence(self.repo_root, branch, workflow_name)
                for issue_id, issue in state.issues.items():
                    if issue.worker_active:
                        event = WorkerFailedEvent(
                            issue_id=issue_id,
                            error="daemon interrupted",
                            timestamp=_now(),
                        )
                        state, _ = reduce(config, state, event, _generate_id, _now)
                for issue in state.issues.values():
                    if issue.worker_active:
                        issue.worker_active = False
                persistence.save(state)

                self._runs[run_id] = RunInfo(
                    run_id=run_id,
                    branch=branch,
                    workflow=workflow_name,
                    status=RunStatus.INTERRUPTED,
                    issue_count=len(state.issues),
                    created_at=_now(),
                    config=config,
                )
