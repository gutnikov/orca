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
    DebugReviewSnapshot,
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
from orca.orchestrator.worktree_helpers import current_head

logger = logging.getLogger(__name__)


class DeadlockError(RuntimeError):
    """Raised when the run loop has nothing in flight and no pending effects,
    yet the root issue is not in a terminal state — a workflow gap that
    leaves the root un-finishable. The daemon marks the run FAILED so callers
    don't conflate this with a clean COMPLETED."""


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
        hot_sessions: set[str] | None = None,
        session_log_paths: dict[str, str] | None = None,
        worker_overrides: dict[str, dict[str, str]] | None = None,
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
        self._session_sync = session_sync
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
        # Run-level debug flag. When True, after every successful worker
        # completion, the orchestrator builds a DebugReviewSnapshot, emits
        # DebugReviewRequiredEvent, and awaits a DebugDecisionEvent before
        # applying the worker's transition.
        self.debug: bool = False
        # Maps issue_id -> (decision_event, decision_box). decision_box is a
        # one-element list holding {"action": str, "comments": list[dict]}.
        self._debug_decision_events: dict[str, tuple[asyncio.Event, list[dict[str, Any]]]] = {}
        # Track used branch slugs to avoid collisions
        self._used_slugs: set[str] = set()
        for branch in self.branches.values():
            self._used_slugs.add(branch)
        # Per-state, per-field worker overrides applied at dispatch time. Keyed
        # by state name; each entry may carry `kind` / `model` / `effort`.
        # State names not present here keep their workflow-config defaults.
        self._worker_overrides: dict[str, dict[str, str]] = worker_overrides or {}

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

    def submit_debug_decision(
        self,
        issue_id: str,
        action: str,
    ) -> bool:
        """Submit a debug decision for a paused issue. Returns False if no debug pause is active.

        Comments are no longer carried on the decision payload — they were
        persisted on the daemon as the user authored them (Task 7) and the
        reducer reads them from `Issue.inline_comments` + `Issue.comment_threads`
        when bundling the `debug_modify_request` event payload.
        """
        entry = self._debug_decision_events.get(issue_id)
        if entry is None:
            return False
        event, box = entry
        box.clear()
        box.append({"action": action})
        event.set()
        return True

    def is_debug_pending(self, issue_id: str) -> bool:
        """True if an issue is currently paused awaiting a debug decision."""
        return issue_id in self._debug_decision_events

    def clear_modify_pending(self, issue_id: str) -> None:
        """Clear modify_pending after a modify_continue rewrite is done.

        Used when the user picked "Modify prompts & configs → continue":
        the state already advanced (worker_result was accepted), so no
        worker re-dispatch is needed — just drop the flag so the agent's
        polling loop stops seeing this as pending work.
        """
        issue = self._state.issues.get(issue_id)
        if issue is None:
            raise ValueError(f"Issue {issue_id!r} not found")
        if not issue.modify_pending:
            return
        issue.modify_pending = False
        self.persistence.save(self._state)

    # ------------------------------------------------------------------ #
    # Inline comments + comment threads                                  #
    # ------------------------------------------------------------------ #

    def save_inline_comment(
        self,
        issue_id: str,
        comment_id: str,
        file: str,
        line: int | None,
        body: str,
    ) -> None:
        """Create-or-update an inline review comment. Idempotent on comment_id."""
        from orca.engine.types import InlineCommentSavedEvent

        if issue_id not in self._state.issues:
            raise ValueError(f"Issue {issue_id!r} not found")
        event = InlineCommentSavedEvent(
            issue_id=issue_id,
            comment_id=comment_id,
            file=file,
            line=line,
            body=body,
            timestamp=self.now(),
        )
        self._state, _ = reduce(self._config, self._state, event, self.generate_id, self.now)
        self.persistence.save(self._state)

    def delete_inline_comment(self, issue_id: str, comment_id: str) -> None:
        """Delete an inline comment and cascade-delete its thread."""
        from orca.engine.types import InlineCommentDeletedEvent

        if issue_id not in self._state.issues:
            raise ValueError(f"Issue {issue_id!r} not found")
        event = InlineCommentDeletedEvent(
            issue_id=issue_id,
            comment_id=comment_id,
            timestamp=self.now(),
        )
        self._state, _ = reduce(self._config, self._state, event, self.generate_id, self.now)
        self.persistence.save(self._state)

    def add_thread_message(
        self,
        issue_id: str,
        comment_id: str,
        role: str,
        body: str,
    ) -> str:
        """Append a message to a comment's thread. Returns the new message_id.

        Lazily creates the thread on the first message. Agent messages bump
        ``agent_last_reviewed_at``; user messages do not.
        """
        from orca.engine.types import CommentThreadMessageAddedEvent

        issue = self._state.issues.get(issue_id)
        if issue is None:
            raise ValueError(f"Issue {issue_id!r} not found")
        if not any(c.id == comment_id for c in issue.inline_comments):
            raise ValueError(f"Comment {comment_id!r} not found on issue {issue_id!r}")
        if role not in ("user", "agent"):
            raise ValueError(f"Invalid role {role!r}")
        message_id = self.generate_id()
        event = CommentThreadMessageAddedEvent(
            issue_id=issue_id,
            comment_id=comment_id,
            role=role,
            message_id=message_id,
            body=body,
            timestamp=self.now(),
        )
        self._state, _ = reduce(self._config, self._state, event, self.generate_id, self.now)
        self.persistence.save(self._state)
        return message_id

    def skip_comment(self, issue_id: str, comment_id: str, reason: str) -> None:
        """Mark a comment reviewed without appending a message.

        Lazily creates an empty thread if none exists and bumps
        ``agent_last_reviewed_at`` so the agent's polling loop stops
        re-evaluating this comment.
        """
        from orca.engine.types import CommentThreadReviewedEvent

        issue = self._state.issues.get(issue_id)
        if issue is None:
            raise ValueError(f"Issue {issue_id!r} not found")
        if not any(c.id == comment_id for c in issue.inline_comments):
            raise ValueError(f"Comment {comment_id!r} not found on issue {issue_id!r}")
        event = CommentThreadReviewedEvent(
            issue_id=issue_id,
            comment_id=comment_id,
            timestamp=self.now(),
            reason=reason,
        )
        self._state, _ = reduce(self._config, self._state, event, self.generate_id, self.now)
        self.persistence.save(self._state)

    def list_inline_comments_with_threads(self, issue_id: str) -> list[dict[str, Any]]:
        """Return all inline comments on the issue, each with its thread (or None)."""
        issue = self._state.issues.get(issue_id)
        if issue is None:
            raise ValueError(f"Issue {issue_id!r} not found")
        thread_by_comment = {t.comment_id: t for t in issue.comment_threads}
        return [
            {
                "id": c.id,
                "file": c.file,
                "line": c.line,
                "body": c.body,
                "created_at": c.created_at,
                "updated_at": c.updated_at,
                "thread": thread_by_comment[c.id].to_dict() if c.id in thread_by_comment else None,
            }
            for c in issue.inline_comments
        ]

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

        # Resolve effective worker config = workflow YAML defaults overlaid
        # with any run-time overrides registered for this state. Overrides
        # let the user retarget kind/model/effort per state when invoking the
        # run, without editing the workflow.
        override = self._worker_overrides.get(effect.state, {})
        worker_kind = override.get("kind") or state_def.worker.kind
        effective_model = override.get("model") or state_def.worker.model
        effective_effort = override.get("effort") or state_def.worker.effort
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
                model=effective_model,
                extra_args=state_def.worker.args,
                prompt_inline=state_def.worker.prompt_inline,
                effort=effective_effort,
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
        effort: str | None = None,
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
            effort=effort,
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
        effort: str | None = None,
    ) -> WorkerOutcome:
        """Create worktree if needed, then execute the worker."""
        workdir = await self._ensure_worktree(effect.issue_id)

        # Record state_base_commit before dispatching so debug-mode restart knows
        # where to rewind the worktree.
        head = await current_head(workdir)
        issue_obj = self._state.issues.get(effect.issue_id)
        if issue_obj is not None and head is not None:
            issue_obj.state_base_commit = head
            self.persistence.save(self._state)

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
            )

        # Create unblock channel for this worker
        unblock_event = asyncio.Event()
        unblock_message: list[str] = []
        self._waiting_workers[effect.issue_id] = (unblock_event, unblock_message)

        def _on_blocked(reason: str) -> None:
            from orca.engine.types import WorkerWaitingEvent

            ts = self.now()
            self._state, _ = reduce(
                self._config,
                self._state,
                WorkerWaitingEvent(issue_id=effect.issue_id, reason=reason, timestamp=ts),
                self.generate_id,
                self.now,
            )
            self.persistence.save(self._state)
            # Mark the active session as waiting so the TUI WORKERS panel
            # renders a distinct indicator (gh#15) instead of the regular
            # in-flight spinner.
            if self._session_sync is not None:
                self._session_sync.manifest.update_waiting(tracking_id, waiting=True)

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
            # Worker resumed — clear the waiting flag so the panel re-shows
            # the in-flight treatment.
            if self._session_sync is not None:
                self._session_sync.manifest.update_waiting(tracking_id, waiting=False)

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
                effort=effort,
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

    def _resolve_config_path(self) -> Path:
        """Locate the workflow YAML file for the current run."""
        if self.flow_root is not None:
            for candidate in sorted(self.flow_root.glob("*.yml")):
                return candidate
        return (self.flow_root / "orca.yml") if self.flow_root else Path("/dev/null")

    async def _build_debug_review_snapshot(
        self,
        issue_id: str,
        worker_result: dict[str, Any],
    ) -> DebugReviewSnapshot | None:
        """Build the debug review snapshot for a completed worker result."""
        from orca.orchestrator.snapshot import build_snapshot
        from orca.orchestrator.template_persist import rendered_prompt_path

        issue = self._state.issues.get(issue_id)
        if issue is None:
            return None
        base_commit = issue.state_base_commit
        if base_commit is None:
            logger.warning("Cannot build debug review snapshot: no state_base_commit for issue %s", issue_id)
            return None

        branch = self.branches.get(issue_id) or self.root_branch
        workdir = self.worktree_mgr.resolve(branch)
        if not workdir.exists() and self.repo_root is not None:
            workdir = self.repo_root

        session_id = ""
        if self._session_sync is not None:
            entries = self._session_sync.manifest.read()
            for entry in entries:
                if entry.get("issue_id") == issue_id:
                    session_id = entry.get("session_id", "")
        prompt_path = rendered_prompt_path(workdir, issue.state, session_id) if session_id else workdir / "missing"

        config_path = self._resolve_config_path()

        return await build_snapshot(
            worktree_path=workdir,
            base_commit=base_commit,
            rendered_prompt_path=prompt_path,
            worker_result=worker_result,
            config_path=config_path,
            issue_type=issue.type,
            state_id=issue.state,
        )

    async def _pause_for_debug_review(self, issue_id: str, worker_result: dict[str, Any]) -> None:
        """Build the debug snapshot, emit DebugReviewRequiredEvent, and await a decision."""
        from orca.engine.types import DebugReviewRequiredEvent

        snapshot = await self._build_debug_review_snapshot(issue_id, worker_result)
        if snapshot is None:
            return

        ts = self.now()
        review_event = DebugReviewRequiredEvent(
            issue_id=issue_id,
            snapshot=snapshot,
            timestamp=ts,
        )
        self._state, _ = reduce(
            self._config,
            self._state,
            review_event,
            self.generate_id,
            self.now,
        )
        self.persistence.save(self._state)

        decision_event = asyncio.Event()
        decision_box: list[dict[str, Any]] = []
        self._debug_decision_events[issue_id] = (decision_event, decision_box)
        issue = self._state.issues.get(issue_id)
        state_name = issue.state if issue is not None else "?"
        logger.info(
            "Debug review pause for issue %s at state %s",
            issue_id,
            state_name,
            extra={"event": "debug_review_pause", "issue_id": issue_id, "state": state_name},
        )

        # Auto-open the review URL in the user's default browser. Opt out by
        # setting ORCA_NO_AUTO_OPEN=1 in the daemon's environment. The user
        # already chose --debug so we assume they want the UI.
        self._auto_open_review_url(issue_id)

        await decision_event.wait()

    async def _build_auto_review_snapshot(self, event: WorkerResultEvent) -> DebugReviewSnapshot | None:
        """Return a snapshot for non-debug review history when the result would be reviewable.

        The probe reducer call reuses the debug-mode validation path without
        mutating live state. If debug mode would not pause for this result
        (invalid outcome, failure retry path, etc.), normal runs should not
        record a synthetic accept either.
        """
        probe_state, probe_effects = reduce(
            self._config,
            self._state,
            event,
            self.generate_id,
            self.now,
            run_debug=True,
        )
        probe_issue = probe_state.issues.get(event.issue_id)
        if probe_effects or probe_issue is None or not probe_issue.debug_pending:
            return None
        try:
            return await self._build_debug_review_snapshot(event.issue_id, event.result)
        except Exception as exc:
            logger.warning(
                "Skipping auto review history for issue %s: failed to build snapshot: %s",
                event.issue_id,
                exc,
                extra={"event": "auto_review_snapshot_failed", "issue_id": event.issue_id},
            )
            return None

    def _auto_open_review_url(self, issue_id: str) -> None:
        """Best-effort: open the debug-review URL in the user's default browser.

        Runs in a detached thread so a slow `open` / `xdg-open` doesn't block
        the orchestrator. Silently no-ops in headless environments, when the
        daemon's browser TCP listener isn't bound, when the user opted out via
        ORCA_NO_AUTO_OPEN=1, or when webbrowser.open raises (rare on macOS,
        more common on remote Linux without DISPLAY).
        """
        import os
        import threading
        import webbrowser

        if os.environ.get("ORCA_NO_AUTO_OPEN"):
            return
        if self.repo_root is None:
            return
        from orca.daemon.lifecycle import read_browser_port

        port = read_browser_port(self.repo_root)
        if port is None:
            return

        # Derive run_id from the persistence layout: state_path is
        # <repo>/.orca-state/runs/<branch>/<workflow>/state.json
        run_dir = self.persistence.state_path.parent
        workflow = run_dir.name
        branch = run_dir.parent.name
        run_id = f"{branch}:{workflow}"
        url = f"http://localhost:{port}/debug/{run_id}/{issue_id}"

        def _open() -> None:
            try:
                webbrowser.open(url, new=2)  # new=2 → new tab if possible
            except Exception:
                return

        threading.Thread(target=_open, daemon=True).start()

    async def _reset_worktree_for_issue(self, issue_id: str) -> None:
        """Reset the worktree branch back to its state_base_commit.

        Root issues that reuse the repo's working tree directly (no isolated
        worktree under .orca-state/worktrees/) don't get reset — we don't
        touch the user's repo. For read-only workers like a preflight that
        ran a classification step, this is a clean no-op. For workers that
        DID commit, the next run sees those commits in the repo and the
        rewrite skill's new prompt decides how to proceed.
        """
        issue = self._state.issues.get(issue_id)
        if issue is None or issue.state_base_commit is None:
            logger.warning("Cannot reset worktree for issue %s: no state_base_commit", issue_id)
            return
        branch = self.branches.get(issue_id)
        if branch is None:
            return
        worktree_path = self.worktree_mgr.resolve(branch)
        if not worktree_path.exists():
            logger.info(
                "No isolated worktree for issue %s (branch=%s) — skipping reset; "
                "root issue uses the repo working tree directly",
                issue_id,
                branch,
                extra={"event": "worktree_reset_skipped_root", "issue_id": issue_id, "branch": branch},
            )
            return
        try:
            await self.worktree_mgr.reset_to(branch, issue.state_base_commit)
        except Exception as exc:
            logger.error(
                "Worktree reset failed for issue %s: %s",
                issue_id,
                exc,
                extra={"event": "worktree_reset_failed", "issue_id": issue_id},
            )
            raise

    async def restart_state(self, issue_id: str) -> None:
        """Reset the worktree and re-dispatch the worker after a modify_restart rewrite."""
        issue = self._state.issues.get(issue_id)
        if issue is None:
            raise ValueError(f"Issue {issue_id!r} not found")
        if not issue.modify_pending:
            raise ValueError(f"Issue {issue_id!r} is not in modify_pending state")

        from orca.engine.config import parse_config

        config_path = self._resolve_config_path()
        try:
            parse_config(config_path.read_text())
        except Exception as exc:
            raise ValueError(f"Workflow YAML failed validation after rewrite: {exc}") from exc

        await self._reset_worktree_for_issue(issue_id)

        issue.modify_pending = False
        issue.worker_active = True
        issue.failure_count = 0

        from orca.engine.dispatch import append_log, build_issue_context, build_result_format
        from orca.engine.types import DispatchWorkerEffect

        effect = DispatchWorkerEffect(
            issue_id=issue_id,
            issue_type=issue.type,
            state=issue.state,
            result_format=build_result_format(self._config, issue.type, issue.state),
            issue=build_issue_context(self._state, issue_id),
        )
        self._spawn_worker(effect)
        append_log(issue, self.now(), "worker_dispatched", {"state": issue.state})
        self.persistence.save(self._state)

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
                # modify_restart in debug mode leaves the issue with
                # modify_pending=true and no in-flight worker. The host (CC
                # via MCP) is expected to rewrite the prompt and call
                # orca_restart_state, which spawns a fresh worker directly
                # into _in_flight. Until that happens, sit idle — this is
                # not a deadlock, it's an external-unblock wait.
                if any(i.modify_pending for i in self._state.issues.values()):
                    await asyncio.sleep(0.5)
                    continue
                logger.warning(
                    "Deadlock detected: no tasks in flight and no pending effects. Stopping.",
                    extra={"event": "deadlock_detected"},
                )
                raise DeadlockError(f"Deadlock: root issue {root_issue_id!r} not done and no pending work")

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

                # v1: only pause for root issues. Decomposed (child) issues run
                # through without a debug pause — documented spec limitation.
                _issue_for_debug = self._state.issues.get(issue_id)
                _is_root = _issue_for_debug is not None and _issue_for_debug.decomposed_from is None

                if self.debug and isinstance(outcome, WorkerSuccess) and _is_root:
                    self._state, _ = reduce(
                        self._config,
                        self._state,
                        event,
                        self.generate_id,
                        self.now,
                        run_debug=True,
                    )
                    self.persistence.save(self._state)
                    await self._pause_for_debug_review(issue_id, outcome.result)
                    decision = self._debug_decision_events[issue_id][1][0]
                    self._debug_decision_events.pop(issue_id, None)
                    from orca.engine.types import DebugDecisionEvent

                    decision_event = DebugDecisionEvent(
                        issue_id=issue_id,
                        action=decision["action"],
                        comments=[],
                        timestamp=self.now(),
                    )
                    if decision["action"] == "restart":
                        await self._reset_worktree_for_issue(issue_id)
                    self._state, new_effects = reduce(
                        self._config,
                        self._state,
                        decision_event,
                        self.generate_id,
                        self.now,
                    )
                    self.persistence.save(self._state)
                else:
                    auto_review_snapshot = None
                    if isinstance(event, WorkerResultEvent):
                        auto_review_snapshot = await self._build_auto_review_snapshot(event)
                    self._state, new_effects = reduce(
                        self._config,
                        self._state,
                        event,
                        self.generate_id,
                        self.now,
                        auto_review_snapshot=auto_review_snapshot,
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

        capture_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await capture_task
