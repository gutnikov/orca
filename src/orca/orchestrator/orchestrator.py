from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

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
from orca.orchestrator.insights import (
    gather_transcripts,
    serialize_state_for_insights,
    truncate_insights_so_far,
)
from orca.orchestrator.persistence import Persistence
from orca.orchestrator.session_sync import SessionSync
from orca.orchestrator.template import render_insights_prompt
from orca.orchestrator.worker import ClaudeCodeWorker, Worker, WorkerFailure, WorkerOutcome, WorkerSuccess
from orca.orchestrator.worktree import WorktreeManager

logger = logging.getLogger(__name__)


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
        session_sync: SessionSync | None = None,
        insights_worker: ClaudeCodeWorker | None = None,
        insights_interval: float = 300.0,
        insights_timeout: float = 120.0,
    ) -> None:
        self.config = config
        self.state = state
        self.root_branch = root_branch
        self.persistence = persistence
        self.branches = branches
        self.workers: Mapping[str, Worker] = workers
        self.generate_id = generate_id
        self.now = now
        self.worktree_mgr = worktree_mgr
        self.repo_root = repo_root
        self._session_sync = session_sync
        self._insights_worker = insights_worker
        self._insights_interval = insights_interval
        self._insights_timeout = insights_timeout
        self._insights_in_flight = False
        # Maps asyncio.Task -> (issue_id, tracking_id)
        self._in_flight: dict[asyncio.Task[WorkerOutcome], tuple[str, str]] = {}
        # Track used branch slugs to avoid collisions
        self._used_slugs: set[str] = set()
        for branch in self.branches.values():
            self._used_slugs.add(branch)

    def _is_terminal(self, issue_id: str) -> bool:
        """Return True if the issue's current state is terminal in config."""
        issue = self.state.issues.get(issue_id)
        if issue is None:
            return False
        state_def = self.config.states.get(issue.state)
        if state_def is None:
            return False
        return state_def.terminal

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
        issue = self.state.issues[issue_id]
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
        state_def = self.config.states.get(effect.state)
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

        # Exponential backoff for retries: 5s, 10s, 20s, 40s, ...
        issue = self.state.issues.get(effect.issue_id)
        failures = issue.failure_count if issue else 0
        backoff = 5.0 * (2**failures) if failures > 0 else 0.0

        task: asyncio.Task[WorkerOutcome] = asyncio.create_task(
            self._run_worker_with_backoff(effect, worker, state_def.worker.prompt, backoff, tracking_id)
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
        issue = self.state.issues.get(issue_id)
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
        return await self._run_worker(effect, worker, prompt_template, tracking_id)

    async def _run_worker(
        self, effect: DispatchWorkerEffect, worker: Worker, prompt_template: str, tracking_id: str
    ) -> WorkerOutcome:
        """Create worktree if needed, then execute the worker."""
        workdir = await self._ensure_worktree(effect.issue_id)

        # Update the manifest with the real worktree path (may differ from the
        # preliminary path recorded in _spawn_worker when the branch didn't exist yet).
        if self._session_sync is not None:
            self._session_sync.manifest.update_worktree_path(tracking_id, str(workdir))
        result_path = workdir / ".orca" / "result.json"

        prompt_path: Path | None = None
        if self.repo_root is not None:
            prompt_path = self.repo_root / prompt_template

        # Enrich issue context with base_branch for the prompt template
        base_branch = self._resolve_base_branch(effect.issue_id)
        enriched_effect = DispatchWorkerEffect(
            issue_id=effect.issue_id,
            state=effect.state,
            result_format=effect.result_format,
            issue={**effect.issue, "base_branch": base_branch},
        )

        return await worker.execute(enriched_effect, workdir, result_path, prompt_path)

    def _process_retry_signals(self, pending: list[DispatchWorkerEffect]) -> bool:
        """Check for retry signal files from the TUI. Returns True if any retries were queued."""
        retry_dir = self.persistence.state_path.parent / "retry"
        if not retry_dir.exists():
            return False

        retried = False
        for signal_file in retry_dir.iterdir():
            issue_id = signal_file.name
            signal_file.unlink()

            issue = self.state.issues.get(issue_id)
            if issue is None:
                continue
            if issue.worker_active:
                continue  # already running
            if issue.failure_count == 0:
                continue  # not failed

            # Reset failure count and re-dispatch
            issue.failure_count = 0
            issue.worker_active = True

            state_def = self.config.states.get(issue.state)
            if state_def is None or state_def.worker is None:
                continue

            from orca.engine.dispatch import build_issue_context, build_result_format

            pending.append(
                DispatchWorkerEffect(
                    issue_id=issue_id,
                    state=issue.state,
                    result_format=build_result_format(self.config, issue.state),
                    issue=build_issue_context(self.state, issue_id),
                )
            )
            self.persistence.save(self.state)
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

    async def _sync_sessions_loop(self) -> None:
        """Periodically render session transcripts to markdown."""
        while True:
            await asyncio.sleep(60)
            if self._session_sync is not None:
                await asyncio.to_thread(self._session_sync.sync)

    async def _run_insights_once(self, root_issue_id: str) -> None:
        """Run a single insights worker invocation."""
        if self.repo_root is None or self._insights_worker is None:
            return

        run_dir = self.persistence.state_path.parent
        insights_path = run_dir / "insights.md"
        template_path = Path(__file__).parent / "prompts" / "insights.md.j2"
        transcripts_dir = self.repo_root / ".orca" / "transcripts"

        is_final = self._is_terminal(root_issue_id)
        mode = "final" if is_final else "incremental"

        state_data = serialize_state_for_insights(self.state)
        sessions = self._session_sync.manifest.read() if self._session_sync else []
        transcripts = gather_transcripts(transcripts_dir, sessions) if transcripts_dir.exists() else {}
        insights_so_far = truncate_insights_so_far(insights_path.read_text()) if insights_path.exists() else ""

        prompt = render_insights_prompt(
            template_path=template_path,
            state=state_data,
            transcripts=transcripts,
            mode=mode,
            insights_so_far=insights_so_far,
            output_path=str(insights_path),
        )

        tracking_id = str(uuid4())
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
        session_log_dir = self.repo_root / ".orca" / "sessions"
        session_log_dir.mkdir(parents=True, exist_ok=True)
        session_log_path = session_log_dir / f"insights-{timestamp}.jsonl"

        if self._session_sync is not None:
            self._session_sync.manifest.append(
                issue_id="__insights__",
                state=mode,
                session_id=tracking_id,
                worktree_path=str(self.repo_root),
                started_at=self.now(),
            )

        self._insights_in_flight = True
        try:
            outcome = await self._insights_worker.execute_raw(
                prompt, self.repo_root, session_log_path, timeout=self._insights_timeout
            )

            if self._session_sync is not None:
                self._session_sync.manifest.mark_completed(tracking_id, self.now())

            if isinstance(outcome, WorkerFailure):
                logger.warning("Insights worker failed: %s", outcome.error)
            else:
                logger.info("Insights worker completed successfully")
        except Exception:
            logger.exception("Insights worker raised exception")
        finally:
            self._insights_in_flight = False

    async def _insights_loop(self, root_issue_id: str) -> None:
        """Periodically run the insights agent to analyze progress."""
        while True:
            await asyncio.sleep(self._insights_interval)

            if self._insights_in_flight:
                logger.debug("Insights worker still in flight, skipping tick")
                continue

            await self._run_insights_once(root_issue_id)

            if self._is_terminal(root_issue_id):
                break

    async def run(self, root_issue_id: str, initial_effects: list[Effect]) -> None:
        """Drive the orchestrator event loop until the root issue is terminal."""
        # Start background session sync
        sync_task: asyncio.Task[None] | None = None
        if self._session_sync is not None:
            sync_task = asyncio.create_task(self._sync_sessions_loop())

        insights_task: asyncio.Task[None] | None = None
        if self._insights_worker is not None:
            insights_task = asyncio.create_task(self._insights_loop(root_issue_id))

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
                    self._session_sync.manifest.mark_completed(tracking_id, ts, claude_session_id=outcome.session_id)

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

                old_issues = set(self.state.issues.keys())
                old_issue_state = self.state.issues[issue_id].state if issue_id in self.state.issues else None

                self.state, new_effects = reduce(
                    self.config,
                    self.state,
                    event,
                    self.generate_id,
                    self.now,
                )

                self.persistence.save(self.state)

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
                new_issue_state = self.state.issues[issue_id].state if issue_id in self.state.issues else None
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
                new_issues = set(self.state.issues.keys()) - old_issues
                for new_id in new_issues:
                    new_issue = self.state.issues[new_id]
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

        # Stop background sync and do a final sync
        if sync_task is not None:
            sync_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await sync_task

        if insights_task is not None:
            insights_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await insights_task

        if self._session_sync is not None:
            await asyncio.to_thread(self._session_sync.sync)

        if self._insights_worker is not None and self._is_terminal(root_issue_id):
            try:
                await asyncio.wait_for(self._run_insights_once(root_issue_id), timeout=self._insights_timeout)
            except TimeoutError:
                logger.warning("Final insights summary timed out")
            except Exception:
                logger.exception("Final insights summary failed")
