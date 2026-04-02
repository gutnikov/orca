# MCP Daemon Proxy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `orca mcp` proxy all tool calls to the running daemon's HTTP API over the Unix socket, instead of creating a separate in-process RunManager.

**Architecture:** Replace the `RunManager` dependency in `mcp_tools.py` with a `DaemonClient` class that makes aiohttp requests to the daemon's Unix socket. The MCP tool signatures and return values stay identical — only the backing implementation changes from direct method calls to HTTP calls.

**Tech Stack:** aiohttp (already used for daemon communication), FastMCP, existing daemon HTTP API

---

### Task 1: Create DaemonClient — the HTTP proxy to the daemon

**Files:**
- Create: `src/orca/daemon/client.py`
- Test: `tests/daemon/test_client.py`

The `DaemonClient` wraps aiohttp Unix socket calls to the daemon HTTP API. Each method maps 1:1 to an HTTP endpoint. The codebase already uses `aiohttp.UnixConnector` this way in `run_cmd.py`, `stop_cmd.py`, `list_cmd.py`, etc.

- [ ] **Step 1: Write the failing test for DaemonClient.status()**

```python
# tests/daemon/test_client.py
"""Tests for DaemonClient — HTTP proxy to daemon Unix socket."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from orca.daemon.client import DaemonClient


@pytest.fixture
def client(tmp_path: Path) -> DaemonClient:
    sock = tmp_path / ".orca" / "daemon.sock"
    sock.parent.mkdir(parents=True)
    sock.touch()
    return DaemonClient(sock)


@pytest.mark.asyncio
async def test_status(client: DaemonClient) -> None:
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={"uptime": 10.0, "active_runs": 1, "total_runs": 2})
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        result = await client.status()

    assert result == {"uptime": 10.0, "active_runs": 1, "total_runs": 2}
    mock_session.get.assert_called_once_with("http://localhost/api/status")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/daemon/test_client.py::test_status -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'orca.daemon.client'`

- [ ] **Step 3: Implement DaemonClient with all methods**

```python
# src/orca/daemon/client.py
"""HTTP client that proxies to the orca daemon over its Unix socket."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import aiohttp


class DaemonClient:
    """Proxy to the orca daemon HTTP API via Unix socket."""

    def __init__(self, socket_path: Path) -> None:
        self._socket_path = socket_path

    def _connector(self) -> aiohttp.UnixConnector:
        return aiohttp.UnixConnector(path=str(self._socket_path))

    async def _get_json(self, path: str) -> dict[str, Any]:
        async with (
            aiohttp.ClientSession(connector=self._connector()) as session,
            session.get(f"http://localhost{path}") as resp,
        ):
            return await resp.json()  # type: ignore[no-any-return]

    async def _get_text(self, path: str) -> str:
        async with (
            aiohttp.ClientSession(connector=self._connector()) as session,
            session.get(f"http://localhost{path}") as resp,
        ):
            return await resp.text()

    async def _post_json(self, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        async with (
            aiohttp.ClientSession(connector=self._connector()) as session,
            session.post(f"http://localhost{path}", json=body) as resp,
        ):
            return await resp.json()  # type: ignore[no-any-return]

    async def status(self) -> dict[str, Any]:
        return await self._get_json("/api/status")

    async def list_runs(self) -> list[dict[str, Any]]:
        return await self._get_json("/api/runs")  # type: ignore[return-value]

    async def get_run(self, run_id: str) -> dict[str, Any]:
        return await self._get_json(f"/api/runs/{run_id}")

    async def get_issue(self, run_id: str, issue_id: str) -> dict[str, Any]:
        return await self._get_json(f"/api/runs/{run_id}/issues/{issue_id}")

    async def get_insights(self, run_id: str) -> str:
        return await self._get_text(f"/api/runs/{run_id}/insights")

    async def get_worker_log(self, run_id: str, issue_id: str, tail: int = 100) -> str:
        return await self._get_text(f"/api/runs/{run_id}/logs/{issue_id}?tail={tail}")

    async def start_run(
        self,
        task_file: str,
        workflow: str | None = None,
        branch: str | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        return await self._post_json(
            "/api/runs/start",
            {"task_file": task_file, "workflow": workflow, "branch": branch, "run_id": run_id},
        )

    async def stop_run(self, run_id: str) -> dict[str, Any]:
        return await self._post_json(f"/api/runs/{run_id}/stop")

    async def drop_run(self, run_id: str) -> dict[str, Any]:
        return await self._post_json(f"/api/runs/{run_id}/drop")

    async def resume_run(self, run_id: str) -> dict[str, Any]:
        return await self._post_json(f"/api/runs/{run_id}/resume")

    async def retry_issue(self, run_id: str, issue_id: str) -> dict[str, Any]:
        return await self._post_json(f"/api/runs/{run_id}/retry/{issue_id}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/daemon/test_client.py::test_status -v`
Expected: PASS

- [ ] **Step 5: Add remaining tests**

```python
# Append to tests/daemon/test_client.py

@pytest.mark.asyncio
async def test_list_runs(client: DaemonClient) -> None:
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value=[{"run_id": "main:default", "status": "running"}])
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        result = await client.list_runs()

    assert result == [{"run_id": "main:default", "status": "running"}]
    mock_session.get.assert_called_once_with("http://localhost/api/runs")


@pytest.mark.asyncio
async def test_get_insights_returns_text(client: DaemonClient) -> None:
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.text = AsyncMock(return_value="insight line 1\ninsight line 2")
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        result = await client.get_insights("my-run")

    assert result == "insight line 1\ninsight line 2"
    mock_session.get.assert_called_once_with("http://localhost/api/runs/my-run/insights")


@pytest.mark.asyncio
async def test_start_run_posts_body(client: DaemonClient) -> None:
    mock_resp = AsyncMock()
    mock_resp.status = 201
    mock_resp.json = AsyncMock(return_value={"run_id": "feat:default", "status": "running"})
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.post = AsyncMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        result = await client.start_run("task.md", workflow="prd")

    assert result["run_id"] == "feat:default"
    mock_session.post.assert_called_once_with(
        "http://localhost/api/runs/start",
        json={"task_file": "task.md", "workflow": "prd", "branch": None, "run_id": None},
    )


@pytest.mark.asyncio
async def test_stop_run(client: DaemonClient) -> None:
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={"status": "stopped"})
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.post = AsyncMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        result = await client.stop_run("my-run")

    assert result == {"status": "stopped"}
    mock_session.post.assert_called_once_with("http://localhost/api/runs/my-run/stop", json=None)
```

- [ ] **Step 6: Run all client tests**

Run: `uv run pytest tests/daemon/test_client.py -v`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add src/orca/daemon/client.py tests/daemon/test_client.py
git commit -m "feat(daemon): add DaemonClient HTTP proxy for Unix socket"
```

---

### Task 2: Rewrite mcp_tools.py to use DaemonClient instead of RunManager

**Files:**
- Modify: `src/orca/daemon/mcp_tools.py`

The MCP tool function signatures and docstrings stay the same. Only the implementation body changes: instead of calling `manager.method()`, call `await client.method()` and return the JSON result.

- [ ] **Step 1: Rewrite `create_mcp_server` to accept `DaemonClient`**

Replace the entire contents of `src/orca/daemon/mcp_tools.py`:

```python
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
```

- [ ] **Step 2: Run linter and type checker**

Run: `uv run ruff check src/orca/daemon/mcp_tools.py && uv run mypy src/orca/daemon/mcp_tools.py`
Expected: PASS (no errors)

- [ ] **Step 3: Commit**

```bash
git add src/orca/daemon/mcp_tools.py
git commit -m "refactor(mcp): replace RunManager with DaemonClient in MCP tools"
```

---

### Task 3: Update mcp_cmd.py to use DaemonClient

**Files:**
- Modify: `src/orca/cli/mcp_cmd.py`

- [ ] **Step 1: Rewrite mcp_command to create DaemonClient instead of RunManager**

Replace the entire contents of `src/orca/cli/mcp_cmd.py`:

```python
"""orca mcp — MCP stdio bridge to the daemon."""

from __future__ import annotations

import sys


def mcp_command() -> None:
    """Create an MCP server backed by DaemonClient, run on stdio transport."""
    from orca.cli.daemon_cmd import _repo_root
    from orca.daemon.client import DaemonClient
    from orca.daemon.lifecycle import check_daemon_running, socket_path
    from orca.daemon.mcp_tools import create_mcp_server

    repo = _repo_root()
    if not check_daemon_running(repo):
        print("Error: daemon is not running. Start it with: orca daemon start", file=sys.stderr)
        raise SystemExit(1)

    client = DaemonClient(socket_path(repo))
    server = create_mcp_server(client)
    server.run(transport="stdio")
```

- [ ] **Step 2: Run linter and type checker**

Run: `uv run ruff check src/orca/cli/mcp_cmd.py && uv run mypy src/orca/cli/mcp_cmd.py`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add src/orca/cli/mcp_cmd.py
git commit -m "feat(mcp): wire mcp_command to DaemonClient instead of in-process RunManager"
```

---

### Task 4: Update daemon server.py to pass RunManager (not DaemonClient) to create_mcp_server

**Files:**
- Modify: `src/orca/daemon/server.py` (if it calls `create_mcp_server` directly)

The daemon's internal server uses `create_mcp_server` with a `RunManager`. Since we changed the signature to accept `DaemonClient`, we need to check if `server.py` calls it. If it does, either keep a separate code path or remove the daemon-internal MCP usage (since MCP is only used via the stdio bridge).

- [ ] **Step 1: Check if server.py uses create_mcp_server**

Read `src/orca/daemon/server.py` and check for any `create_mcp_server` import/usage. Based on the exploration, `server.py` uses `create_app(manager)` from `http_api.py` — not `create_mcp_server`. So no changes needed here.

If confirmed: skip to commit. If `server.py` does call `create_mcp_server`, remove that call (the MCP server is only used via stdio).

- [ ] **Step 2: Run full test suite**

Run: `uv run pytest -x -v`
Expected: All pass

- [ ] **Step 3: Run linter and type checker on full project**

Run: `uv run ruff check . && uv run mypy src/`
Expected: PASS

- [ ] **Step 4: Commit (if any changes)**

```bash
git commit -m "chore: clean up server.py MCP references if needed"
```

---

### Task 5: Smoke test the MCP stdio bridge end-to-end

**Files:** None (manual verification)

- [ ] **Step 1: Verify daemon is running**

Run: `cd /Users/agutnikov/work/projects/sme-web/sme-web && orca runs`
Expected: Shows the running SMEW-1942 run

- [ ] **Step 2: Test MCP stdio protocol**

Run:
```bash
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}
{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}
{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"orca_list_runs","arguments":{}}}' | /Users/agutnikov/work/orca/bin/orca-mcp.sh 2>/dev/null
```

Expected: Third JSON response contains the running SMEW-1942 run data (not an empty array)

- [ ] **Step 3: Reconnect MCP in Claude Code**

Run: `/mcp` in Claude Code, reconnect the orca server
Then call `orca_list_runs` — should show the active run

- [ ] **Step 4: Commit all work if not already committed**

```bash
git add -A
git commit -m "feat(mcp): MCP stdio bridge proxies to daemon HTTP API"
```
