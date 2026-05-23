"""Top-level CLI dispatcher for orca."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _version_string() -> str:
    """Return the package version, with git short hash if available."""
    from importlib.metadata import version

    v = version("orca")

    import subprocess

    src_dir = Path(__file__).resolve().parent.parent.parent.parent
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=src_dir,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return f"{v} ({result.stdout.strip()})"
    except Exception:
        pass
    return v


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser with subcommands."""
    parser = argparse.ArgumentParser(prog="orca", description="Orca workflow orchestrator")
    parser.add_argument("-v", "--version", action="store_true", help="Print version and exit")
    parser.add_argument("--root", type=Path, default=None, help="Repository root (default: auto-detect via git)")
    visible_subcommands = (
        "daemon",
        "run",
        "tui",
        "mcp",
        "stop",
        "resume",
        "drop",
        "retry",
        "init",
        "clean",
        "runs",
        "logs",
        "unblock",
    )
    sub = parser.add_subparsers(dest="subcommand", metavar="{" + ",".join(visible_subcommands) + "}")

    # orca daemon start|stop|status
    daemon_parser = sub.add_parser("daemon", help="Manage the orca daemon")
    daemon_parser.add_argument("daemon_action", choices=["start", "stop", "status"])
    daemon_parser.add_argument("--foreground", action="store_true", help="Run in foreground (default: daemonize)")

    # orca run <task.md> [-w workflow] [-b branch] [--base ref] [--max-hops N] [--max-retries N]
    run_parser = sub.add_parser("run", help="Submit a workflow run")
    run_parser.add_argument("task_file", type=Path)
    run_parser.add_argument("-w", "--workflow", type=str, default=None)
    run_parser.add_argument("-b", "--branch", type=str, default=None)
    run_parser.add_argument("--base", type=str, default=None)
    run_parser.add_argument("--headless", action="store_true")
    run_parser.add_argument("--insights", action="store_true")
    run_parser.add_argument(
        "--debug",
        action="store_true",
        help="Pause after every worker completion for review (debug mode).",
    )
    run_parser.add_argument("--run-id", type=str, default=None)
    run_parser.add_argument("--max-hops", type=int, default=10)
    run_parser.add_argument("--max-retries", type=int, default=3)

    # orca tui
    sub.add_parser("tui", help="Attach TUI to daemon")

    # orca mcp
    sub.add_parser("mcp", help="MCP stdio bridge")

    # orca stop <run_id>
    stop_parser = sub.add_parser("stop", help="Stop a running workflow")
    stop_parser.add_argument("run_id", type=str)

    # orca resume <run_id>
    resume_parser = sub.add_parser("resume", help="Resume a stopped/failed workflow")
    resume_parser.add_argument("run_id", type=str)

    # orca drop <run_id>
    drop_parser = sub.add_parser("drop", help="Drop a run from the daemon")
    drop_parser.add_argument("run_id", type=str)

    # orca retry <run_id> <issue_id>
    retry_parser = sub.add_parser("retry", help="Retry a failed issue")
    retry_parser.add_argument("run_id", type=str)
    retry_parser.add_argument("issue_id", type=str, help="Issue ID (find via orca runs, state.json, or MCP)")

    # orca init (deprecated — playbooks are served via the orca_get_playbook MCP tool)
    sub.add_parser("init", help="Deprecated; cleans up legacy .orca/playbooks/ if present")

    # orca clean [--dry-run] [-y]
    clean_parser = sub.add_parser("clean", help="Remove terminal-state runs and accumulated artifacts")
    clean_parser.add_argument("--dry-run", action="store_true", help="Show what would be cleaned without removing")
    clean_parser.add_argument("-y", "--yes", action="store_true", help="Skip the confirmation prompt")

    # orca runs [--waiting]
    runs_parser = sub.add_parser("runs", help="List all runs")
    runs_parser.add_argument(
        "--waiting",
        action="store_true",
        help="Only show runs with at least one issue currently waiting on HITL input",
    )

    # orca logs <run_id> [issue_id] [--tail N]
    logs_parser = sub.add_parser("logs", help="Print worker logs")
    logs_parser.add_argument("run_id", type=str)
    logs_parser.add_argument("issue_id", type=str, nargs="?", default=None)
    logs_parser.add_argument("--tail", type=int, default=100)

    # orca unblock <run_id> <issue_id> -m "message"
    unblock_parser = sub.add_parser("unblock", help="Unblock a blocked worker")
    unblock_parser.add_argument("run_id", type=str)
    unblock_parser.add_argument("issue_id", type=str)
    unblock_parser.add_argument("-m", "--message", type=str, required=True, help="Message to send to the worker")

    # Kept as a hidden compatibility stub so old automation fails clearly.
    eval_parser = sub.add_parser("eval", help=argparse.SUPPRESS)
    eval_parser.add_argument("args", nargs="*")
    eval_parser.add_argument("--all", action="store_true")
    sub._choices_actions = [action for action in sub._choices_actions if action.dest != "eval"]

    return parser


def main() -> None:
    """CLI entry point: dispatch to subcommand handlers via lazy imports."""
    parser = build_parser()
    args = parser.parse_args()

    if args.version:
        print(f"orca {_version_string()}")
        return

    if args.subcommand is None:
        parser.print_help()
        sys.exit(1)

    if args.subcommand == "daemon":
        from orca.cli.daemon_cmd import daemon_command

        daemon_command(args.daemon_action, root=args.root, foreground=args.foreground)

    elif args.subcommand == "run":
        from orca.cli.run_cmd import run_command

        run_command(args)  # args.root already in args

    elif args.subcommand == "tui":
        from orca.cli.tui_cmd import tui_command

        tui_command(root=args.root)

    elif args.subcommand == "mcp":
        from orca.cli.mcp_cmd import mcp_command

        mcp_command()

    elif args.subcommand == "stop":
        from orca.cli.stop_cmd import stop_command

        stop_command(args.run_id, root=args.root)

    elif args.subcommand == "drop":
        from orca.cli.drop_cmd import drop_command

        drop_command(args.run_id, root=args.root)

    elif args.subcommand == "resume":
        from orca.cli.resume_cmd import resume_command

        resume_command(args.run_id, root=args.root)

    elif args.subcommand == "retry":
        from orca.cli.retry_cmd import retry_command

        retry_command(args.run_id, args.issue_id, root=args.root)

    elif args.subcommand == "init":
        from orca.cli.init_cmd import init_command

        init_command(root=args.root)

    elif args.subcommand == "clean":
        from orca.cli.clean_cmd import clean_command

        clean_command(root=args.root, dry_run=args.dry_run, yes=args.yes)

    elif args.subcommand == "runs":
        from orca.cli.list_cmd import runs_command

        runs_command(root=args.root, waiting_only=args.waiting)

    elif args.subcommand == "logs":
        from orca.cli.list_cmd import logs_command

        logs_command(args)  # args.root already in args

    elif args.subcommand == "unblock":
        from orca.cli.unblock_cmd import unblock_command

        unblock_command(args.run_id, args.issue_id, args.message, root=args.root)

    elif args.subcommand == "eval":
        print("Error: `orca eval` has been removed.", file=sys.stderr)
        sys.exit(2)

    else:
        parser.print_help()
        sys.exit(1)
