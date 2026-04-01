"""MCP tools that proxy to the orca daemon HTTP API."""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from orca.daemon.client import DaemonClient


def create_mcp_server(client: DaemonClient) -> FastMCP:
    """Create an MCP server with orca daemon tools backed by DaemonClient."""
    server = FastMCP("orca")

    async def orca_daemon_status() -> str:
        """Get the daemon status including uptime, active run count, and total run count."""
        result = await client.status()
        return json.dumps(result)

    async def orca_start_run(
        task_file: str,
        workflow: str | None = None,
        branch: str | None = None,
        run_id: str | None = None,
    ) -> str:
        """Start a new orca workflow run.

        Args:
            task_file: Path to the task markdown file.
            workflow: Optional workflow name (defaults to 'default').
            branch: Optional git branch name (auto-detected if omitted).
            run_id: Optional custom run identifier (defaults to 'branch:workflow').

        Returns JSON with run_id and status, or an error message.
        """
        result = await client.start_run(task_file, workflow, branch, run_id)
        return json.dumps(result)

    async def orca_list_runs() -> str:
        """List all runs with their summary information.

        Returns a JSON array of run summaries.
        """
        result = await client.list_runs()
        return json.dumps(result)

    async def orca_get_run(run_id: str) -> str:
        """Get details for a specific run.

        Args:
            run_id: The run identifier (format: 'branch:workflow').

        Returns JSON with run_id, status, and state, or an error message.
        """
        result = await client.get_run(run_id)
        return json.dumps(result)

    async def orca_get_issue(run_id: str, issue_id: str) -> str:
        """Get a specific issue from a run.

        Args:
            run_id: The run identifier.
            issue_id: The issue identifier.

        Returns the issue as JSON, or an error message.
        """
        result = await client.get_issue(run_id, issue_id)
        return json.dumps(result)

    async def orca_get_insights(run_id: str) -> str:
        """Get insights log text for a run.

        Args:
            run_id: The run identifier.

        Returns plain text insights content, or empty string if not available.
        """
        return await client.get_insights(run_id)

    async def orca_get_worker_log(run_id: str, issue_id: str, tail: int = 100) -> str:
        """Get the worker log for a specific issue in a run.

        Args:
            run_id: The run identifier.
            issue_id: The issue identifier (used as tracking ID).
            tail: Number of trailing lines to return (default 100).

        Returns plain text log content, or empty string if not available.
        """
        return await client.get_worker_log(run_id, issue_id, tail)

    async def orca_retry_issue(run_id: str, issue_id: str) -> str:
        """Retry a failed issue in a run.

        Args:
            run_id: The run identifier.
            issue_id: The issue identifier to retry.

        Returns JSON with status, or an error message.
        """
        result = await client.retry_issue(run_id, issue_id)
        return json.dumps(result)

    async def orca_stop_run(run_id: str) -> str:
        """Stop a running orca workflow.

        Args:
            run_id: The run identifier to stop.

        Returns JSON with status, or an error message.
        """
        result = await client.stop_run(run_id)
        return json.dumps(result)

    async def orca_drop_run(run_id: str) -> str:
        """Drop a run from the daemon, stopping it first if running.

        Args:
            run_id: The run identifier to drop.

        Returns JSON with status, or an error message.
        """
        result = await client.drop_run(run_id)
        return json.dumps(result)

    async def orca_resume_run(run_id: str) -> str:
        """Resume a stopped, failed, or interrupted orca workflow.

        Args:
            run_id: The run identifier to resume.

        Returns JSON with status, or an error message.
        """
        result = await client.resume_run(run_id)
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

    return server
