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
from orca.engine.types import CreateEvent, Effect, EventLogEntry, State, StateMachineConfig, WorkerFailedEvent
from orca.orchestrator.branches import BranchMap
from orca.orchestrator.config_types import parse_orchestrator_config
from orca.orchestrator.log import setup_logging
from orca.orchestrator.orchestrator import Orchestrator
from orca.orchestrator.persistence import Persistence
from orca.orchestrator.runner import (
    _find_root_issue,
    _git_branch_exists,
    _git_create_branch,
    _recover_effects,
    parse_task_file,
    resolve_base_ref,
    resolve_branch,
    resolve_config_path,
)
from orca.orchestrator.session_sync import SessionManifest, SessionSync
from orca.orchestrator.template_persist import rendered_prompt_path
from orca.orchestrator.usage import collect_usage, with_estimated_cost
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


def debug_review_url(browser_port: int | None, run_id: str, issue_id: str) -> str | None:
    """Construct the per-issue debug-review URL. Returns None if browser port
    is unavailable (daemon TCP listener not bound)."""
    if browser_port is None:
        return None
    return f"http://localhost:{browser_port}/debug/{run_id}/{issue_id}"


def _collect_debug_reviews(
    state: Any,
    run_id: str,
    browser_port: int | None,
) -> list[dict[str, Any]]:
    """Return per-issue records for runs currently paused in debug review.

    Each record: `{issue_id, state, url}`. Surfaced in `RunInfo.to_summary`
    AND in compact-run output so any reasonable polling agent can't miss it.
    This is the bullet-proof way to surface debug pauses — relying on agents
    to scan the event_log for `debug_review_required` events has proven
    fragile in practice (the SKILL describes how, but agents narrate the
    result instead of surfacing the URL).
    """
    result: list[dict[str, Any]] = []
    for issue_id, issue in state.issues.items():
        if not getattr(issue, "debug_pending", False):
            continue
        record: dict[str, Any] = {"issue_id": issue_id, "state": issue.state}
        url = debug_review_url(browser_port, run_id, issue_id)
        if url is not None:
            record["url"] = url
        result.append(record)
    return result


def _last_worker_error(state: Any) -> str | None:
    """Return the most recent worker_failed error message across all issues.

    Only reports errors from issues whose last worker event is a failure (not
    followed by a success). Surfaced in run summaries so polling agents/UIs can
    detect startup failures (e.g. invalid model ID) without diving into
    get_worker_log.
    """
    latest: str | None = None
    latest_ts: str = ""
    for issue in state.issues.values():
        for entry in reversed(issue.event_log):
            if entry.type == "worker_result":
                break
            if entry.type == "worker_failed":
                ts = entry.timestamp or ""
                if ts >= latest_ts:
                    latest_ts = ts
                    latest = entry.data.get("error", "unknown error")
                break
    return latest


def _usage_entry_with_metadata(
    entry: dict[str, Any],
    state: State,
    config: StateMachineConfig,
) -> dict[str, Any]:
    result = dict(entry)
    state_name = result.get("state")
    issue_id = result.get("issue_id")
    if not isinstance(state_name, str) or not isinstance(issue_id, str):
        return result
    issue = state.issues.get(issue_id)
    if issue is None:
        return result
    type_def = config.types.get(issue.type)
    if type_def is None:
        return result
    state_def = type_def.states.get(state_name)
    if state_def is None or state_def.worker is None:
        return result

    worker = state_def.worker
    if not isinstance(result.get("worker_kind"), str):
        result["worker_kind"] = worker.kind
    if worker.model and not isinstance(result.get("model"), str):
        result["model"] = worker.model
    if worker.effort and not isinstance(result.get("effort"), str):
        result["effort"] = worker.effort
    return result


def _session_needs_usage_backfill(entry: dict[str, Any]) -> bool:
    usage = entry.get("usage")
    if not isinstance(usage, dict):
        return True
    return "cost_usd" not in usage


def _pair_debug_attempts(
    event_log: list[EventLogEntry],
    *,
    drop_pending_tail: bool,
) -> list[dict[str, Any]]:
    """Walk event_log, pair each debug_review_required with its following
    debug_decision, and infer the state at pause time.

    Returns list of {attempt, state, state_local_index, paused_at, decision,
    decided_at}. state_local_index is the 1-based count of attempts (so far)
    that share this attempt's state.

    State is tracked via "created", "advanced", and "transitioned" events.
    If the log ends with an unmatched debug_review_required and
    drop_pending_tail=True, that trailing attempt is excluded (the caller is
    using the live URL for it).
    """
    current_state: str | None = None
    attempts: list[dict[str, Any]] = []
    pending: dict[str, Any] | None = None
    state_counter: dict[str | None, int] = {}
    attempt_index = 0

    def _finalize_pending(decision: str | None, decided_at: str | None) -> None:
        nonlocal pending
        assert pending is not None
        s = pending["state"]
        state_counter[s] = state_counter.get(s, 0) + 1
        attempts.append(
            {
                **pending,
                "state_local_index": state_counter[s],
                "decision": decision,
                "decided_at": decided_at,
            }
        )
        pending = None

    for entry in event_log:
        if entry.type == "created":
            current_state = entry.data.get("state")
        elif entry.type in ("advanced", "transitioned"):
            current_state = entry.data.get("to")
        elif entry.type == "debug_review_required":
            if pending is not None:
                _finalize_pending(None, None)
            pending = {
                "attempt": attempt_index,
                "state": current_state,
                "paused_at": entry.timestamp,
            }
            attempt_index += 1
        elif entry.type == "debug_decision" and pending is not None:
            _finalize_pending(entry.data.get("action"), entry.timestamp)
    if pending is not None and not drop_pending_tail:
        _finalize_pending(None, None)
    return attempts


def _project_past_comments(
    persisted: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Project the persisted debug_decision.comments shape back into the
    live wire shape (separate inline_comments and comment_threads arrays)
    so the existing renderer can consume it unchanged.

    Synthetic thread IDs and message IDs are stable per-comment but
    meaningless beyond React keys — read-only mode never mutates them.
    """
    inline_comments = [{"id": c["id"], "file": c["file"], "line": c["line"], "body": c["body"]} for c in persisted]
    comment_threads: list[dict[str, Any]] = []
    for c in persisted:
        messages = c.get("thread_messages") or []
        if not messages:
            continue
        comment_threads.append(
            {
                "id": f"thread-{c['id']}",
                "comment_id": c["id"],
                "messages": [
                    {
                        "id": f"{c['id']}-m{i}",
                        "role": m["role"],
                        "body": m["body"],
                        "timestamp": None,
                    }
                    for i, m in enumerate(messages)
                ],
                "agent_last_reviewed_at": None,
            }
        )
    return inline_comments, comment_threads


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
    debug: bool = False

    def to_summary(self, browser_port: int | None = None) -> dict[str, Any]:
        """JSON-serializable summary.

        `browser_port` — when provided, debug-review records will include the
        full URL agents should surface to the user. Pass it from the manager
        (which reads it via lifecycle.read_browser_port).
        """
        terminal_count = 0
        waiting_issues: list[dict[str, Any]] = []
        debug_reviews: list[dict[str, Any]] = []
        last_worker_error: str | None = None
        if self.orchestrator is not None:
            terminal_count = sum(1 for issue in self.orchestrator.state.issues.values() if issue.state == "done")
            waiting_issues = _collect_waiting_issues(self.orchestrator.state)
            debug_reviews = _collect_debug_reviews(self.orchestrator.state, self.run_id, browser_port)
            last_worker_error = _last_worker_error(self.orchestrator.state)
        # Update issue_count from live state if available
        issue_count = self.issue_count
        if self.orchestrator is not None:
            issue_count = len(self.orchestrator.state.issues)
        summary: dict[str, Any] = {
            "run_id": self.run_id,
            "branch": self.branch,
            "workflow": self.workflow,
            "status": self.status.value,
            "issue_count": issue_count,
            "terminal_count": terminal_count,
            "created_at": self.created_at,
            "waiting_issues": waiting_issues,
            "debug_reviews": debug_reviews,
            "debug": self.debug,
        }
        if last_worker_error is not None:
            summary["last_worker_error"] = last_worker_error
        return summary


class RunManager:
    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root
        self._runs: dict[str, RunInfo] = {}
        self._usage_backfill_attempted: set[tuple[str, str]] = set()

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
        debug: bool = False,
        worker_overrides: dict[str, dict[str, str]] | None = None,
    ) -> str:
        """Start a new orchestrator run. Returns run_id.

        Resolves config, sets up persistence/branches/worktrees/orchestrator,
        then launches orchestrator.run() as an asyncio task.
        """
        # Resolve config
        config_path = resolve_config_path(self.repo_root, workflow)
        import yaml as _yaml

        raw_yaml: dict[str, Any] = _yaml.safe_load(config_path.read_text()) or {}
        config = parse_config(config_path.read_text())
        orch_config = parse_orchestrator_config(raw_yaml)
        flow_root = config_path.parent

        # Validate worker overrides: every state name must exist in the
        # workflow's state graph, and any `kind` value must be a registered
        # CLI kind. We don't validate `model`/`effort` strings — the agent
        # CLI itself will reject unknown values at spawn time.
        if worker_overrides:
            known_states: set[str] = set()
            for type_def in config.types.values():
                known_states.update(type_def.states.keys())
            for state_name, fields in worker_overrides.items():
                if state_name not in known_states:
                    msg = f"override references unknown state {state_name!r}"
                    raise ValueError(msg)
                if "kind" in fields and fields["kind"] not in KIND_REGISTRY:
                    msg = (
                        f"override for state {state_name!r}: unknown kind {fields['kind']!r} "
                        f"(known: {sorted(KIND_REGISTRY)})"
                    )
                    raise ValueError(msg)
                for key in fields:
                    if key not in ("kind", "model", "effort"):
                        msg = f"override for state {state_name!r}: unknown field {key!r} (allowed: kind, model, effort)"
                        raise ValueError(msg)

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

            # Ensure a worktree exists when the requested branch differs from
            # the main directory's HEAD — prevents silent wrong-branch execution.
            current_branch = resolve_branch()
            if base is not None:
                # Explicit base: always create worktree (integration branch mode)
                if not await _git_branch_exists(branch, self.repo_root):
                    await _git_create_branch(branch, base, self.repo_root)
                await worktree_mgr.create(
                    issue_id=root_issue_id,
                    branch_name=branch,
                    parent_branch=base,
                )
            elif branch != current_branch:
                # Branch differs from HEAD: isolate via worktree
                if await _git_branch_exists(branch, self.repo_root):
                    await worktree_mgr.create(
                        issue_id=root_issue_id,
                        branch_name=branch,
                        parent_branch=branch,
                    )
                else:
                    base_ref = resolve_base_ref(None, orch_config.base_branch)
                    await _git_create_branch(branch, base_ref, self.repo_root)
                    await worktree_mgr.create(
                        issue_id=root_issue_id,
                        branch_name=branch,
                        parent_branch=base_ref,
                    )

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
            worker_overrides=worker_overrides,
        )
        orchestrator.debug = debug

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
            debug=debug,
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
        """Restart the orchestrator loop for a finished run (e.g. after retry).

        Re-reads the workflow YAML so that mutable fields (model, args,
        inactivity_timeout) reflect any edits made between stop and resume.
        """
        orchestrator = run_info.orchestrator
        if orchestrator is None:
            return

        # Re-read workflow config to pick up YAML edits (e.g. fixed model ID)
        run_dir = self.repo_root / ".orca-state" / "runs" / run_info.branch / run_info.workflow
        source_file = run_dir / "config_source.json"
        try:
            if source_file.exists():
                config_path = Path(_json.loads(source_file.read_text())["config_path"])
            else:
                config_path = resolve_config_path(
                    self.repo_root,
                    run_info.workflow if run_info.workflow != "default" else None,
                )
            if config_path.exists():
                fresh_config = parse_config(config_path.read_text())
                orchestrator._config = fresh_config
                run_info.config = fresh_config
        except Exception:
            logger.debug("Could not refresh config on restart for %s", run_info.run_id, exc_info=True)

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
        state = self._state_for_run(run_info)
        if state is not None:
            return state.to_dict()
        return None

    def _state_for_run(self, run_info: RunInfo) -> State | None:
        """Return live state when available, otherwise load persisted state."""
        if run_info.orchestrator is not None:
            return run_info.orchestrator.state
        persistence = Persistence(self.repo_root, run_info.branch, run_info.workflow)
        return persistence.load()

    def get_sessions(self, run_id: str) -> list[dict[str, Any]]:
        """Get session manifest entries for a run."""
        run_info = self._runs.get(run_id)
        if run_info is None:
            return []
        run_dir = self.repo_root / ".orca-state" / "runs" / run_info.branch / run_info.workflow
        manifest = SessionManifest(run_dir)
        sessions = manifest.read()
        if any(_session_needs_usage_backfill(entry) for entry in sessions):
            self._backfill_session_usage(run_info, run_dir, manifest, sessions)
            sessions = manifest.read()
        return sessions

    def _backfill_session_usage(
        self,
        run_info: RunInfo,
        run_dir: Path,
        manifest: SessionManifest,
        sessions: list[dict[str, Any]],
    ) -> None:
        state = run_info.orchestrator.state if run_info.orchestrator is not None else None
        if state is None:
            state = Persistence(self.repo_root, run_info.branch, run_info.workflow).load()
        if state is None:
            return
        config = run_info.config or self._load_run_config(run_info, run_dir)
        if config is None:
            return

        for entry in sessions:
            session_id = entry.get("session_id")
            if not isinstance(session_id, str):
                continue
            key = (run_info.run_id, session_id)
            if key in self._usage_backfill_attempted:
                continue
            if run_info.status == RunStatus.RUNNING and entry.get("completed_at") is None:
                continue
            self._usage_backfill_attempted.add(key)
            usage_entry = _usage_entry_with_metadata(entry, state, config)
            existing_usage = entry.get("usage")
            if isinstance(existing_usage, dict):
                model = usage_entry.get("model")
                priced = with_estimated_cost(existing_usage, model if isinstance(model, str) else None)
                if priced is not None:
                    manifest.update_usage(session_id, priced)
                continue
            usage = collect_usage(usage_entry)
            if usage is not None:
                manifest.update_usage(session_id, usage)

    def _load_run_config(self, run_info: RunInfo, run_dir: Path) -> StateMachineConfig | None:
        try:
            source_file = run_dir / "config_source.json"
            if source_file.exists():
                config_path = Path(_json.loads(source_file.read_text())["config_path"])
            else:
                config_path = resolve_config_path(
                    self.repo_root,
                    run_info.workflow if run_info.workflow != "default" else None,
                )
            config = parse_config(config_path.read_text())
            run_info.config = config
            return config
        except Exception:
            logger.debug("Could not load config for usage backfill %s", run_info.run_id, exc_info=True)
            return None

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

    def get_worker_log(
        self,
        run_id: str,
        issue_id: str,
        tail: int = 100,
        session_id: str | None = None,
    ) -> str:
        """Return worker log content.

        When *session_id* is provided, returns that session's log directly via
        the orchestrator's tracking-id lookup (used by the web dashboard's
        phase navigation). When *session_id* is None, returns the latest
        session's log for the given issue (existing TUI / CLI behavior).
        """
        run_info = self._runs.get(run_id)
        if run_info is None or run_info.orchestrator is None:
            return ""
        if session_id:
            return run_info.orchestrator.get_session_log(session_id, tail)
        return run_info.orchestrator.get_session_log_by_issue(issue_id, tail)

    def get_session_prompt(self, run_id: str, session_id: str) -> str | None:
        """Return the persisted rendered prompt for a worker session."""
        run_info = self._runs.get(run_id)
        if run_info is None:
            return None
        run_dir = self.repo_root / ".orca-state" / "runs" / run_info.branch / run_info.workflow
        manifest = SessionManifest(run_dir)
        entry = next((item for item in manifest.read() if item.get("session_id") == session_id), None)
        if entry is None:
            return None
        worktree_path = entry.get("worktree_path")
        state = entry.get("state")
        if not isinstance(worktree_path, str) or not isinstance(state, str):
            return None
        path = rendered_prompt_path(Path(worktree_path), state, session_id)
        try:
            return path.read_text()
        except OSError:
            return None

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

    def submit_debug_decision(
        self,
        run_id: str,
        issue_id: str,
        action: str,
    ) -> None:
        """Submit a debug decision. Raises ValueError with categorized messages
        that the HTTP layer maps to 400/404/409/410.

        Comments are no longer accepted here — they were persisted on the
        daemon as the user authored them (Task 7) and the reducer reads them
        from `Issue.inline_comments` + `Issue.comment_threads` when bundling
        the `debug_modify_request` event payload.
        """
        run_info = self._runs.get(run_id)
        if run_info is None:
            raise ValueError(f"Run {run_id!r} not found")
        if run_info.status == RunStatus.STOPPED:
            raise ValueError(f"Run {run_id!r}: run_stopped")
        if run_info.orchestrator is None:
            raise ValueError(f"Run {run_id!r}: no orchestrator")
        if not run_info.orchestrator.is_debug_pending(issue_id):
            issue = run_info.orchestrator.state.issues.get(issue_id)
            if issue is not None:
                last_decision = next(
                    (e for e in reversed(issue.event_log) if e.type == "debug_decision"),
                    None,
                )
                if last_decision is not None:
                    raise ValueError(
                        f"Issue {issue_id!r}: already_decided (prior action: {last_decision.data.get('action')})"
                    )
            raise ValueError(f"Issue {issue_id!r}: not_pending")
        run_info.orchestrator.submit_debug_decision(issue_id, action)

    async def restart_state(self, run_id: str, issue_id: str) -> None:
        """Restart a state after a modify_restart rewrite."""
        run_info = self._runs.get(run_id)
        if run_info is None:
            raise ValueError(f"Run {run_id!r} not found")
        if run_info.orchestrator is None:
            raise ValueError(f"Run {run_id!r}: no orchestrator")
        await run_info.orchestrator.restart_state(issue_id)

    def clear_modify_pending(self, run_id: str, issue_id: str) -> None:
        run_info = self._runs.get(run_id)
        if run_info is None or run_info.orchestrator is None:
            raise ValueError(f"Run {run_id!r} not found")
        run_info.orchestrator.clear_modify_pending(issue_id)

    # ------------------------------------------------------------------ #
    # Inline comments + comment threads                                  #
    # ------------------------------------------------------------------ #

    def save_inline_comment(
        self,
        run_id: str,
        issue_id: str,
        comment_id: str,
        file: str,
        line: int | None,
        body: str,
    ) -> None:
        run_info = self._runs.get(run_id)
        if run_info is None or run_info.orchestrator is None:
            raise ValueError(f"Run {run_id!r} not found")
        run_info.orchestrator.save_inline_comment(issue_id, comment_id, file, line, body)

    def delete_inline_comment(self, run_id: str, issue_id: str, comment_id: str) -> None:
        run_info = self._runs.get(run_id)
        if run_info is None or run_info.orchestrator is None:
            raise ValueError(f"Run {run_id!r} not found")
        run_info.orchestrator.delete_inline_comment(issue_id, comment_id)

    def add_thread_message(
        self,
        run_id: str,
        issue_id: str,
        comment_id: str,
        role: str,
        body: str,
    ) -> str:
        run_info = self._runs.get(run_id)
        if run_info is None or run_info.orchestrator is None:
            raise ValueError(f"Run {run_id!r} not found")
        return run_info.orchestrator.add_thread_message(issue_id, comment_id, role, body)

    def skip_comment(self, run_id: str, issue_id: str, comment_id: str, reason: str) -> None:
        run_info = self._runs.get(run_id)
        if run_info is None or run_info.orchestrator is None:
            raise ValueError(f"Run {run_id!r} not found")
        run_info.orchestrator.skip_comment(issue_id, comment_id, reason)

    def list_inline_comments_with_threads(self, run_id: str, issue_id: str) -> list[dict[str, Any]]:
        run_info = self._runs.get(run_id)
        if run_info is None or run_info.orchestrator is None:
            raise ValueError(f"Run {run_id!r} not found")
        return run_info.orchestrator.list_inline_comments_with_threads(issue_id)

    def get_debug_review(
        self,
        run_id: str,
        issue_id: str,
        *,
        attempt: int | None = None,
    ) -> dict[str, Any] | None:
        """Return the debug-review snapshot as a dict, or None.

        When `attempt` is None: returns the active pause's snapshot if
        `is_debug_pending(issue_id)`, else None. (Original behavior.)

        When `attempt` is an int: bypasses the pending guard. Walks the
        issue's event_log for the Nth debug_review_required event, finds
        the next debug_decision, projects its persisted comments back into
        the live wire shape, and returns the snapshot dict EXTENDED with a
        `past_review` field. Returns None if the attempt index is out of
        range.
        """
        run_info = self._runs.get(run_id)
        if run_info is None:
            return None
        state = self._state_for_run(run_info)
        if state is None:
            return None
        issue = state.issues.get(issue_id)
        if issue is None:
            return None

        if attempt is None:
            pending = (
                run_info.orchestrator.is_debug_pending(issue_id)
                if run_info.orchestrator is not None
                else bool(issue.debug_pending)
            )
            if not pending:
                return None
            for entry in reversed(issue.event_log):
                if entry.type == "debug_review_required":
                    return entry.data.get("snapshot")
            return None

        # Past-attempt branch: bypass debug_pending guard.
        if attempt < 0:
            return None
        attempts = _pair_debug_attempts(issue.event_log, drop_pending_tail=False)
        if attempt >= len(attempts):
            return None
        target = attempts[attempt]

        # Find the matching snapshot: it's the (attempt+1)th debug_review_required.
        snapshot: dict[str, Any] | None = None
        decision_comments: list[dict[str, Any]] = []
        seen = -1
        for entry in issue.event_log:
            if entry.type == "debug_review_required":
                seen += 1
                if seen == attempt:
                    snapshot = entry.data.get("snapshot")
            elif entry.type == "debug_decision" and seen == attempt and snapshot is not None:
                decision_comments = entry.data.get("comments", [])
                break
        if snapshot is None:
            return None

        inline_comments, comment_threads = _project_past_comments(decision_comments)
        return {
            **snapshot,
            "past_review": {
                "attempt": target["attempt"],
                "state": target["state"],
                "state_local_index": target["state_local_index"],
                "paused_at": target["paused_at"],
                "decision_action": target["decision"],
                "decided_at": target["decided_at"],
                "inline_comments": inline_comments,
                "comment_threads": comment_threads,
            },
        }

    def list_debug_attempts(self, run_id: str, issue_id: str) -> list[dict[str, Any]]:
        """Return the list of past debug-review attempts for this issue.

        Each item: {attempt, state, state_local_index, paused_at, decision, decided_at}.
        Excludes the currently-active pause when issue.debug_pending=True —
        the live URL serves that one. Undecided pauses from crashed runs
        still appear with decision=None.
        """
        run_info = self._runs.get(run_id)
        if run_info is None:
            return []
        state = self._state_for_run(run_info)
        if state is None:
            return []
        issue = state.issues.get(issue_id)
        if issue is None:
            return []
        return _pair_debug_attempts(
            issue.event_log,
            drop_pending_tail=bool(issue.debug_pending),
        )

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

                # Check if all issues are terminal (completed run)
                all_terminal = all(issue.state == "done" for issue in state.issues.values())

                if all_terminal:
                    # Completed runs are preserved in the listing (not invisible)
                    self._runs[run_id] = RunInfo(
                        run_id=run_id,
                        branch=branch,
                        workflow=workflow_name,
                        status=RunStatus.COMPLETED,
                        issue_count=len(state.issues),
                        created_at=_now(),
                        config=config,
                    )
                    continue

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
