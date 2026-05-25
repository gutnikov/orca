from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mcp.types import TextContent

from orca.daemon.mcp_tools import create_mcp_server

FAKE_ROOT = "/tmp/test-repo"


def _first_text(content_blocks: object) -> str:
    assert isinstance(content_blocks, list)
    first_block = content_blocks[0]
    assert isinstance(first_block, TextContent)
    return str(first_block.text)


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


class TestMcpToolRegistration:
    def test_server_has_all_tools(self) -> None:
        server = create_mcp_server()
        assert server is not None

    @pytest.mark.asyncio()
    async def test_all_tools_registered(self) -> None:
        server = create_mcp_server()
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
            "orca_unblock_worker",
            "orca_get_debug_review",
            "orca_submit_debug_decision",
            "orca_restart_state",
            "orca_clear_modify_pending",
            "orca_get_playbook",
            "orca_list_playbooks",
        }
        assert tool_names == expected


@pytest.mark.asyncio()
class TestDaemonStatusTool:
    async def test_returns_uptime_and_counts(self, mock_client: MagicMock) -> None:
        server = create_mcp_server()
        with (
            patch("orca.daemon.mcp_tools.check_daemon_running", return_value=True),
            patch("orca.daemon.mcp_tools.DaemonClient", return_value=mock_client),
        ):
            content_blocks, _ = await server.call_tool("orca_daemon_status", {"root": FAKE_ROOT})
        data = json.loads(_first_text(content_blocks))
        assert data["active_runs"] == 0
        assert data["total_runs"] == 0
        assert "uptime" in data


@pytest.mark.asyncio()
class TestListRunsTool:
    async def test_empty_list(self, mock_client: MagicMock) -> None:
        server = create_mcp_server()
        with (
            patch("orca.daemon.mcp_tools.check_daemon_running", return_value=True),
            patch("orca.daemon.mcp_tools.DaemonClient", return_value=mock_client),
        ):
            content_blocks, _ = await server.call_tool("orca_list_runs", {"root": FAKE_ROOT})
        data = json.loads(_first_text(content_blocks))
        assert data == []


@pytest.mark.asyncio()
class TestGetRunTool:
    async def test_not_found(self, mock_client: MagicMock) -> None:
        server = create_mcp_server()
        with (
            patch("orca.daemon.mcp_tools.check_daemon_running", return_value=True),
            patch("orca.daemon.mcp_tools.DaemonClient", return_value=mock_client),
        ):
            content_blocks, _ = await server.call_tool("orca_get_run", {"root": FAKE_ROOT, "run_id": "nope:default"})
        data = json.loads(_first_text(content_blocks))
        assert "error" in data

    async def test_not_found_message(self, mock_client: MagicMock) -> None:
        server = create_mcp_server()
        with (
            patch("orca.daemon.mcp_tools.check_daemon_running", return_value=True),
            patch("orca.daemon.mcp_tools.DaemonClient", return_value=mock_client),
        ):
            content_blocks, _ = await server.call_tool("orca_get_run", {"root": FAKE_ROOT, "run_id": "nope:default"})
        data = json.loads(_first_text(content_blocks))
        assert "nope:default" in data["error"]


@pytest.mark.asyncio()
class TestGetIssueTool:
    async def test_not_found_run(self, mock_client: MagicMock) -> None:
        server = create_mcp_server()
        with (
            patch("orca.daemon.mcp_tools.check_daemon_running", return_value=True),
            patch("orca.daemon.mcp_tools.DaemonClient", return_value=mock_client),
        ):
            content_blocks, _ = await server.call_tool(
                "orca_get_issue", {"root": FAKE_ROOT, "run_id": "nope:default", "issue_id": "iss-1"}
            )
        data = json.loads(_first_text(content_blocks))
        assert "error" in data


@pytest.mark.asyncio()
class TestGetInsightsTool:
    async def test_empty_for_unknown_run(self, mock_client: MagicMock) -> None:
        server = create_mcp_server()
        with (
            patch("orca.daemon.mcp_tools.check_daemon_running", return_value=True),
            patch("orca.daemon.mcp_tools.DaemonClient", return_value=mock_client),
        ):
            content_blocks, _ = await server.call_tool(
                "orca_get_insights", {"root": FAKE_ROOT, "run_id": "nope:default"}
            )
        assert _first_text(content_blocks) == ""


@pytest.mark.asyncio()
class TestGetWorkerLogTool:
    async def test_empty_for_unknown_run(self, mock_client: MagicMock) -> None:
        server = create_mcp_server()
        with (
            patch("orca.daemon.mcp_tools.check_daemon_running", return_value=True),
            patch("orca.daemon.mcp_tools.DaemonClient", return_value=mock_client),
        ):
            content_blocks, _ = await server.call_tool(
                "orca_get_worker_log", {"root": FAKE_ROOT, "run_id": "nope:default", "issue_id": "iss-1"}
            )
        assert _first_text(content_blocks) == ""


@pytest.mark.asyncio()
class TestRetryIssueTool:
    async def test_not_found(self, mock_client: MagicMock) -> None:
        server = create_mcp_server()
        with (
            patch("orca.daemon.mcp_tools.check_daemon_running", return_value=True),
            patch("orca.daemon.mcp_tools.DaemonClient", return_value=mock_client),
        ):
            content_blocks, _ = await server.call_tool(
                "orca_retry_issue", {"root": FAKE_ROOT, "run_id": "nope:default", "issue_id": "iss-1"}
            )
        data = json.loads(_first_text(content_blocks))
        assert "error" in data


@pytest.mark.asyncio()
class TestStopRunTool:
    async def test_not_found(self, mock_client: MagicMock) -> None:
        server = create_mcp_server()
        with (
            patch("orca.daemon.mcp_tools.check_daemon_running", return_value=True),
            patch("orca.daemon.mcp_tools.DaemonClient", return_value=mock_client),
        ):
            content_blocks, _ = await server.call_tool("orca_stop_run", {"root": FAKE_ROOT, "run_id": "nope:default"})
        data = json.loads(_first_text(content_blocks))
        assert "error" in data


@pytest.mark.asyncio()
class TestGetPlaybookTool:
    async def test_returns_top_level_playbook_content(self) -> None:
        server = create_mcp_server()
        content_blocks, _ = await server.call_tool("orca_get_playbook", {"name": "orca-workflow-create"})
        text = _first_text(content_blocks)
        # The playbook starts with this header — proves we read the bundled file.
        assert text.startswith("# Playbook: Create an Orca Workflow")

    async def test_returns_subdir_playbook_content(self) -> None:
        server = create_mcp_server()
        content_blocks, _ = await server.call_tool("orca_get_playbook", {"name": "reference/orca-glossary"})
        text = _first_text(content_blocks)
        # First line of the glossary — proves the subdir lookup works.
        assert "glossary" in text.lower()

    async def test_accepts_trailing_md_suffix(self) -> None:
        """Names with or without `.md` should resolve identically."""
        server = create_mcp_server()
        with_md, _ = await server.call_tool("orca_get_playbook", {"name": "orca-workflow-create.md"})
        without_md, _ = await server.call_tool("orca_get_playbook", {"name": "orca-workflow-create"})
        assert _first_text(with_md) == _first_text(without_md)

    async def test_rejects_parent_traversal(self) -> None:
        from mcp.server.fastmcp.exceptions import ToolError

        server = create_mcp_server()
        with pytest.raises(ToolError, match="invalid playbook name"):
            await server.call_tool("orca_get_playbook", {"name": "../../../etc/passwd"})

    async def test_rejects_absolute_path(self) -> None:
        from mcp.server.fastmcp.exceptions import ToolError

        server = create_mcp_server()
        with pytest.raises(ToolError, match="invalid playbook name"):
            await server.call_tool("orca_get_playbook", {"name": "/etc/passwd"})

    async def test_rejects_empty_name(self) -> None:
        from mcp.server.fastmcp.exceptions import ToolError

        server = create_mcp_server()
        with pytest.raises(ToolError, match="invalid playbook name"):
            await server.call_tool("orca_get_playbook", {"name": ""})

    async def test_errors_on_unknown_playbook(self) -> None:
        from mcp.server.fastmcp.exceptions import ToolError

        server = create_mcp_server()
        with pytest.raises(ToolError, match="playbook not found"):
            await server.call_tool("orca_get_playbook", {"name": "does-not-exist"})


@pytest.mark.asyncio()
class TestListPlaybooksTool:
    async def test_includes_known_playbooks(self) -> None:
        server = create_mcp_server()
        content_blocks, _ = await server.call_tool("orca_list_playbooks", {})
        names = json.loads(_first_text(content_blocks))
        assert isinstance(names, list)
        # Spot-check a few well-known playbooks.
        assert "orca-workflow-create" in names
        assert "reference/orca-glossary" in names
        assert "reference/wrapper-skill-template" in names

    async def test_sorted_and_unique(self) -> None:
        server = create_mcp_server()
        content_blocks, _ = await server.call_tool("orca_list_playbooks", {})
        names = json.loads(_first_text(content_blocks))
        assert names == sorted(names)
        assert len(names) == len(set(names))

    async def test_no_md_suffix(self) -> None:
        server = create_mcp_server()
        content_blocks, _ = await server.call_tool("orca_list_playbooks", {})
        names = json.loads(_first_text(content_blocks))
        for n in names:
            assert not n.endswith(".md")
