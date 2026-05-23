"""Tests for DaemonClient — HTTP proxy to daemon Unix socket."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from orca.daemon.client import DaemonClient


@pytest.fixture
def client(tmp_path: Path) -> DaemonClient:
    sock = tmp_path / ".orca-state" / "daemon.sock"
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

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        result = await client.status()

    assert result == {"uptime": 10.0, "active_runs": 1, "total_runs": 2}
    mock_session.get.assert_called_once_with("http://localhost/api/status")


@pytest.mark.asyncio
async def test_list_runs(client: DaemonClient) -> None:
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value=[{"run_id": "main:default", "status": "running"}])
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_resp)
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

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_resp)
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

    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        result = await client.start_run("task.md", workflow="prd")

    assert result["run_id"] == "feat:default"
    mock_session.post.assert_called_once_with(
        "http://localhost/api/runs/start",
        json={"task_file": "task.md", "workflow": "prd", "branch": None, "run_id": None, "debug": False},
    )


@pytest.mark.asyncio
async def test_stop_run(client: DaemonClient) -> None:
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={"status": "stopped"})
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        result = await client.stop_run("my-run")

    assert result == {"status": "stopped"}
    mock_session.post.assert_called_once_with("http://localhost/api/runs/my-run/stop", json=None)
