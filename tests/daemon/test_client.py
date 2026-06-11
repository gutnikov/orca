"""Tests for DaemonClient — HTTP proxy to daemon Unix socket."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
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


@pytest.mark.asyncio
async def test_session_created_with_timeout(client: DaemonClient) -> None:
    """Every session must carry an explicit ClientTimeout so a wedged daemon
    can't hang the MCP/CLI caller forever."""
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={})
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    captured: dict[str, object] = {}

    def fake_session(*args: object, **kwargs: object) -> MagicMock:
        captured.update(kwargs)
        return mock_session

    with patch("aiohttp.ClientSession", side_effect=fake_session):
        await client.status()

    timeout = captured.get("timeout")
    assert isinstance(timeout, aiohttp.ClientTimeout)
    assert timeout.total == 30


@pytest.mark.asyncio
async def test_connection_error_translated_to_runtime_error(client: DaemonClient) -> None:
    with (
        patch("aiohttp.ClientSession", side_effect=aiohttp.ClientConnectionError("connection refused")),
        pytest.raises(RuntimeError, match="daemon unreachable"),
    ):
        await client.status()


@pytest.mark.asyncio
async def test_timeout_translated_to_runtime_error(client: DaemonClient) -> None:
    mock_resp = MagicMock()
    mock_resp.__aenter__ = AsyncMock(side_effect=TimeoutError())
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("aiohttp.ClientSession", return_value=mock_session),
        pytest.raises(RuntimeError, match="daemon unreachable"),
    ):
        await client.stop_run("my-run")


@pytest.mark.asyncio
async def test_text_endpoint_connection_error_translated(client: DaemonClient) -> None:
    with (
        patch("aiohttp.ClientSession", side_effect=aiohttp.ClientConnectionError("connection refused")),
        pytest.raises(RuntimeError, match="daemon unreachable"),
    ):
        await client.get_worker_log("my-run", "issue-1")
