from __future__ import annotations

import json
from pathlib import Path

import pytest
from starlette.testclient import TestClient

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
      done: complete
  complete:
    terminal: true
initial: todo
"""
    (tmp_path / "orca.yml").write_text(config)
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "todo.md").write_text("Do: {{ issue.title }}")
    (tmp_path / "task.md").write_text("title: Integration test task")
    return tmp_path


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
    async def test_mcp_status_and_list(self, repo: Path) -> None:
        """MCP tools match HTTP API results."""
        manager = RunManager(repo)
        server = create_mcp_server(manager)

        content_blocks, _ = await server.call_tool("orca_daemon_status", {})
        data = json.loads(content_blocks[0].text)
        assert data["active_runs"] == 0

        content_blocks, _ = await server.call_tool("orca_list_runs", {})
        data = json.loads(content_blocks[0].text)
        assert data == []

    @pytest.mark.asyncio()
    async def test_http_and_mcp_consistency(self, repo: Path) -> None:
        """HTTP and MCP return same data for the same queries."""
        manager = RunManager(repo)
        client = TestClient(create_app(manager))
        server = create_mcp_server(manager)

        # HTTP status
        http_status = client.get("/api/status").json()

        # MCP status
        content_blocks, _ = await server.call_tool("orca_daemon_status", {})
        mcp_status = json.loads(content_blocks[0].text)

        assert http_status["active_runs"] == mcp_status["active_runs"]
        assert http_status["total_runs"] == mcp_status["total_runs"]

        # HTTP list runs
        http_runs = client.get("/api/runs").json()

        # MCP list runs
        content_blocks, _ = await server.call_tool("orca_list_runs", {})
        mcp_runs = json.loads(content_blocks[0].text)

        assert http_runs == mcp_runs
