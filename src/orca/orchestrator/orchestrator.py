from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable, Mapping
from pathlib import Path

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
from orca.orchestrator.session_sync import SessionSync
from orca.orchestrator.worker import Worker, WorkerFailure, WorkerOutcome, WorkerSuccess

logger = logging.getLogger(__name__)


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
        worktree_resolver: Callable[[str], Path],
        repo_root: Path | None = None,
        session_sync: SessionSync | None = None,
    ) -> None:
        self.config = config
        self.state = state
        self.root_branch = root_branch
        self.persistence = persistence
        self.branches = branches
        self.workers: Mapping[str, Worker] = workers
        self.generate_id = generate_id
        self.now = now
        self.worktree_resolver = worktree_resolver
        self.repo_root = repo_root
        self._session_sync = session_sync
        # Maps asyncio.Task -> issue_id
        self._in_flight: dict[asyncio.Task[WorkerOutcome], str] = {}

    def _is_terminal(self, issue_id: str) -> bool:
        """Return True if the issue's current state is terminal in config."""
        issue = self.state.issues.get(issue_id)
        if issue is None:
            return False
        state_def = self.config.states.get(issue.state)
        if state_def is None:
            return False
        return state_def.terminal

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

        workdir = self.worktree_resolver(effect.issue_id)
        result_path = workdir / ".orca" / "result.json"

        prompt_path: Path | None = None
        if self.repo_root is not None:
            prompt_path = self.repo_root / state_def.worker.prompt

        task: asyncio.Task[WorkerOutcome] = asyncio.create_task(
            worker.execute(effect, workdir, result_path, prompt_path)
        )
        self._in_flight[task] = effect.issue_id
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
            await asyncio.sleep(180)
            if self._session_sync is not None:
                await asyncio.to_thread(self._session_sync.sync)

    async def run(self, root_issue_id: str, initial_effects: list[Effect]) -> None:
        """Drive the orchestrator event loop until the root issue is terminal."""
        # Start background session sync
        sync_task: asyncio.Task[None] | None = None
        if self._session_sync is not None:
            sync_task = asyncio.create_task(self._sync_sessions_loop())

        pending: list[DispatchWorkerEffect] = []
        self._route_effects(initial_effects, pending)

        while not self._is_terminal(root_issue_id):
            # Spawn all pending dispatch effects
            for effect in pending:
                self._spawn_worker(effect)
            pending.clear()

            # Deadlock protection: nothing running and nothing pending
            if not self._in_flight:
                logger.warning(
                    "Deadlock detected: no tasks in flight and no pending effects. Stopping.",
                    extra={"event": "deadlock_detected"},
                )
                break

            # Wait for at least one task to complete
            done, _ = await asyncio.wait(
                list(self._in_flight.keys()),
                return_when=asyncio.FIRST_COMPLETED,
            )

            for task in done:
                issue_id = self._in_flight.pop(task)
                try:
                    outcome: WorkerOutcome = task.result()
                except Exception as exc:
                    # Treat unexpected exceptions as worker failures
                    outcome = WorkerFailure(error=f"task raised exception: {exc}")

                ts = self.now()

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

                # Record session in manifest for transcript rendering
                if self._session_sync is not None and outcome.session_id is not None:
                    workdir = self.worktree_resolver(issue_id)
                    self._session_sync.manifest.append(
                        issue_id=issue_id,
                        state=old_issue_state or "unknown",
                        session_id=outcome.session_id,
                        worktree_path=str(workdir),
                        started_at=ts,
                    )

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
        if self._session_sync is not None:
            await asyncio.to_thread(self._session_sync.sync)
