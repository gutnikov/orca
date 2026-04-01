from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.testclient import TestClient

from orca.daemon.client import DaemonClient
from orca.daemon.http_api import create_app
from orca.daemon.manager import RunManager
from orca.daemon.mcp_tools import create_mcp_server


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
    async def test_mcp_status_and_list(self, mock_client: DaemonClient) -> None:
        """MCP tools return expected results from DaemonClient."""
        server = create_mcp_server(mock_client)

        content_blocks, _ = await server.call_tool("orca_daemon_status", {})
        data = json.loads(content_blocks[0].text)
        assert data["active_runs"] == 0

        content_blocks, _ = await server.call_tool("orca_list_runs", {})
        data = json.loads(content_blocks[0].text)
        assert data == []

    @pytest.mark.asyncio()
    async def test_http_and_mcp_consistency(self, repo: Path, mock_client: DaemonClient) -> None:
        """HTTP and MCP return same data for the same queries."""
        manager = RunManager(repo)
        http_client = TestClient(create_app(manager))

        # HTTP status
        http_status = http_client.get("/api/status").json()

        # MCP status (via mocked client returning same empty state)
        server = create_mcp_server(mock_client)
        content_blocks, _ = await server.call_tool("orca_daemon_status", {})
        mcp_status = json.loads(content_blocks[0].text)

        assert http_status["active_runs"] == mcp_status["active_runs"]
        assert http_status["total_runs"] == mcp_status["total_runs"]

        # HTTP list runs
        http_runs = http_client.get("/api/runs").json()

        # MCP list runs
        content_blocks, _ = await server.call_tool("orca_list_runs", {})
        mcp_runs = json.loads(content_blocks[0].text)

        assert http_runs == mcp_runs
