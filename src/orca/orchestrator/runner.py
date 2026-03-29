from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml

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
from orca.orchestrator.config_types import SlackConfig, parse_integrations, parse_orchestrator_config
from orca.orchestrator.log import setup_logging
from orca.orchestrator.persistence import Persistence
from orca.orchestrator.validation import validate_result
from orca.orchestrator.worker import KIND_REGISTRY, CliAgentWorker
from orca.orchestrator.worktree import WorktreeManager

logger = logging.getLogger(__name__)


def parse_task_file(path: Path) -> dict[str, Any]:
    """Read a task file and return issue fields as a dict.

    Supports two formats:
    - YAML: if content parses as a YAML dict, return its fields directly.
      Optional ``---`` frontmatter delimiters are stripped before parsing.
    - Plain text (legacy): first line is the title, remainder is the description.
    """
    text = path.read_text()

    # Strip optional frontmatter delimiters
    stripped = text.strip()
    if stripped.startswith("---"):
        body = stripped.split("\n", 1)[1] if "\n" in stripped else ""
        # Remove closing delimiter if present
        if "\n---" in body:
            body = body[: body.index("\n---")]
        parsed = yaml.safe_load(body)
    else:
        parsed = yaml.safe_load(text)

    if isinstance(parsed, dict):
        return {k: v for k, v in parsed.items() if v is not None}

    # Legacy plain-text fallback: first line = title, rest = description
    lines = text.split("\n", 1)
    title = lines[0].strip()
    description = lines[1].strip() if len(lines) > 1 else ""
    return {"title": title, "description": description}


def _generate_id() -> str:
    return str(uuid4())


def _now() -> str:
    return datetime.now(UTC).isoformat()


def resolve_base_ref(cli_base: str | None, config_base: str) -> str:
    """Resolve the base ref for branch creation.

    Priority: CLI --base > config base_branch > "origin/main" (config default).
    """
    if cli_base is not None:
        return cli_base
    return config_base


async def _git_create_branch(branch_name: str, base_ref: str, repo_root: Path) -> None:
    """Create a git branch from a base ref."""
    proc = await asyncio.create_subprocess_exec(
        "git",
        "branch",
        branch_name,
        base_ref,
        cwd=str(repo_root),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        msg = f"Failed to create branch '{branch_name}' from '{base_ref}': {stderr.decode()}"
        raise RuntimeError(msg)


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
        type_def = config.types.get(issue.type)
        if type_def is None:
            continue
        state_def = type_def.states.get(issue.state)
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

        result_format = build_result_format(config, issue.type, issue.state)
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
                    issue_type=issue.type,
                    state=issue.state,
                    result_format=result_format,
                    issue=issue_context,
                )
            )

    return recovered_events, recovered_effects


async def _start_slack_mcp_server(slack_config: SlackConfig) -> tuple[asyncio.subprocess.Process, str]:
    """Start the slack-hitl MCP server subprocess, return (process, sse_url)."""
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "orca.mcp_servers.slack_hitl.server",
        "--bot-token",
        slack_config.bot_token,
        "--app-token",
        slack_config.app_token,
        "--port",
        "0",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    assert proc.stdout is not None
    line = await asyncio.wait_for(proc.stdout.readline(), timeout=30)
    port = int(line.decode().strip())
    return proc, f"http://127.0.0.1:{port}/sse"


async def run(
    task_file: Path,
    branch_name: str,
    config_path: Path,
    base_ref: str | None = None,
    insights_enabled: bool = False,
    hot_sessions: set[str] | None = None,
    session_log_paths: dict[str, str] | None = None,
    insights_state: dict[str, str] | None = None,
    workflow: str = "default",
    max_hops: int | None = None,
    max_retries: int | None = None,
) -> None:
    """Main entry point: read task file, set up state, run orchestrator."""
    repo_root = Path.cwd()

    # Read task file
    fields = parse_task_file(task_file)

    # Load config
    config = parse_config(config_path.read_text())
    if max_hops is not None:
        object.__setattr__(config, "max_hops", max_hops)
    if max_retries is not None:
        object.__setattr__(config, "max_worker_retries", max_retries)
    raw_config: dict[str, Any] = yaml.safe_load(config_path.read_text())
    integrations = parse_integrations(raw_config.get("integrations"))

    # Set up run directory and persistence
    run_dir = repo_root / ".orca" / "runs" / branch_name / workflow
    persistence = Persistence(repo_root, branch_name, workflow)
    branches = BranchMap(repo_root, branch_name, workflow)
    worktree_mgr = WorktreeManager(repo_root, branch_name)

    log_path = run_dir / "orca.log.jsonl"
    setup_logging(log_path)

    initial_effects: list[Effect] = []

    if persistence.exists():
        # Resume: load state and branches, recover effects
        state = persistence.load()
        if state is None:
            msg = "Failed to load state from persistence"
            raise RuntimeError(msg)
        branches.load()

        # Reset hop_count and failure_count on non-terminal issues so
        # CLI limits (--max-hops, --max-retries) apply fresh on re-run.
        for issue in state.issues.values():
            type_def = config.types.get(issue.type)
            if type_def and issue.state in type_def.states and type_def.states[issue.state].terminal:
                continue
            issue.hop_count = 0
            issue.failure_count = 0

        logger.info(
            "Run resumed",
            extra={"event": "run_resumed", "branch": branch_name},
        )

        # Clean up sessions from the previous (crashed) run
        from orca.orchestrator.session_sync import SessionManifest

        manifest = SessionManifest(run_dir)
        manifest.mark_orphans_completed(_now())

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

        if base_ref is not None:
            # -b mode: create integration branch and worktree
            if not await _git_branch_exists(branch_name, repo_root):
                await _git_create_branch(branch_name, base_ref, repo_root)
            await worktree_mgr.create(
                issue_id=root_issue_id,
                branch_name=branch_name,
                parent_branch=base_ref,
            )
        else:
            # Legacy mode: use repo root if branch already checked out
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
                    parent_branch=branch_name,
                )

        # Create initial state and event
        state = State(issues={}, worker_queues={})
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

    # Start Slack HITL MCP server if configured
    slack_mcp_proc: asyncio.subprocess.Process | None = None
    slack_mcp_url: str | None = None
    if integrations.slack is not None:
        slack_mcp_proc, slack_mcp_url = await _start_slack_mcp_server(integrations.slack)
        logger.info("Slack HITL MCP server started", extra={"event": "slack_mcp_started", "url": slack_mcp_url})

    # Set up workers, session sync, and orchestrator
    workers = {name: CliAgentWorker(repo_root, kc) for name, kc in KIND_REGISTRY.items()}

    from orca.orchestrator.orchestrator import Orchestrator
    from orca.orchestrator.session_sync import SessionSync

    session_sync = SessionSync(run_dir=run_dir)

    orchestrator = Orchestrator(
        config=config,
        state=state,
        root_branch=branch_name,
        persistence=persistence,
        branches=branches,
        workers=workers,
        generate_id=_generate_id,
        now=_now,
        worktree_mgr=worktree_mgr,
        repo_root=repo_root,
        session_sync=session_sync,
        insights_enabled=insights_enabled,
        hot_sessions=hot_sessions,
        session_log_paths=session_log_paths,
        insights_state=insights_state,
        slack_mcp_url=slack_mcp_url,
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
    finally:
        if slack_mcp_proc is not None:
            slack_mcp_proc.terminate()
            await slack_mcp_proc.wait()

    logger.info(
        "Run completed",
        extra={"event": "run_completed", "branch": branch_name, "root_issue_id": root_issue_id},
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(prog="orca", description="Orca orchestrator CLI")
    parser.add_argument("task_file", type=Path, help="Path to the task file")
    parser.add_argument(
        "-w", "--workflow", type=str, default=None, help="Workflow name shorthand (e.g. 'develop' -> orca.develop.yml)"
    )
    parser.add_argument("-b", "--branch", type=str, default=None, help="Integration branch name for this run")
    parser.add_argument(
        "--base", type=str, default=None, help="Base ref to branch from (default: config or origin/main)"
    )
    parser.add_argument("--headless", action="store_true", help="Run without TUI (headless mode)")
    parser.add_argument("--insights", action="store_true", help="Enable insights agent for progress monitoring")
    parser.add_argument("--max-hops", type=int, default=10, help="Maximum state transitions per issue (default: 10)")
    parser.add_argument(
        "--max-retries", type=int, default=3, help="Maximum worker crash retries per issue (default: 3)"
    )
    return parser


def main() -> None:
    """CLI entry point: orca <task_file> [-b branch] [--base ref] [-w workflow] [--headless] [--insights]."""
    parser = build_parser()
    args = parser.parse_args()

    repo_root = Path.cwd()
    config_path = resolve_config_path(repo_root, args.workflow)

    # Parse orchestrator config for base_branch default
    raw_config: dict[str, Any] = yaml.safe_load(config_path.read_text())
    orch_config = parse_orchestrator_config(raw_config)

    if args.base is not None and args.branch is None:
        print("Error: --base requires -b/--branch", file=sys.stderr)
        raise SystemExit(1)

    if args.branch is not None:
        branch_name = args.branch
        base_ref: str | None = resolve_base_ref(args.base, orch_config.base_branch)
    else:
        branch_name = resolve_branch()
        base_ref = None

    workflow = args.workflow or "default"

    # Validate task file exists before starting
    if not args.task_file.exists():
        print(f"Error: task file not found: {args.task_file}")
        raise SystemExit(1)

    if args.headless:
        asyncio.run(
            run(
                args.task_file,
                branch_name,
                config_path,
                base_ref=base_ref,
                insights_enabled=args.insights,
                workflow=workflow,
                max_hops=args.max_hops,
                max_retries=args.max_retries,
            )
        )
    else:
        # Shared state between orchestrator (daemon thread) and TUI (main thread).
        # hot_sessions: TUI writes which session to capture frequently
        # session_log_paths: orchestrator writes log file paths for each worker
        hot_sessions: set[str] = set()
        session_log_paths: dict[str, str] = {}
        insights_state: dict[str, str] = {}

        run_error: BaseException | None = None

        def run_orchestrator() -> None:
            nonlocal run_error
            try:
                asyncio.run(
                    run(
                        args.task_file,
                        branch_name,
                        config_path,
                        base_ref=base_ref,
                        insights_enabled=args.insights,
                        hot_sessions=hot_sessions,
                        session_log_paths=session_log_paths,
                        insights_state=insights_state,
                        workflow=workflow,
                        max_hops=args.max_hops,
                        max_retries=args.max_retries,
                    )
                )
            except BaseException as e:
                run_error = e

        import threading

        thread = threading.Thread(target=run_orchestrator, daemon=True)
        thread.start()

        try:
            from orca.tui.app import OrcaApp
        except ImportError:
            print("Error: textual is not installed. Install with: uv pip install 'orca[tui]'")
            raise SystemExit(1) from None

        run_dir = repo_root / ".orca" / "runs" / branch_name / workflow
        config = parse_config(config_path.read_text())

        app = OrcaApp(
            run_dir=run_dir,
            branch_name=branch_name,
            config=config,
            insights_enabled=args.insights,
            hot_sessions=hot_sessions,
            session_log_paths=session_log_paths,
            insights_state=insights_state,
        )
        app.run()

        # Surface orchestrator errors before exiting
        if run_error is not None:
            import traceback

            print("\nOrchestrator error:", file=sys.stderr)
            traceback.print_exception(type(run_error), run_error, run_error.__traceback__, file=sys.stderr)

        # Reset terminal escape sequences that Textual enables.
        # Write directly to fd to bypass any buffering, then force exit.
        import os

        reset = (
            "\x1b[?1000l"  # disable normal mouse tracking
            "\x1b[?1002l"  # disable button-event mouse tracking
            "\x1b[?1003l"  # disable any-event mouse tracking
            "\x1b[?1006l"  # disable SGR mouse reporting
            "\x1b[?1004l"  # disable focus reporting
            "\x1b[?1049l"  # exit alternate screen buffer
            "\x1b[?25h"  # show cursor
        )
        with contextlib.suppress(OSError):
            os.write(1, reset.encode())

        # Force exit to kill orchestrator thread and any subprocesses.
        # os._exit skips cleanup but guarantees immediate termination
        # after the terminal reset bytes have been written to the fd.
        os._exit(0)
