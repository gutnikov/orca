"""Top-level CLI dispatcher for orca."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser with subcommands."""
    parser = argparse.ArgumentParser(prog="orca", description="Orca workflow orchestrator")
    sub = parser.add_subparsers(dest="subcommand", required=True)

    # orca daemon start|stop|status
    daemon_parser = sub.add_parser("daemon", help="Manage the orca daemon")
    daemon_parser.add_argument("daemon_action", choices=["start", "stop", "status"])

    # orca run <task.md> [-w workflow] [-b branch] [--base ref] [--max-hops N] [--max-retries N]
    run_parser = sub.add_parser("run", help="Submit a workflow run")
    run_parser.add_argument("task_file", type=Path)
    run_parser.add_argument("-w", "--workflow", type=str, default=None)
    run_parser.add_argument("-b", "--branch", type=str, default=None)
    run_parser.add_argument("--base", type=str, default=None)
    run_parser.add_argument("--max-hops", type=int, default=10)
    run_parser.add_argument("--max-retries", type=int, default=3)

    # orca tui
    sub.add_parser("tui", help="Attach TUI to daemon")

    # orca mcp
    sub.add_parser("mcp", help="MCP stdio bridge")

    # orca runs
    sub.add_parser("runs", help="List all runs")

    # orca logs <run_id> [issue_id] [--tail N]
    logs_parser = sub.add_parser("logs", help="Print worker logs")
    logs_parser.add_argument("run_id", type=str)
    logs_parser.add_argument("issue_id", type=str, nargs="?", default=None)
    logs_parser.add_argument("--tail", type=int, default=100)

    return parser


def main() -> None:
    """CLI entry point: dispatch to subcommand handlers via lazy imports."""
    parser = build_parser()
    args = parser.parse_args()

    if args.subcommand == "daemon":
        from orca.cli.daemon_cmd import daemon_command

        daemon_command(args.daemon_action)

    elif args.subcommand == "run":
        from orca.cli.run_cmd import run_command

        run_command(args)

    elif args.subcommand == "tui":
        from orca.cli.tui_cmd import tui_command

        tui_command()

    elif args.subcommand == "mcp":
        from orca.cli.mcp_cmd import mcp_command

        mcp_command()

    elif args.subcommand == "runs":
        from orca.cli.list_cmd import runs_command

        runs_command()

    elif args.subcommand == "logs":
        from orca.cli.list_cmd import logs_command

        logs_command(args)

    else:
        parser.print_help()
        sys.exit(1)
