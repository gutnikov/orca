from __future__ import annotations

import pytest

from orca.cli.main import build_parser


class TestCliDispatch:
    def test_no_subcommand_shows_help(self) -> None:
        parser = build_parser()
        args = parser.parse_args([])
        assert args.subcommand is None

    def test_daemon_start_subcommand(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["daemon", "start"])
        assert args.subcommand == "daemon"
        assert args.daemon_action == "start"

    def test_daemon_stop_subcommand(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["daemon", "stop"])
        assert args.subcommand == "daemon"
        assert args.daemon_action == "stop"

    def test_daemon_status_subcommand(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["daemon", "status"])
        assert args.subcommand == "daemon"
        assert args.daemon_action == "status"

    def test_run_subcommand(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["run", "task.md", "-w", "develop", "-b", "feat/x"])
        assert args.subcommand == "run"
        assert str(args.task_file) == "task.md"
        assert args.workflow == "develop"
        assert args.branch == "feat/x"

    def test_run_subcommand_defaults(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["run", "task.md"])
        assert args.subcommand == "run"
        assert str(args.task_file) == "task.md"
        assert args.workflow is None
        assert args.branch is None
        assert args.base is None
        assert args.max_hops == 10
        assert args.max_retries == 3

    def test_run_subcommand_all_options(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "run",
                "task.md",
                "-w",
                "ci",
                "-b",
                "my-branch",
                "--base",
                "origin/main",
                "--max-hops",
                "5",
                "--max-retries",
                "2",
            ]
        )
        assert args.base == "origin/main"
        assert args.max_hops == 5
        assert args.max_retries == 2

    def test_tui_subcommand(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["tui"])
        assert args.subcommand == "tui"
        assert args.run_id is None

    def test_tui_subcommand_accepts_run_id(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["tui", "DEV-52_payments_fees:test-plan-execute"])
        assert args.subcommand == "tui"
        assert args.run_id == "DEV-52_payments_fees:test-plan-execute"

    def test_mcp_subcommand(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["mcp"])
        assert args.subcommand == "mcp"

    def test_runs_subcommand(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["runs"])
        assert args.subcommand == "runs"
        assert args.waiting is False

    def test_runs_subcommand_waiting_flag(self) -> None:
        """gh#16 — `orca runs --waiting` filters to runs currently parked
        on HITL input (a `waiting_issues` field with at least one entry).
        """
        parser = build_parser()
        args = parser.parse_args(["runs", "--waiting"])
        assert args.subcommand == "runs"
        assert args.waiting is True

    def test_logs_subcommand(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["logs", "main:default"])
        assert args.subcommand == "logs"
        assert args.run_id == "main:default"
        assert args.issue_id is None
        assert args.tail == 100

    def test_logs_subcommand_with_issue_and_tail(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["logs", "main:default", "issue-123", "--tail", "50"])
        assert args.run_id == "main:default"
        assert args.issue_id == "issue-123"
        assert args.tail == 50

    def test_root_flag_default_none(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["runs"])
        assert args.root is None

    def test_root_flag_with_path(self) -> None:
        from pathlib import Path

        parser = build_parser()
        args = parser.parse_args(["--root", "/tmp/myrepo", "daemon", "status"])
        assert args.root == Path("/tmp/myrepo")
        assert args.subcommand == "daemon"


class TestCleanParser:
    def test_clean_default_flags(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["clean"])
        assert args.subcommand == "clean"
        assert args.dry_run is False
        assert args.yes is False

    def test_clean_dry_run(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["clean", "--dry-run"])
        assert args.dry_run is True
        assert args.yes is False

    def test_clean_yes_short(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["clean", "-y"])
        assert args.yes is True

    def test_clean_yes_long(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["clean", "--yes"])
        assert args.yes is True

    def test_clean_combined_flags(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["clean", "--dry-run", "-y"])
        assert args.dry_run is True
        assert args.yes is True


class TestUnblockParser:
    def test_parser_accepts_unblock(self) -> None:
        from orca.cli.main import build_parser

        parser = build_parser()
        args = parser.parse_args(["unblock", "my-run:default", "issue-1", "-m", "PR merged"])
        assert args.subcommand == "unblock"
        assert args.run_id == "my-run:default"
        assert args.issue_id == "issue-1"
        assert args.message == "PR merged"

    def test_parser_requires_message(self) -> None:
        from orca.cli.main import build_parser

        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["unblock", "my-run:default", "issue-1"])


class TestRemovedEvalParser:
    def test_removed_command_is_hidden_from_help(self) -> None:
        parser = build_parser()
        help_text = parser.format_help()
        assert "eval" not in help_text

    def test_parser_accepts_hidden_compatibility_stub(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["eval"])
        assert args.subcommand == "eval"
        assert args.args == []
        assert args.all is False

    def test_parser_accepts_removed_all_flag_for_clear_error(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["eval", "--all"])
        assert args.subcommand == "eval"
        assert args.all is True
