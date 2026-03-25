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


async def _git_branch_exists(branch_name: str, repo_root: Path) -> bool:
    """Check if a git branch exists locally."""
    proc = await asyncio.create_subprocess_exec(
        "git",
        "rev-parse",
        "--verify",
        branch_name,
        cwd=str(repo_root),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.communicate()
    return proc.returncode == 0


def resolve_config_path(repo_root: Path, workflow: str | None) -> Path:
    """Resolve the workflow config file path.

    Args:
        repo_root: Repository root directory.
        workflow: Shorthand name (e.g. "develop" -> "orca.develop.yml"), or None for "orca.yml".

    Returns:
        Resolved config file path.

    Raises:
        SystemExit: If the resolved file does not exist.
    """
    import sys

    config_name = f"orca.{workflow}.yml" if workflow else "orca.yml"
    config_path = repo_root / config_name
    if config_path.exists():
        return config_path

    available = sorted({*repo_root.glob("orca.yml"), *repo_root.glob("orca.*.yml")})
    available_str = ", ".join(p.name for p in available) if available else "(none found)"
    print(f"Error: {config_name} not found in {repo_root}. Available: {available_str}", file=sys.stderr)
    raise SystemExit(1)


def resolve_branch() -> str:
    """Detect the current git branch.

    Returns:
        Current branch name.

    Raises:
        SystemExit: If detection fails (detached HEAD, not a git repo).
    """
    import subprocess
    import sys

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        name = result.stdout.strip()
        if result.returncode != 0 or not name or name == "HEAD":
            print("Error: cannot detect current branch (detached HEAD?). Specify with -b.", file=sys.stderr)
            raise SystemExit(1)
        return name
    except FileNotFoundError:
        print("Error: git not found. Specify branch with -b.", file=sys.stderr)
        raise SystemExit(1) from None


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
    run_dir: Path,
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
        # When the root issue reuses an existing branch, the worktree dir
        # doesn't exist — result.json lives in the run directory instead.
        result_path = worktree_path / ".orca" / "result.json" if worktree_path.exists() else run_dir / "result.json"

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


async def run(task_file: Path, branch_name: str, config_path: Path, insights_enabled: bool = False) -> None:
    """Main entry point: read task file, set up state, run orchestrator."""
    repo_root = Path.cwd()

    # Read task file
    title, description = parse_task_file(task_file)

    # Load config
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

        # Clean up sessions from the previous (crashed) run
        from orca.orchestrator.session_sync import SessionManifest

        run_dir = repo_root / ".orca" / "runs" / branch_name
        manifest = SessionManifest(run_dir)
        manifest.mark_orphans_completed(_now())
        manifest.backfill_claude_session_ids()

        recovered_events, recovered_effects = _recover_effects(
            config, state, branches, worktree_mgr, run_dir, _generate_id, _now
        )

        # Feed recovered events through the reducer
        for event in recovered_events:
            state, new_effects = reduce(config, state, event, _generate_id, _now)
            initial_effects.extend(new_effects)

        initial_effects.extend(recovered_effects)
    else:
        # Fresh start
        root_issue_id = _generate_id()

        # Check if the branch already exists (e.g. user is on it).
        # If so, use repo_root directly instead of creating a worktree.
        branch_exists = await _git_branch_exists(branch_name, repo_root)
        if branch_exists:
            logger.info(
                "Branch %s already exists — using repo root as root workdir",
                branch_name,
                extra={"event": "branch_reuse", "branch": branch_name},
            )
        else:
            await worktree_mgr.create(
                issue_id=root_issue_id,
                branch_name=branch_name,
                parent_branch="HEAD",
            )

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
    """CLI entry point: orca <task_file> [-w workflow] [--headless] [--insights]."""
    parser = argparse.ArgumentParser(prog="orca", description="Orca orchestrator CLI")
    parser.add_argument("task_file", type=Path, help="Path to the task file")
    parser.add_argument(
        "-w", "--workflow", type=str, default=None, help="Workflow name shorthand (e.g. 'develop' -> orca.develop.yml)"
    )
    parser.add_argument("--headless", action="store_true", help="Run without TUI (headless mode)")
    parser.add_argument("--insights", action="store_true", help="Enable insights agent for progress monitoring")

    args = parser.parse_args()

    repo_root = Path.cwd()
    config_path = resolve_config_path(repo_root, args.workflow)
    branch_name = resolve_branch()

    if args.headless:
        asyncio.run(run(args.task_file, branch_name, config_path, insights_enabled=args.insights))
    else:
        import threading

        run_error: BaseException | None = None

        def run_orchestrator() -> None:
            nonlocal run_error
            try:
                asyncio.run(run(args.task_file, branch_name, config_path, insights_enabled=args.insights))
            except BaseException as e:
                run_error = e

        thread = threading.Thread(target=run_orchestrator, daemon=True)
        thread.start()

        try:
            from orca.tui.app import OrcaApp
        except ImportError:
            print("Error: textual is not installed. Install with: uv pip install 'orca[tui]'")
            raise SystemExit(1) from None

        run_dir = repo_root / ".orca" / "runs" / branch_name
        config = parse_config(config_path.read_text())

        app = OrcaApp(run_dir=run_dir, branch_name=branch_name, config=config, insights_enabled=args.insights)
        app.run()

        # Surface orchestrator errors before exiting
        if run_error is not None:
            import sys
            import traceback

            print("\nOrchestrator error:", file=sys.stderr)
            traceback.print_exception(type(run_error), run_error, run_error.__traceback__, file=sys.stderr)

        # Reset terminal before force-killing — SIGTERM would leave escape
        # sequences (focus reporting, alternate screen) enabled.
        import sys

        sys.stdout.write("\x1b[?1000l")  # disable normal mouse tracking
        sys.stdout.write("\x1b[?1002l")  # disable button-event mouse tracking
        sys.stdout.write("\x1b[?1003l")  # disable any-event mouse tracking
        sys.stdout.write("\x1b[?1006l")  # disable SGR mouse reporting
        sys.stdout.write("\x1b[?1004l")  # disable focus reporting
        sys.stdout.write("\x1b[?1049l")  # exit alternate screen buffer
        sys.stdout.write("\x1b[?25h")  # show cursor
        sys.stdout.flush()

        # Force exit to kill orchestrator thread and any subprocesses
        import os
        import signal

        os.kill(os.getpid(), signal.SIGTERM)
