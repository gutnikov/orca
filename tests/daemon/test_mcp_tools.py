from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mcp.server.fastmcp import FastMCP

from orca.daemon.mcp_tools import create_mcp_server


@pytest.fixture()
def repo_root(tmp_path: Path) -> Path:
    return tmp_path / "repo"


@pytest.fixture()
def mock_client() -> MagicMock:
    from orca.daemon.client import DaemonClient

    mock = MagicMock(spec=DaemonClient)
    mock.status = AsyncMock(return_value={"uptime": 1.0, "active_runs": 0, "total_runs": 0})
    mock.list_runs = AsyncMock(return_value=[])
    mock.get_run = AsyncMock(return_value={"error": "run 'nope:default' not found"})
    mock.get_issue = AsyncMock(return_value={"error": "issue 'iss-1' not found in run 'nope:default'"})
    mock.get_insights = AsyncMock(return_value="")
    mock.get_worker_log = AsyncMock(return_value="")
    mock.retry_issue = AsyncMock(return_value={"error": "run 'nope:default' not found"})
    mock.stop_run = AsyncMock(return_value={"error": "run 'nope:default' not found"})
    mock.drop_run = AsyncMock(return_value={"error": "run 'nope:default' not found"})
    mock.resume_run = AsyncMock(return_value={"error": "run 'nope:default' not found"})
    return mock


@pytest.fixture()
def server(repo_root: Path, mock_client: MagicMock) -> Iterator[FastMCP[Any]]:
    with (
        patch("orca.daemon.mcp_tools.check_daemon_running", return_value=True),
        patch("orca.daemon.mcp_tools.DaemonClient", return_value=mock_client),
    ):
        yield create_mcp_server(repo_root)


class TestMcpToolRegistration:
    def test_server_has_all_tools(self, server: MagicMock) -> None:
        assert server is not None

    @pytest.mark.asyncio()
    async def test_all_tools_registered(self, server: MagicMock) -> None:
        tools = await server.list_tools()
        tool_names = {t.name for t in tools}
        expected = {
            "orca_daemon_status",
            "orca_start_run",
            "orca_list_runs",
            "orca_get_run",
            "orca_get_issue",
            "orca_get_insights",
            "orca_get_worker_log",
            "orca_retry_issue",
            "orca_stop_run",
            "orca_drop_run",
            "orca_resume_run",
        }
        assert tool_names == expected


@pytest.mark.asyncio()
class TestDaemonStatusTool:
    async def test_returns_uptime_and_counts(self, server: MagicMock, mock_client: MagicMock) -> None:
        with (
            patch("orca.daemon.mcp_tools.check_daemon_running", return_value=True),
            patch("orca.daemon.mcp_tools.DaemonClient", return_value=mock_client),
        ):
            content_blocks, _ = await server.call_tool("orca_daemon_status", {})
        data = json.loads(content_blocks[0].text)
        assert data["active_runs"] == 0
        assert data["total_runs"] == 0
        assert "uptime" in data


@pytest.mark.asyncio()
class TestListRunsTool:
    async def test_empty_list(self, server: MagicMock, mock_client: MagicMock) -> None:
        with (
            patch("orca.daemon.mcp_tools.check_daemon_running", return_value=True),
            patch("orca.daemon.mcp_tools.DaemonClient", return_value=mock_client),
        ):
            content_blocks, _ = await server.call_tool("orca_list_runs", {})
        data = json.loads(content_blocks[0].text)
        assert data == []


@pytest.mark.asyncio()
class TestGetRunTool:
    async def test_not_found(self, server: MagicMock, mock_client: MagicMock) -> None:
        with (
            patch("orca.daemon.mcp_tools.check_daemon_running", return_value=True),
            patch("orca.daemon.mcp_tools.DaemonClient", return_value=mock_client),
        ):
            content_blocks, _ = await server.call_tool("orca_get_run", {"run_id": "nope:default"})
        data = json.loads(content_blocks[0].text)
        assert "error" in data

    async def test_not_found_message(self, server: MagicMock, mock_client: MagicMock) -> None:
        with (
            patch("orca.daemon.mcp_tools.check_daemon_running", return_value=True),
            patch("orca.daemon.mcp_tools.DaemonClient", return_value=mock_client),
        ):
            content_blocks, _ = await server.call_tool("orca_get_run", {"run_id": "nope:default"})
        data = json.loads(content_blocks[0].text)
        assert "nope:default" in data["error"]


@pytest.mark.asyncio()
class TestGetIssueTool:
    async def test_not_found_run(self, server: MagicMock, mock_client: MagicMock) -> None:
        with (
            patch("orca.daemon.mcp_tools.check_daemon_running", return_value=True),
            patch("orca.daemon.mcp_tools.DaemonClient", return_value=mock_client),
        ):
            content_blocks, _ = await server.call_tool(
                "orca_get_issue", {"run_id": "nope:default", "issue_id": "iss-1"}
            )
        data = json.loads(content_blocks[0].text)
        assert "error" in data


@pytest.mark.asyncio()
class TestGetInsightsTool:
    async def test_empty_for_unknown_run(self, server: MagicMock, mock_client: MagicMock) -> None:
        with (
            patch("orca.daemon.mcp_tools.check_daemon_running", return_value=True),
            patch("orca.daemon.mcp_tools.DaemonClient", return_value=mock_client),
        ):
            content_blocks, _ = await server.call_tool("orca_get_insights", {"run_id": "nope:default"})
        assert content_blocks[0].text == ""


@pytest.mark.asyncio()
class TestGetWorkerLogTool:
    async def test_empty_for_unknown_run(self, server: MagicMock, mock_client: MagicMock) -> None:
        with (
            patch("orca.daemon.mcp_tools.check_daemon_running", return_value=True),
            patch("orca.daemon.mcp_tools.DaemonClient", return_value=mock_client),
        ):
            content_blocks, _ = await server.call_tool(
                "orca_get_worker_log", {"run_id": "nope:default", "issue_id": "iss-1"}
            )
        assert content_blocks[0].text == ""


@pytest.mark.asyncio()
class TestRetryIssueTool:
    async def test_not_found(self, server: MagicMock, mock_client: MagicMock) -> None:
        with (
            patch("orca.daemon.mcp_tools.check_daemon_running", return_value=True),
            patch("orca.daemon.mcp_tools.DaemonClient", return_value=mock_client),
        ):
            content_blocks, _ = await server.call_tool(
                "orca_retry_issue", {"run_id": "nope:default", "issue_id": "iss-1"}
            )
        data = json.loads(content_blocks[0].text)
        assert "error" in data


@pytest.mark.asyncio()
class TestStopRunTool:
    async def test_not_found(self, server: MagicMock, mock_client: MagicMock) -> None:
        with (
            patch("orca.daemon.mcp_tools.check_daemon_running", return_value=True),
            patch("orca.daemon.mcp_tools.DaemonClient", return_value=mock_client),
        ):
            content_blocks, _ = await server.call_tool("orca_stop_run", {"run_id": "nope:default"})
        data = json.loads(content_blocks[0].text)
        assert "error" in data
