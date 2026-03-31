from __future__ import annotations

import json
from pathlib import Path

import pytest

from orca.daemon.manager import RunManager
from orca.daemon.mcp_tools import create_mcp_server


@pytest.fixture()
def manager(tmp_path: Path) -> RunManager:
    return RunManager(tmp_path)


class TestMcpToolRegistration:
    def test_server_has_all_tools(self, manager: RunManager) -> None:
        server = create_mcp_server(manager)
        assert server is not None

    @pytest.mark.asyncio()
    async def test_all_nine_tools_registered(self, manager: RunManager) -> None:
        server = create_mcp_server(manager)
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
        }
        assert tool_names == expected


@pytest.mark.asyncio()
class TestDaemonStatusTool:
    async def test_returns_uptime_and_counts(self, manager: RunManager) -> None:
        server = create_mcp_server(manager)
        content_blocks, _ = await server.call_tool("orca_daemon_status", {})
        data = json.loads(content_blocks[0].text)
        assert data["active_runs"] == 0
        assert data["total_runs"] == 0
        assert "uptime" in data


@pytest.mark.asyncio()
class TestListRunsTool:
    async def test_empty_list(self, manager: RunManager) -> None:
        server = create_mcp_server(manager)
        content_blocks, _ = await server.call_tool("orca_list_runs", {})
        data = json.loads(content_blocks[0].text)
        assert data == []


@pytest.mark.asyncio()
class TestGetRunTool:
    async def test_not_found(self, manager: RunManager) -> None:
        server = create_mcp_server(manager)
        content_blocks, _ = await server.call_tool("orca_get_run", {"run_id": "nope:default"})
        data = json.loads(content_blocks[0].text)
        assert "error" in data

    async def test_not_found_message(self, manager: RunManager) -> None:
        server = create_mcp_server(manager)
        content_blocks, _ = await server.call_tool("orca_get_run", {"run_id": "nope:default"})
        data = json.loads(content_blocks[0].text)
        assert "nope:default" in data["error"]


@pytest.mark.asyncio()
class TestGetIssueTool:
    async def test_not_found_run(self, manager: RunManager) -> None:
        server = create_mcp_server(manager)
        content_blocks, _ = await server.call_tool("orca_get_issue", {"run_id": "nope:default", "issue_id": "iss-1"})
        data = json.loads(content_blocks[0].text)
        assert "error" in data


@pytest.mark.asyncio()
class TestGetInsightsTool:
    async def test_empty_for_unknown_run(self, manager: RunManager) -> None:
        server = create_mcp_server(manager)
        content_blocks, _ = await server.call_tool("orca_get_insights", {"run_id": "nope:default"})
        assert content_blocks[0].text == ""


@pytest.mark.asyncio()
class TestGetWorkerLogTool:
    async def test_empty_for_unknown_run(self, manager: RunManager) -> None:
        server = create_mcp_server(manager)
        content_blocks, _ = await server.call_tool(
            "orca_get_worker_log", {"run_id": "nope:default", "issue_id": "iss-1"}
        )
        assert content_blocks[0].text == ""


@pytest.mark.asyncio()
class TestRetryIssueTool:
    async def test_not_found(self, manager: RunManager) -> None:
        server = create_mcp_server(manager)
        content_blocks, _ = await server.call_tool("orca_retry_issue", {"run_id": "nope:default", "issue_id": "iss-1"})
        data = json.loads(content_blocks[0].text)
        assert "error" in data


@pytest.mark.asyncio()
class TestStopRunTool:
    async def test_not_found(self, manager: RunManager) -> None:
        server = create_mcp_server(manager)
        content_blocks, _ = await server.call_tool("orca_stop_run", {"run_id": "nope:default"})
        data = json.loads(content_blocks[0].text)
        assert "error" in data
