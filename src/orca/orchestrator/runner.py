from __future__ import annotations

import argparse
import asyncio
import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from orca.engine.config import parse_config
from orca.engine.dispatch import build_issue_context, build_result_format
from orca.engine.reducer import reduce
from orca.engine.types import (
    CreateEvent,
    DispatchWorkerEffect,
    Effect,
    State,
    StateMachineConfig,
    WorkerResultEvent,
)
from orca.orchestrator.branches import BranchMap
from orca.orchestrator.log import setup_logging
from orca.orchestrator.persistence import Persistence
from orca.orchestrator.validation import validate_result
from orca.orchestrator.worker import ClaudeCodeWorker
from orca.orchestrator.worktree import WorktreeManager

logger = logging.getLogger(__name__)


def parse_task_file(path: Path) -> tuple[str, str]:
    """Read a task file and return (title, description).

    The first line is the title; the remainder (stripped) is the description.
    All values have leading/trailing whitespace removed.
    """
    text = path.read_text()
    lines = text.split("\n", 1)
    title = lines[0].strip()
    description = lines[1].strip() if len(lines) > 1 else ""
    return title, description


def _generate_id() -> str:
    return str(uuid4())


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _find_root_issue(state: State) -> str:
    """Find the issue with decomposed_from is None (the root issue)."""
    for issue_id, issue in state.issues.items():
        if issue.decomposed_from is None:
            return issue_id
    msg = "No root issue found in state"
    raise ValueError(msg)


def _recover_effects(
    config: StateMachineConfig,
    state: State,
    branches: BranchMap,
    worktree_mgr: WorktreeManager,
    repo_root: Path,
    generate_id: Callable[[], str],
    now: Callable[[], str],
) -> tuple[list[WorkerResultEvent], list[DispatchWorkerEffect]]:
    """For issues with worker_active=True, check for existing result files.

    Returns:
        recovered_events: WorkerResultEvents from valid result files.
        recovered_effects: DispatchWorkerEffects for re-dispatch when no valid result.
    """
    recovered_events: list[WorkerResultEvent] = []
    recovered_effects: list[DispatchWorkerEffect] = []

    for issue_id, issue in state.issues.items():
        if not issue.worker_active:
            continue

        branch = branches.get(issue_id)
        if branch is None:
            branch = issue_id  # fallback

        worktree_path = worktree_mgr.resolve(branch)
        result_path = worktree_path / ".orca" / "result.json"

        result_format = build_result_format(config, issue.state)
        issue_context = build_issue_context(state, issue_id)

        # Try to read and validate the result file
        result_valid = False
        if result_path.exists():
            try:
                result = json.loads(result_path.read_text())
                error = validate_result(result, result_format)
                if error is None:
                    recovered_events.append(
                        WorkerResultEvent(
                            issue_id=issue_id,
                            result=result,
                            timestamp=now(),
                        )
                    )
                    result_valid = True
            except (json.JSONDecodeError, OSError):
                pass

        if not result_valid:
            recovered_effects.append(
                DispatchWorkerEffect(
                    issue_id=issue_id,
                    state=issue.state,
                    result_format=result_format,
                    issue=issue_context,
                )
            )

    return recovered_events, recovered_effects


async def run(task_file: Path, branch_name: str) -> None:
    """Main entry point: read task file, set up state, run orchestrator."""
    repo_root = Path.cwd()

    # Read task file
    title, description = parse_task_file(task_file)

    # Load config
    config_path = repo_root / "orca.yml"
    config = parse_config(config_path.read_text())

    # Set up Persistence and BranchMap
    persistence = Persistence(repo_root, branch_name)
    branches = BranchMap(repo_root, branch_name)
    worktree_mgr = WorktreeManager(repo_root, branch_name)

    log_path = repo_root / ".orca" / "runs" / branch_name / "orca.log.jsonl"
    setup_logging(log_path)

    initial_effects: list[Effect] = []

    if persistence.exists():
        # Resume: load state and branches, recover effects
        state = persistence.load()
        if state is None:
            msg = "Failed to load state from persistence"
            raise RuntimeError(msg)
        branches.load()

        logger.info(
            "Run resumed",
            extra={"event": "run_resumed", "branch": branch_name},
        )

        recovered_events, recovered_effects = _recover_effects(
            config, state, branches, worktree_mgr, repo_root, _generate_id, _now
        )

        # Feed recovered events through the reducer
        for event in recovered_events:
            state, new_effects = reduce(config, state, event, _generate_id, _now)
            initial_effects.extend(new_effects)

        initial_effects.extend(recovered_effects)
    else:
        # Fresh start — worktree creation also creates the branch via -b
        # Create root worktree
        root_issue_id = _generate_id()
        worktree_path = await worktree_mgr.create(
            issue_id=root_issue_id,
            branch_name=branch_name,
            parent_branch="HEAD",
        )
        _ = worktree_path  # worktree_path used internally by WorktreeManager

        # Create initial state and event
        state = State(issues={}, worker_queues={})
        fields = {"title": title, "description": description}
        create_event = CreateEvent(
            issue_id=root_issue_id,
            fields=fields,
            timestamp=_now(),
        )
        state, initial_effects = reduce(config, state, create_event, _generate_id, _now)

        # Map root issue to branch, save both
        branches.set(root_issue_id, branch_name)
        branches.save()
        persistence.save(state)

        logger.info(
            "Run started",
            extra={
                "event": "run_started",
                "branch": branch_name,
                "task_file": str(task_file),
                "root_issue_id": root_issue_id,
            },
        )

    # Find root issue ID
    root_issue_id = _find_root_issue(state)

    # Set up worker, session sync, and orchestrator
    worker = ClaudeCodeWorker(repo_root)

    from orca.orchestrator.orchestrator import Orchestrator
    from orca.orchestrator.session_sync import SessionSync

    run_dir = repo_root / ".orca" / "runs" / branch_name
    transcripts_dir = repo_root / ".orca" / "transcripts"
    session_sync = SessionSync(run_dir=run_dir, transcripts_dir=transcripts_dir)

    orchestrator = Orchestrator(
        config=config,
        state=state,
        root_branch=branch_name,
        persistence=persistence,
        branches=branches,
        workers={"claude-code": worker},
        generate_id=_generate_id,
        now=_now,
        worktree_resolver=lambda issue_id: worktree_mgr.resolve(branches.get(issue_id) or issue_id),
        repo_root=repo_root,
        session_sync=session_sync,
    )

    try:
        await orchestrator.run(root_issue_id, initial_effects)
    except Exception:
        logger.error(
            "Run failed",
            extra={"event": "run_failed", "branch": branch_name},
            exc_info=True,
        )
        raise

    logger.info(
        "Run completed",
        extra={"event": "run_completed", "branch": branch_name, "root_issue_id": root_issue_id},
    )


def main() -> None:
    """CLI entry point: orca run <task_file> <branch_name>."""
    parser = argparse.ArgumentParser(prog="orca", description="Orca orchestrator CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run the orchestrator with a task file")
    run_parser.add_argument("task_file", type=Path, help="Path to the task file")
    run_parser.add_argument("branch_name", type=str, help="Git branch name for this run")

    args = parser.parse_args()

    if args.command == "run":
        asyncio.run(run(args.task_file, args.branch_name))
