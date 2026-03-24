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
    """Recover in-flight workers and retry exhausted-retry issues on resume.

    Returns:
        recovered_events: WorkerResultEvents from valid result files.
        recovered_effects: DispatchWorkerEffects for re-dispatch.
    """
    recovered_events: list[WorkerResultEvent] = []
    recovered_effects: list[DispatchWorkerEffect] = []

    for issue_id, issue in state.issues.items():
        state_def = config.states.get(issue.state)
        if state_def is None or state_def.terminal:
            continue

        if issue.worker_active:
            # In-flight when orchestrator stopped — check for result or re-dispatch
            pass
        elif issue.failure_count > 0:
            # Retries exhausted — reset and re-dispatch
            logger.info(
                "Retrying previously exhausted issue %s (failure_count=%d)",
                issue_id,
                issue.failure_count,
                extra={"event": "retry_exhausted", "issue_id": issue_id},
            )
            issue.failure_count = 0
            issue.worker_active = True
        else:
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


async def run(task_file: Path, branch_name: str, insights_enabled: bool = False) -> None:
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

        # Mark orphan sessions from the previous (crashed) run as completed
        from orca.orchestrator.session_sync import SessionManifest

        run_dir = repo_root / ".orca" / "runs" / branch_name
        SessionManifest(run_dir).mark_orphans_completed(_now())

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
    insights_worker = worker if insights_enabled else None

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
        worktree_mgr=worktree_mgr,
        repo_root=repo_root,
        session_sync=session_sync,
        insights_worker=insights_worker,
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
    run_parser.add_argument("--headless", action="store_true", help="Run without TUI (headless mode)")
    run_parser.add_argument("--insights", action="store_true", help="Enable insights agent for progress monitoring")

    watch_parser = subparsers.add_parser("watch", help="Watch orchestrator state in a TUI dashboard")
    watch_parser.add_argument("branch_name", type=str, help="Git branch name of the run to watch")

    args = parser.parse_args()

    if args.command == "run":
        if args.headless:
            asyncio.run(run(args.task_file, args.branch_name, insights_enabled=args.insights))
        else:
            import threading

            run_error: BaseException | None = None

            def run_orchestrator() -> None:
                nonlocal run_error
                try:
                    asyncio.run(run(args.task_file, args.branch_name, insights_enabled=args.insights))
                except BaseException as e:
                    run_error = e

            thread = threading.Thread(target=run_orchestrator, daemon=True)
            thread.start()

            try:
                from orca.tui.app import OrcaApp
            except ImportError:
                print("Error: textual is not installed. Install with: uv pip install 'orca[tui]'")
                raise SystemExit(1) from None

            repo_root = Path.cwd()
            run_dir = repo_root / ".orca" / "runs" / args.branch_name

            config = None
            config_path = repo_root / "orca.yml"
            if config_path.exists():
                config = parse_config(config_path.read_text())

            app = OrcaApp(run_dir=run_dir, branch_name=args.branch_name, config=config)
            app.run()

            # TUI closed — force exit to kill orchestrator thread and any subprocesses
            import os
            import signal

            os.kill(os.getpid(), signal.SIGTERM)
    elif args.command == "watch":
        try:
            from orca.tui.app import OrcaApp
        except ImportError as e:
            print("Error: textual is not installed. Install with: uv pip install 'orca[tui]'")
            raise SystemExit(1) from e

        repo_root = Path.cwd()
        run_dir = repo_root / ".orca" / "runs" / args.branch_name

        if not run_dir.exists():
            print(f"Error: no run found at {run_dir}")
            raise SystemExit(1)

        # Load config for terminal state detection
        config = None
        config_path = repo_root / "orca.yml"
        if config_path.exists():
            config = parse_config(config_path.read_text())

        app = OrcaApp(run_dir=run_dir, branch_name=args.branch_name, config=config)
        app.run()
