from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mcp.types import TextContent
from starlette.testclient import TestClient

from orca.daemon.client import DaemonClient
from orca.daemon.http_api import create_app
from orca.daemon.manager import RunManager
from orca.daemon.mcp_tools import create_mcp_server


def _first_text(content_blocks: object) -> str:
    assert isinstance(content_blocks, list)
    first_block = content_blocks[0]
    assert isinstance(first_block, TextContent)
    return str(first_block.text)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """Minimal repo with orca.yml and task file."""
    config = """\
issue:
  fields:
    title:
      type: string
      description: Title
states:
  todo:
    worker:
      kind: claude-code
      prompt: prompts/todo.md
      result_format:
        outcome:
          type: enum
          values: [done]
          description: Outcome
    on:
      done: done
initial: todo
"""
    (tmp_path / "orca.yml").write_text(config)
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "todo.md").write_text("Do: {{ issue.title }}")
    (tmp_path / "task.md").write_text("title: Integration test task")
    return tmp_path


@pytest.fixture()
def mock_client() -> DaemonClient:
    mock = MagicMock(spec=DaemonClient)
    mock.status = AsyncMock(return_value={"uptime": 1.0, "active_runs": 0, "total_runs": 0})
    mock.list_runs = AsyncMock(return_value=[])
    return mock


class TestDaemonIntegration:
    def test_http_status_and_list(self, repo: Path) -> None:
        """Status endpoint works, list runs starts empty."""
        manager = RunManager(repo)
        client = TestClient(create_app(manager))

        resp = client.get("/api/status")
        assert resp.status_code == 200
        assert resp.json()["active_runs"] == 0

        resp = client.get("/api/runs")
        assert resp.json() == []

    @pytest.mark.asyncio()
    async def test_mcp_status_and_list(self, repo: Path, mock_client: DaemonClient) -> None:
        """MCP tools return expected results from DaemonClient."""
        root = str(repo)
        with (
            patch("orca.daemon.mcp_tools.check_daemon_running", return_value=True),
            patch("orca.daemon.mcp_tools.DaemonClient", return_value=mock_client),
        ):
            server = create_mcp_server()

            content_blocks, _ = await server.call_tool("orca_daemon_status", {"root": root})
            data = json.loads(_first_text(content_blocks))
            assert data["active_runs"] == 0

            content_blocks, _ = await server.call_tool("orca_list_runs", {"root": root})
            data = json.loads(_first_text(content_blocks))
            assert data == []

    @pytest.mark.asyncio()
    async def test_http_and_mcp_consistency(self, repo: Path, mock_client: DaemonClient) -> None:
        """HTTP and MCP return same data for the same queries."""
        root = str(repo)
        manager = RunManager(repo)
        http_client = TestClient(create_app(manager))

        # HTTP status
        http_status = http_client.get("/api/status").json()

        # MCP status (via mocked client returning same empty state)
        with (
            patch("orca.daemon.mcp_tools.check_daemon_running", return_value=True),
            patch("orca.daemon.mcp_tools.DaemonClient", return_value=mock_client),
        ):
            server = create_mcp_server()
            content_blocks, _ = await server.call_tool("orca_daemon_status", {"root": root})
            mcp_status = json.loads(_first_text(content_blocks))

            assert http_status["active_runs"] == mcp_status["active_runs"]
            assert http_status["total_runs"] == mcp_status["total_runs"]

            # HTTP list runs
            http_runs = http_client.get("/api/runs").json()

            # MCP list runs
            content_blocks, _ = await server.call_tool("orca_list_runs", {"root": root})
            mcp_runs = json.loads(_first_text(content_blocks))

            assert http_runs == mcp_runs
