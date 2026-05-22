"""MCP tools that proxy to the orca daemon HTTP API."""

from __future__ import annotations

import json
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from orca.daemon.client import DaemonClient
from orca.daemon.lifecycle import check_daemon_running, socket_path


def _resolve_playbook(name: str) -> Traversable:
    """Resolve a playbook name to the bundled file Traversable.

    Accepts names with or without a trailing `.md`. Subdirectories use `/`.
    Rejects empty, absolute, or parent-traversing names.
    """
    stem = name.removesuffix(".md")
    parts = stem.split("/")
    if not stem or any(p in ("", "..", ".") for p in parts):
        msg = f"invalid playbook name: {name!r}"
        raise ValueError(msg)
    target = files("orca.playbooks")
    for part in parts[:-1]:
        target = target.joinpath(part)
    target = target.joinpath(parts[-1] + ".md")
    if not target.is_file():
        msg = f"playbook not found: {name!r}"
        raise ValueError(msg)
    return target


def _list_playbook_names() -> list[str]:
    """Return every bundled playbook's name (no `.md`), sorted."""
    names: list[str] = []

    def _walk(node: Traversable, prefix: str) -> None:
        for child in node.iterdir():
            if child.is_dir():
                _walk(child, prefix + child.name + "/")
            elif child.name.endswith(".md"):
                names.append(prefix + child.name.removesuffix(".md"))

    _walk(files("orca.playbooks"), "")
    return sorted(names)


def create_mcp_server() -> FastMCP:
    """Create an MCP server with orca daemon tools.

    Every tool requires a ``root`` parameter — the absolute path to the
    target project's repo root. The tool resolves the daemon socket from
    that path and connects on demand.
    """
    server = FastMCP("orca")

    def _get_client(root: str) -> DaemonClient:
        repo = Path(root)
        if not check_daemon_running(repo):
            raise RuntimeError(f"Daemon is not running for {repo}. Start it with: orca --root {repo} daemon start")
        return DaemonClient(socket_path(repo))

    async def orca_daemon_status(root: str) -> str:
        """Get the daemon status including uptime, active run count, and total run count.

        Args:
            root: Absolute path to the target project's repo root.
        """
        result = await _get_client(root).status()
        return json.dumps(result)

    async def orca_start_run(
        root: str,
        task_file: str,
        workflow: str | None = None,
        branch: str | None = None,
        run_id: str | None = None,
    ) -> str:
        """Start a new orca workflow run.

        Args:
            root: Absolute path to the target project's repo root.
            task_file: Path to the task markdown file.
            workflow: Optional workflow name (defaults to 'default').
            branch: Optional git branch name (auto-detected if omitted).
            run_id: Optional custom run identifier (defaults to 'branch:workflow').

        Returns JSON with run_id and status, or an error message.
        """
        result = await _get_client(root).start_run(task_file, workflow, branch, run_id)
        return json.dumps(result)

    async def orca_list_runs(root: str) -> str:
        """List all runs with their summary information.

        Args:
            root: Absolute path to the target project's repo root.

        Returns a JSON array of run summaries.
        """
        result = await _get_client(root).list_runs()
        return json.dumps(result)

    async def orca_get_run(root: str, run_id: str, compact: bool = False) -> str:
        """Get details for a specific run.

        Args:
            root: Absolute path to the target project's repo root.
            run_id: The run identifier (format: 'branch:workflow').
            compact: If true, return a compact summary without event_log, fields,
                     or completed sessions. Use for polling to save context tokens.

        Returns JSON with run_id, status, and state, or an error message.
        """
        result = await _get_client(root).get_run(run_id, compact=compact)
        return json.dumps(result)

    async def orca_get_issue(root: str, run_id: str, issue_id: str) -> str:
        """Get a specific issue from a run.

        Args:
            root: Absolute path to the target project's repo root.
            run_id: The run identifier.
            issue_id: The issue identifier.

        Returns the issue as JSON, or an error message.
        """
        result = await _get_client(root).get_issue(run_id, issue_id)
        return json.dumps(result)

    async def orca_get_insights(root: str, run_id: str) -> str:
        """Get insights log text for a run.

        Args:
            root: Absolute path to the target project's repo root.
            run_id: The run identifier.

        Returns plain text insights content, or empty string if not available.
        """
        return await _get_client(root).get_insights(run_id)

    async def orca_get_worker_log(root: str, run_id: str, issue_id: str, tail: int = 100) -> str:
        """Get the worker log for a specific issue in a run.

        Args:
            root: Absolute path to the target project's repo root.
            run_id: The run identifier.
            issue_id: The issue identifier (used as tracking ID).
            tail: Number of trailing lines to return (default 100).

        Returns plain text log content, or empty string if not available.
        """
        return await _get_client(root).get_worker_log(run_id, issue_id, tail)

    async def orca_retry_issue(root: str, run_id: str, issue_id: str) -> str:
        """Retry a failed issue in a run.

        Args:
            root: Absolute path to the target project's repo root.
            run_id: The run identifier.
            issue_id: The issue identifier to retry.

        Returns JSON with status, or an error message.
        """
        result = await _get_client(root).retry_issue(run_id, issue_id)
        return json.dumps(result)

    async def orca_stop_run(root: str, run_id: str) -> str:
        """Stop a running orca workflow.

        Args:
            root: Absolute path to the target project's repo root.
            run_id: The run identifier to stop.

        Returns JSON with status, or an error message.
        """
        result = await _get_client(root).stop_run(run_id)
        return json.dumps(result)

    async def orca_drop_run(root: str, run_id: str) -> str:
        """Drop a run from the daemon, stopping it first if running.

        Args:
            root: Absolute path to the target project's repo root.
            run_id: The run identifier to drop.

        Returns JSON with status, or an error message.
        """
        result = await _get_client(root).drop_run(run_id)
        return json.dumps(result)

    async def orca_resume_run(root: str, run_id: str) -> str:
        """Resume a stopped, failed, or interrupted orca workflow.

        Args:
            root: Absolute path to the target project's repo root.
            run_id: The run identifier to resume.

        Returns JSON with status, or an error message.
        """
        result = await _get_client(root).resume_run(run_id)
        return json.dumps(result)

    async def orca_get_playbook(name: str) -> str:
        """Fetch an orca playbook by name.

        Playbooks are the agent-facing reference material that drive every
        orca skill (`orca-workflow-create`, `orca-prompt-create`, etc.). They
        are bundled inside the installed orca package — call this tool
        instead of looking for them in the project's `.orca/playbooks/`
        directory; that directory no longer exists.

        Args:
            name: Playbook name without `.md`, e.g. `orca-workflow-create`
                  or `reference/orca-glossary`. Subdirectory names use `/`.

        Returns:
            The playbook's markdown content.

        Markdown links inside the returned content (e.g.
        `[orca-glossary](reference/orca-glossary.md)`) are also playbook
        names — follow them by calling this tool again with the link target.
        """
        return _resolve_playbook(name).read_text(encoding="utf-8")

    async def orca_list_playbooks() -> str:
        """List every playbook available via `orca_get_playbook`.

        Returns:
            JSON-encoded sorted list of playbook names (no `.md`).
        """
        return json.dumps(_list_playbook_names())

    async def orca_unblock_worker(root: str, run_id: str, issue_id: str, message: str) -> str:
        """Unblock a waiting worker by sending it a message.

        Args:
            root: Absolute path to the target project's repo root.
            run_id: The run identifier.
            issue_id: The issue identifier of the blocked worker.
            message: Message to send to the worker explaining what changed.

        Returns JSON with status, or an error message.
        """
        result = await _get_client(root).unblock_worker(run_id, issue_id, message)
        return json.dumps(result)

    server.add_tool(orca_daemon_status, name="orca_daemon_status")
    server.add_tool(orca_start_run, name="orca_start_run")
    server.add_tool(orca_list_runs, name="orca_list_runs")
    server.add_tool(orca_get_run, name="orca_get_run")
    server.add_tool(orca_get_issue, name="orca_get_issue")
    server.add_tool(orca_get_insights, name="orca_get_insights")
    server.add_tool(orca_get_worker_log, name="orca_get_worker_log")
    server.add_tool(orca_retry_issue, name="orca_retry_issue")
    server.add_tool(orca_stop_run, name="orca_stop_run")
    server.add_tool(orca_drop_run, name="orca_drop_run")
    server.add_tool(orca_resume_run, name="orca_resume_run")
    server.add_tool(orca_unblock_worker, name="orca_unblock_worker")
    server.add_tool(orca_get_playbook, name="orca_get_playbook")
    server.add_tool(orca_list_playbooks, name="orca_list_playbooks")

    return server
