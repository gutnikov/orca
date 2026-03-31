from __future__ import annotations

import json
import time
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from orca.daemon.manager import RunManager, RunStatus

_start_time = time.monotonic()


def create_mcp_server(manager: RunManager) -> FastMCP:
    """Create an MCP server with orca daemon tools."""
    server = FastMCP("orca")

    async def orca_daemon_status() -> str:
        """Get the daemon status including uptime, active run count, and total run count."""
        runs = manager.list_runs()
        active = sum(1 for r in runs if r.status == RunStatus.RUNNING)
        uptime = time.monotonic() - _start_time
        return json.dumps({"uptime": round(uptime, 1), "active_runs": active, "total_runs": len(runs)})

    async def orca_start_run(
        task_file: str,
        workflow: str | None = None,
        branch: str | None = None,
    ) -> str:
        """Start a new orca workflow run.

        Args:
            task_file: Path to the task markdown file.
            workflow: Optional workflow name (defaults to 'default').
            branch: Optional git branch name (auto-detected if omitted).

        Returns JSON with run_id and status, or an error message.
        """
        try:
            run_id = await manager.start_run(
                task_file=Path(task_file),
                workflow=workflow,
                branch=branch,
            )
            return json.dumps({"run_id": run_id, "status": "running"})
        except (ValueError, RuntimeError) as exc:
            return json.dumps({"error": str(exc)})

    async def orca_list_runs() -> str:
        """List all runs with their summary information.

        Returns a JSON array of run summaries.
        """
        runs = manager.list_runs()
        return json.dumps([r.to_summary() for r in runs])

    async def orca_get_run(run_id: str) -> str:
        """Get details for a specific run.

        Args:
            run_id: The run identifier (format: 'branch:workflow').

        Returns JSON with run_id, status, and state, or an error message.
        """
        run_info = manager.get_run(run_id)
        if run_info is None:
            return json.dumps({"error": f"Run '{run_id}' not found"})
        state = manager.get_run_state(run_id)
        return json.dumps({"run_id": run_id, "status": run_info.status.value, "state": state})

    async def orca_get_issue(run_id: str, issue_id: str) -> str:
        """Get a specific issue from a run.

        Args:
            run_id: The run identifier.
            issue_id: The issue identifier.

        Returns the issue as JSON, or an error message.
        """
        issue = manager.get_issue(run_id, issue_id)
        if issue is None:
            return json.dumps({"error": f"Issue '{issue_id}' not found in run '{run_id}'"})
        return json.dumps(issue)

    async def orca_get_insights(run_id: str) -> str:
        """Get insights log text for a run.

        Args:
            run_id: The run identifier.

        Returns plain text insights content, or empty string if not available.
        """
        return manager.get_insights(run_id)

    async def orca_get_worker_log(run_id: str, issue_id: str, tail: int = 100) -> str:
        """Get the worker log for a specific issue in a run.

        Args:
            run_id: The run identifier.
            issue_id: The issue identifier (used as tracking ID).
            tail: Number of trailing lines to return (default 100).

        Returns plain text log content, or empty string if not available.
        """
        return manager.get_worker_log(run_id, issue_id, tail)

    async def orca_retry_issue(run_id: str, issue_id: str) -> str:
        """Retry a failed issue in a run.

        Args:
            run_id: The run identifier.
            issue_id: The issue identifier to retry.

        Returns JSON with run_id, issue_id, and status, or an error message.
        """
        try:
            manager.retry_issue(run_id, issue_id)
            return json.dumps({"run_id": run_id, "issue_id": issue_id, "status": "retrying"})
        except (ValueError, RuntimeError) as exc:
            return json.dumps({"error": str(exc)})

    async def orca_stop_run(run_id: str) -> str:
        """Stop a running orca workflow.

        Args:
            run_id: The run identifier to stop.

        Returns JSON with run_id and status, or an error message.
        """
        try:
            await manager.stop_run(run_id)
            return json.dumps({"run_id": run_id, "status": "stopped"})
        except (ValueError, RuntimeError) as exc:
            return json.dumps({"error": str(exc)})

    server.add_tool(orca_daemon_status, name="orca_daemon_status")
    server.add_tool(orca_start_run, name="orca_start_run")
    server.add_tool(orca_list_runs, name="orca_list_runs")
    server.add_tool(orca_get_run, name="orca_get_run")
    server.add_tool(orca_get_issue, name="orca_get_issue")
    server.add_tool(orca_get_insights, name="orca_get_insights")
    server.add_tool(orca_get_worker_log, name="orca_get_worker_log")
    server.add_tool(orca_retry_issue, name="orca_retry_issue")
    server.add_tool(orca_stop_run, name="orca_stop_run")

    return server
