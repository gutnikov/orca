from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from orca.engine.dispatch import build_run_context
from orca.engine.reducer import reduce
from orca.engine.types import (
    DispatchWorkerEffect,
    Effect,
    ErrorEffect,
    State,
    StateMachineConfig,
    WorkerFailedEvent,
    WorkerResultEvent,
)
from orca.orchestrator.branches import BranchMap
from orca.orchestrator.persistence import Persistence
from orca.orchestrator.pty_session import PtySession
from orca.orchestrator.session_sync import SessionSync
from orca.orchestrator.worker import Worker, WorkerFailure, WorkerOutcome, WorkerSuccess
from orca.orchestrator.worktree import WorktreeManager

logger = logging.getLogger(__name__)


def _notify_form_pending(run_id: str, issue_id: str) -> None:
    """Log the form URL and try to open the user's browser.

    The daemon's localhost TCP listener serves the React form app; this
    helper builds a URL pointing at it and best-effort opens the user's
    default browser. Both the log line and the browser open are safe to
    fail (e.g. headless SSH session — the URL is still in the log).
    """
    raw = os.environ.get("ORCA_DAEMON_TCP_PORT", "7891")
    if raw.strip().lower() in ("", "0", "off", "false"):
        return
    try:
        port = int(raw)
    except ValueError:
        return
    from urllib.parse import quote

    url = f"http://127.0.0.1:{port}/forms/{quote(run_id, safe='')}/{quote(issue_id, safe='')}"
    logger.info("⏳ Form pending for issue %s — open %s", issue_id, url)
    try:
        import webbrowser

        webbrowser.open(url)
    except Exception:
        # Headless / no display — URL is still in the log.
        pass


def _slugify(title: str, max_len: int = 60) -> str:
    """Convert an issue title to a git-branch-safe slug."""
    slug = title.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    if len(slug) > max_len:
        slug = slug[:max_len].rstrip("-")
    return slug or "issue"


class Orchestrator:
    def __init__(
        self,
        config: StateMachineConfig,
        state: State,
        root_branch: str,
        persistence: Persistence,
        branches: BranchMap,
        workers: Mapping[str, Worker],
        generate_id: Callable[[], str],
        now: Callable[[], str],
        worktree_mgr: WorktreeManager,
        repo_root: Path | None = None,
        flow_root: Path | None = None,
        session_sync: SessionSync | None = None,
        insights_enabled: bool = False,
        hot_sessions: set[str] | None = None,
        session_log_paths: dict[str, str] | None = None,
        insights_state: dict[str, str] | None = None,
        eval_name: str | None = None,
    ) -> None:
        self._config = config
        self._state = state
        self.root_branch = root_branch
        self.persistence = persistence
        self.branches = branches
        self.workers: Mapping[str, Worker] = workers
        self.generate_id = generate_id
        self.now = now
        self.worktree_mgr = worktree_mgr
        self.repo_root = repo_root
        self.flow_root = flow_root or repo_root
        self.eval_name = eval_name
        self._session_sync = session_sync
        self._insights_enabled = insights_enabled
        self._insights_state = insights_state
        self._insights_tracking_id: str = ""
        # Shared with TUI: which sessions should be captured frequently
        self._hot_sessions: set[str] = hot_sessions if hot_sessions is not None else set()
        # Shared with TUI: maps tracking_id -> log file path
        self._session_log_paths: dict[str, str] = session_log_paths if session_log_paths is not None else {}
        # Internal: maps tracking_id -> TmuxSession (orchestrator only)
        self._tmux_sessions: dict[str, PtySession] = {}
        self._last_save: dict[str, float] = {}
        # Maps asyncio.Task -> (issue_id, tracking_id)
        self._in_flight: dict[asyncio.Task[WorkerOutcome], tuple[str, str]] = {}
        self._progress_sessions: set[str] = set()
        # Maps issue_id -> (unblock_event, message_box) for waiting workers
        self._waiting_workers: dict[str, tuple[asyncio.Event, list[str]]] = {}
        # Track used branch slugs to avoid collisions
        self._used_slugs: set[str] = set()
        for branch in self.branches.values():
            self._used_slugs.add(branch)

    async def stop(self) -> None:
        """Cancel in-flight workers and kill all tmux sessions."""
        for task in list(self._in_flight.keys()):
            task.cancel()
        if self._in_flight:
            await asyncio.gather(*self._in_flight.keys(), return_exceptions=True)
        self._in_flight.clear()
        for session in list(self._tmux_sessions.values()):
            with contextlib.suppress(Exception):
                session.close()
        self._tmux_sessions.clear()

    @property
    def state(self) -> State:
        """Current state of the state machine."""
        return self._state

    @property
    def config(self) -> StateMachineConfig:
        """State machine configuration."""
        return self._config

    @property
    def hot_sessions(self) -> set[str]:
        """Sessions the TUI wants captured frequently."""
        return self._hot_sessions

    @property
    def session_log_paths(self) -> dict[str, str]:
        """Map of tracking_id -> log file path (shared with TUI)."""
        return self._session_log_paths

    @property
    def insights_tracking_id(self) -> str:
        return self._insights_tracking_id

    def get_session_log(self, tracking_id: str, tail: int = 100) -> str:
        """Read session log content for a tracking ID.

        Returns empty string if the tracking ID is unknown or the log file
        does not exist.  When *tail* is given, only the last *tail* lines
        are returned.
        """
        log_path_str = self._session_log_paths.get(tracking_id)
        if not log_path_str:
            return ""
        log_path = Path(log_path_str)
        if not log_path.exists():
            return ""
        text = log_path.read_text()
        lines = text.splitlines()
        if tail and len(lines) > tail:
            lines = lines[-tail:]
        return "\n".join(lines) + "\n"

    def get_session_log_by_issue(self, issue_id: str, tail: int = 100) -> str:
        """Read session log for the latest session of the given issue_id.

        Looks up the issue's most recent session in the manifest, then
        delegates to ``get_session_log`` with the session's tracking_id.
        Returns empty string if no session is found.
        """
        if self._session_sync is None:
            return ""
        entries = self._session_sync.manifest.read()
        # Find the latest session for this issue_id (last in the list)
        tracking_id = ""
        for entry in entries:
            if entry.get("issue_id") == issue_id:
                tracking_id = entry.get("session_id", "")
        if not tracking_id:
            return ""
        return self.get_session_log(tracking_id, tail)

    def set_hot_session(self, session_id: str) -> None:
        """Mark a session as hot (high-frequency capture)."""
        self._hot_sessions.add(session_id)

    def set_cold_session(self, session_id: str) -> None:
        """Mark a session as cold (low-frequency capture)."""
        self._hot_sessions.discard(session_id)

    def unblock_worker(self, issue_id: str, message: str) -> bool:
        """Unblock a blocked worker by setting its event and message.

        Returns False if the issue is not currently blocked.
        """
        entry = self._waiting_workers.get(issue_id)
        if entry is None:
            return False
        event, msg_box = entry
        msg_box.clear()
        msg_box.append(message)
        event.set()
        return True

    def is_waiting(self, issue_id: str) -> bool:
        """True if a worker for this issue is currently blocked awaiting unblock."""
        return issue_id in self._waiting_workers

    def mark_form_submitted(self, issue_id: str, ts: str) -> None:
        """Stamp `pending_form_submitted_at` on an issue and persist.

        Subsequent GETs on the form endpoint will return 410 until the worker
        actually resumes (which clears both pending_form fields).
        """
        issue = self._state.issues.get(issue_id)
        if issue is None:
            return
        issue.pending_form_submitted_at = ts
        self.persistence.save(self._state)

    def _is_terminal(self, issue_id: str) -> bool:
        """Return True if the issue's current state is terminal in config."""
        issue = self._state.issues.get(issue_id)
        if issue is None:
            return False
        return issue.state == "done"

    def _unique_branch_name(self, title: str, parent_branch: str) -> str:
        """Generate a unique, human-readable branch name from an issue title.

        Uses '-' as separator (not '/') so the logical branch name matches
        the git branch name. Hierarchical '/' separators cause git ref
        conflicts when parent and child branches coexist.
        """
        slug = _slugify(title)
        branch = f"{parent_branch}-{slug}"
        if branch not in self._used_slugs:
            self._used_slugs.add(branch)
            return branch
        for i in range(2, 1000):
            candidate = f"{branch}-{i}"
            if candidate not in self._used_slugs:
                self._used_slugs.add(candidate)
                return candidate
        fallback = f"{parent_branch}-{slug}-{self.generate_id()[:8]}"
        self._used_slugs.add(fallback)
        return fallback

    async def _ensure_worktree(self, issue_id: str) -> Path:
        """Ensure a worktree exists for the issue, creating one if needed."""
        existing_branch = self.branches.get(issue_id)
        if existing_branch is not None:
            worktree_path = self.worktree_mgr.resolve(existing_branch)
            if worktree_path.exists():
                return worktree_path
            # Branch registered but no worktree dir — root issue reusing an
            # existing branch.  Fall back to the repo root.
            if self.repo_root is not None:
                return self.repo_root
            return worktree_path

        # Derive a human-readable branch name from the issue title
        issue = self._state.issues[issue_id]
        title = str(issue.fields.get("title", "issue"))

        # Find parent branch to base the worktree on
        parent_branch = self.root_branch
        if issue.decomposed_from is not None:
            parent_branch = self.branches.get(issue.decomposed_from) or self.root_branch

        branch_name = self._unique_branch_name(title, parent_branch)
        worktree_path = await self.worktree_mgr.create(
            issue_id=issue_id,
            branch_name=branch_name,
            parent_branch=parent_branch,
        )

        self.branches.set(issue_id, branch_name)
        self.branches.save()

        return worktree_path

    def _spawn_worker(self, effect: DispatchWorkerEffect) -> None:
        """Resolve the worker for the effect and spawn an asyncio task."""
        type_def = self._config.types.get(effect.issue_type)
        if type_def is None:
            logger.warning(
                "No type definition for type %r — skipping dispatch",
                effect.issue_type,
                extra={"event": "no_type_definition", "issue_type": effect.issue_type},
            )
            return
        state_def = type_def.states.get(effect.state)
        if state_def is None or state_def.worker is None:
            logger.warning(
                "No worker definition for state %r — skipping dispatch",
                effect.state,
                extra={"event": "no_worker_definition", "state": effect.state},
            )
            return

        worker_kind = state_def.worker.kind
        worker = self.workers.get(worker_kind)
        if worker is None:
            logger.warning(
                "Unknown worker kind %r — skipping dispatch",
                worker_kind,
                extra={"event": "unknown_worker_kind", "worker_kind": worker_kind},
            )
            return

        # Record in-flight session so the TUI can show it
        tracking_id = str(uuid4())
        if self._session_sync is not None:
            branch = self.branches.get(effect.issue_id) or effect.issue_id
            workdir = self.worktree_mgr.resolve(branch)
            # If the worktree dir doesn't exist, the root issue is reusing the
            # repo checkout directly — record repo_root instead.
            if not workdir.exists() and self.repo_root is not None:
                workdir = self.repo_root
            self._session_sync.manifest.append(
                issue_id=effect.issue_id,
                state=effect.state,
                session_id=tracking_id,
                worktree_path=str(workdir),
                started_at=self.now(),
            )

        if effect.progress_enabled:
            self._progress_sessions.add(tracking_id)

        # Exponential backoff for retries: 5s, 10s, 20s, 40s, ...
        issue = self._state.issues.get(effect.issue_id)
        failures = issue.failure_count if issue else 0
        backoff = 5.0 * (2**failures) if failures > 0 else 0.0

        task: asyncio.Task[WorkerOutcome] = asyncio.create_task(
            self._run_worker_with_backoff(
                effect,
                worker,
                state_def.worker.prompt,
                backoff,
                tracking_id,
                model=state_def.worker.model,
                extra_args=state_def.worker.args,
                prompt_inline=state_def.worker.prompt_inline,
            )
        )
        self._in_flight[task] = (effect.issue_id, tracking_id)
        logger.info(
            "Worker dispatched for issue %s in state %s",
            effect.issue_id,
            effect.state,
            extra={
                "event": "worker_dispatched",
                "issue_id": effect.issue_id,
                "state": effect.state,
                "worker_kind": worker_kind,
            },
        )

    def _resolve_base_branch(self, issue_id: str) -> str:
        """Resolve the base branch for an issue (parent's branch or root_branch)."""
        issue = self._state.issues.get(issue_id)
        if issue is not None and issue.decomposed_from is not None:
            parent_branch = self.branches.get(issue.decomposed_from)
            if parent_branch is not None:
                return parent_branch
        return self.root_branch

    async def _run_worker_with_backoff(
        self,
        effect: DispatchWorkerEffect,
        worker: Worker,
        prompt_template: str,
        backoff: float,
        tracking_id: str,
        model: str | None = None,
        extra_args: tuple[str, ...] | None = None,
        prompt_inline: bool = False,
    ) -> WorkerOutcome:
        """Wait for backoff delay, then run the worker."""
        if backoff > 0:
            logger.info(
                "Backing off %.0fs before retrying issue %s",
                backoff,
                effect.issue_id,
                extra={"event": "worker_backoff", "issue_id": effect.issue_id, "backoff_seconds": backoff},
            )
            await asyncio.sleep(backoff)
        return await self._run_worker(
            effect,
            worker,
            prompt_template,
            tracking_id,
            model=model,
            extra_args=extra_args,
            prompt_inline=prompt_inline,
        )

    async def _run_worker(
        self,
        effect: DispatchWorkerEffect,
        worker: Worker,
        prompt_template: str,
        tracking_id: str,
        model: str | None = None,
        extra_args: tuple[str, ...] | None = None,
        prompt_inline: bool = False,
    ) -> WorkerOutcome:
        """Create worktree if needed, then execute the worker."""
        workdir = await self._ensure_worktree(effect.issue_id)

        # Update the manifest with the real worktree path (may differ from the
        # preliminary path recorded in _spawn_worker when the branch didn't exist yet).
        if self._session_sync is not None:
            self._session_sync.manifest.update_worktree_path(tracking_id, str(workdir))
        # When the root issue reuses an existing branch, workdir is the repo
        # root.  Avoid polluting .orca-state/ with result.json — write it to the
        # run directory (.orca-state/runs/{branch}/) instead.
        if workdir == self.repo_root:
            result_path = self.persistence.state_path.parent / "result.json"
        else:
            result_path = workdir / ".orca-state" / "result.json"

        prompt_path: Path | None = None
        prompt_text: str | None = None
        if prompt_inline:
            prompt_text = prompt_template
        elif self.flow_root is not None:
            prompt_path = self.flow_root / prompt_template

        # Enrich issue context with base_branch for the prompt template
        base_branch = self._resolve_base_branch(effect.issue_id)
        enriched_effect = DispatchWorkerEffect(
            issue_id=effect.issue_id,
            issue_type=effect.issue_type,
            state=effect.state,
            result_format=effect.result_format,
            issue={**effect.issue, "base_branch": base_branch},
            progress_enabled=effect.progress_enabled,
        )

        type_def = self._config.types.get(effect.issue_type)
        state_def = type_def.states.get(effect.state) if type_def is not None else None
        inactivity_timeout = (
            state_def.worker.inactivity_timeout or state_def.worker.timeout if state_def and state_def.worker else None
        )

        # Create TmuxSession and register log path for TUI
        tmux_session = PtySession(session_name=tracking_id, cols=120, rows=40)
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
        log_dir = workdir / ".orca-state" / "sessions"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"{enriched_effect.state}-{timestamp}.log"

        self._tmux_sessions[tracking_id] = tmux_session
        self._session_log_paths[tracking_id] = str(log_path)
        if self._session_sync is not None:
            self._session_sync.manifest.update_log_path(tracking_id, str(log_path))

        # Build run context for prompt templates
        run_context: dict[str, Any] | None = None
        if self.repo_root is not None and self._session_sync is not None:
            run_dir = self.persistence.state_path.parent
            sessions_dir = self.repo_root / ".orca-state" / "sessions"
            run_context = build_run_context(
                state=self._state,
                run_dir=run_dir,
                sessions_dir=sessions_dir,
                sessions=self._session_sync.manifest.read(),
                branch=self.root_branch,
                workflow=run_dir.name,
                eval_name=self.eval_name,
            )

        # Create unblock channel for this worker
        unblock_event = asyncio.Event()
        unblock_message: list[str] = []
        self._waiting_workers[effect.issue_id] = (unblock_event, unblock_message)

        def _on_blocked(reason: str, form: dict[str, Any] | None) -> None:
            from orca.engine.types import WorkerWaitingEvent

            ts = self.now()
            self._state, _ = reduce(
                self._config,
                self._state,
                WorkerWaitingEvent(issue_id=effect.issue_id, reason=reason, timestamp=ts, form=form),
                self.generate_id,
                self.now,
            )
            self.persistence.save(self._state)
            if form is not None:
                # Derive run_id (branch:workflow) from the persistence state path.
                state_path = self.persistence.state_path
                branch = state_path.parent.parent.name
                workflow = state_path.parent.name
                _notify_form_pending(f"{branch}:{workflow}", effect.issue_id)

        def _on_unblocked(message: str) -> None:
            from orca.engine.types import WorkerResumedEvent

            ts = self.now()
            self._state, _ = reduce(
                self._config,
                self._state,
                WorkerResumedEvent(issue_id=effect.issue_id, message=message, timestamp=ts),
                self.generate_id,
                self.now,
            )
            self.persistence.save(self._state)

        try:
            outcome = await worker.execute(
                enriched_effect,
                workdir,
                result_path,
                prompt_path,
                inactivity_timeout,
                pty_session=tmux_session,
                env=dict(os.environ),
                model=model,
                extra_args=list(extra_args) if extra_args else None,
                session_manifest=self._session_sync.manifest if self._session_sync else None,
                session_id=tracking_id,
                run_context=run_context,
                unblock_event=unblock_event,
                unblock_message=unblock_message,
                on_blocked=_on_blocked,
                on_unblocked=_on_unblocked,
                prompt_text=prompt_text,
            )
        finally:
            self._waiting_workers.pop(effect.issue_id, None)
            # Final scrollback save before killing the session
            try:
                raw = tmux_session.capture_scrollback()
                if raw:
                    log_path.write_text(raw)
            except Exception:
                pass

            self._tmux_sessions.pop(tracking_id, None)
            tmux_session.close()

        return outcome

    def _process_retry_signals(self, pending: list[DispatchWorkerEffect]) -> bool:
        """Check for retry signal files from the TUI. Returns True if any retries were queued."""
        retry_dir = self.persistence.state_path.parent / "retry"
        if not retry_dir.exists():
            return False

        retried = False
        for signal_file in retry_dir.iterdir():
            issue_id = signal_file.name
            signal_file.unlink()

            issue = self._state.issues.get(issue_id)
            if issue is None:
                continue
            if issue.worker_active:
                continue  # already running
            if issue.failure_count == 0:
                continue  # not failed

            # Reset failure count and re-dispatch
            issue.failure_count = 0
            issue.worker_active = True

            type_def = self._config.types.get(issue.type)
            if type_def is None:
                continue
            state_def = type_def.states.get(issue.state)
            if state_def is None or state_def.worker is None:
                continue

            from orca.engine.dispatch import build_issue_context, build_result_format

            pending.append(
                DispatchWorkerEffect(
                    issue_id=issue_id,
                    issue_type=issue.type,
                    state=issue.state,
                    result_format=build_result_format(self._config, issue.type, issue.state),
                    issue=build_issue_context(self._state, issue_id),
                )
            )
            self.persistence.save(self._state)
            logger.info(
                "Retry signal processed for issue %s",
                issue_id,
                extra={"event": "retry_signal", "issue_id": issue_id, "state": issue.state},
            )
            retried = True

        return retried

    def _route_effects(self, effects: list[Effect], pending: list[DispatchWorkerEffect]) -> None:
        """Separate effects: dispatch workers immediately or log errors."""
        for effect in effects:
            if isinstance(effect, DispatchWorkerEffect):
                pending.append(effect)
            elif isinstance(effect, ErrorEffect):
                logger.error(
                    "ErrorEffect for issue %r: %s",
                    effect.issue_id,
                    effect.message,
                    extra={"event": "error_effect", "issue_id": effect.issue_id, "error": effect.message},
                )

    def _build_insights_prompt(self) -> str:
        prompt_path = Path(__file__).parent / "prompts" / "insights.md"
        template = prompt_path.read_text()
        run_dir = self.persistence.state_path.parent
        config_path = ""
        if self.repo_root:
            for candidate in sorted(self.repo_root.glob("orca*.yml")):
                config_path = str(candidate)
                break
        return template.format(
            run_dir=str(run_dir),
            branch_name=self.root_branch,
            config_path=config_path,
            repo_root=str(self.repo_root or "."),
        )

    async def _session_capture_loop(self) -> None:
        """Periodically capture tmux scrollback to log files.

        Hot sessions (selected in TUI) are captured every 1s.
        Cold sessions are captured every 10s.
        """
        import time

        while True:
            await asyncio.sleep(1.0)
            now = time.monotonic()
            for tid, tmux in list(self._tmux_sessions.items()):
                is_hot = tid in self._hot_sessions
                interval = 0.5 if is_hot else 10.0
                last = self._last_save.get(tid, 0.0)
                if now - last < interval:
                    continue
                try:
                    log_path_str = self._session_log_paths.get(tid)
                    if log_path_str and tmux.alive:
                        raw = tmux.capture_scrollback()
                        if raw:
                            Path(log_path_str).write_text(raw)
                            if tid in self._progress_sessions and self._session_sync is not None:
                                from orca.orchestrator.worker import parse_progress

                                progress_result = parse_progress(raw)
                                if progress_result is not None:
                                    percent, status = progress_result
                                    self._session_sync.manifest.update_progress(tid, percent, status)
                        self._last_save[tid] = now
                except Exception:
                    pass

    async def run(self, root_issue_id: str, initial_effects: list[Effect]) -> None:
        """Drive the orchestrator event loop until the root issue is terminal."""
        capture_task = asyncio.create_task(self._session_capture_loop())

        pending: list[DispatchWorkerEffect] = []
        self._route_effects(initial_effects, pending)

        # Spawn insights tmux session if enabled
        insights_session: PtySession | None = None
        if self._insights_enabled and self.repo_root is not None:
            from orca.orchestrator.pty_session import TmuxSession

            insights_id = f"insights-{uuid4()}"
            self._insights_tracking_id = insights_id
            insights_session = TmuxSession(session_name=insights_id, cols=120, rows=40)
            prompt = self._build_insights_prompt()
            log_dir = self.repo_root / ".orca-state" / "sessions"
            log_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
            insights_log = log_dir / f"insights-{ts}.log"
            await insights_session.spawn(
                "claude",
                ["--dangerously-skip-permissions", "--max-turns", "200"],
                cwd=self.repo_root,
                stdin_data=prompt.encode(),
            )
            self._tmux_sessions[insights_id] = insights_session
            self._session_log_paths[insights_id] = str(insights_log)
            if self._insights_state is not None:
                self._insights_state["tracking_id"] = insights_id

        while not self._is_terminal(root_issue_id):
            # Spawn all pending dispatch effects
            for effect in pending:
                self._spawn_worker(effect)
            pending.clear()

            # Nothing in flight — check for retry signals before declaring deadlock
            if not self._in_flight:
                retried = self._process_retry_signals(pending)
                if retried:
                    continue
                logger.warning(
                    "Deadlock detected: no tasks in flight and no pending effects. Stopping.",
                    extra={"event": "deadlock_detected"},
                )
                break

            # Wait for at least one task to complete, with timeout to check for retry signals
            done, _ = await asyncio.wait(
                list(self._in_flight.keys()),
                timeout=5.0,
                return_when=asyncio.FIRST_COMPLETED,
            )

            # Check for retry signals on each wakeup (timeout or completion)
            self._process_retry_signals(pending)

            if not done:
                continue  # timeout — loop back to spawn any retried tasks

            for task in done:
                issue_id, tracking_id = self._in_flight.pop(task)
                try:
                    outcome: WorkerOutcome = task.result()
                except Exception as exc:
                    # Treat unexpected exceptions as worker failures
                    outcome = WorkerFailure(error=f"task raised exception: {exc}")

                ts = self.now()

                # Mark the in-flight session as completed
                if self._session_sync is not None:
                    self._session_sync.manifest.mark_completed(tracking_id, ts)
                    self._progress_sessions.discard(tracking_id)

                if isinstance(outcome, WorkerSuccess):
                    event: WorkerResultEvent | WorkerFailedEvent = WorkerResultEvent(
                        issue_id=issue_id,
                        result=outcome.result,
                        timestamp=ts,
                    )
                else:
                    event = WorkerFailedEvent(
                        issue_id=issue_id,
                        error=outcome.error,
                        timestamp=ts,
                    )

                old_issues = set(self._state.issues.keys())
                old_issue_state = self._state.issues[issue_id].state if issue_id in self._state.issues else None

                self._state, new_effects = reduce(
                    self._config,
                    self._state,
                    event,
                    self.generate_id,
                    self.now,
                )

                self.persistence.save(self._state)

                # Log worker outcome
                if isinstance(outcome, WorkerSuccess):
                    logger.info(
                        "Worker succeeded for issue %s",
                        issue_id,
                        extra={
                            "event": "worker_succeeded",
                            "issue_id": issue_id,
                            "result_outcome": outcome.result.get("outcome"),
                        },
                    )
                else:
                    logger.warning(
                        "Worker failed for issue %s: %s",
                        issue_id,
                        outcome.error,
                        extra={"event": "worker_failed", "issue_id": issue_id, "error": outcome.error},
                    )

                # Detect state transition
                new_issue_state = self._state.issues[issue_id].state if issue_id in self._state.issues else None
                if old_issue_state and new_issue_state and old_issue_state != new_issue_state:
                    logger.info(
                        "Issue %s transitioned from %s to %s",
                        issue_id,
                        old_issue_state,
                        new_issue_state,
                        extra={
                            "event": "state_transitioned",
                            "issue_id": issue_id,
                            "from_state": old_issue_state,
                            "to_state": new_issue_state,
                        },
                    )

                # Detect new issues (decomposition)
                new_issues = set(self._state.issues.keys()) - old_issues
                for new_id in new_issues:
                    new_issue = self._state.issues[new_id]
                    logger.info(
                        "Issue %s created: %s",
                        new_id,
                        new_issue.fields.get("title", ""),
                        extra={
                            "event": "issue_created",
                            "issue_id": new_id,
                            "parent_id": new_issue.decomposed_from,
                            "title": new_issue.fields.get("title", ""),
                        },
                    )

                self._route_effects(new_effects, pending)

        # Cancel any remaining in-flight tasks
        for task in list(self._in_flight.keys()):
            task.cancel()
        if self._in_flight:
            await asyncio.gather(*self._in_flight.keys(), return_exceptions=True)
        self._in_flight.clear()

        # Clean up insights session
        if insights_session is not None:
            await asyncio.sleep(10)  # brief wait for agent to notice completion
            try:
                raw = insights_session.capture_scrollback()
                if raw and self._insights_tracking_id in self._session_log_paths:
                    Path(self._session_log_paths[self._insights_tracking_id]).write_text(raw)
            except Exception:
                pass
            self._tmux_sessions.pop(self._insights_tracking_id, None)
            insights_session.close()

        capture_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await capture_task
