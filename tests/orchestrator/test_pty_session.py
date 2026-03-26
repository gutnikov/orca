from __future__ import annotations

import asyncio
import subprocess

import pytest

from orca.orchestrator.pty_session import TmuxSession


def _tmux_available() -> bool:
    try:
        result = subprocess.run(["tmux", "-V"], capture_output=True)
        return result.returncode == 0
    except FileNotFoundError:
        return False


pytestmark = pytest.mark.skipif(not _tmux_available(), reason="tmux not installed")


@pytest.mark.asyncio()
async def test_spawn_and_capture() -> None:
    session = TmuxSession(session_name="test-spawn", cols=80, rows=24)
    try:
        await session.spawn("bash", ["-c", 'echo "hello tmux"; sleep 5'], cwd=".")
        await asyncio.sleep(1.0)
        output = session.capture_scrollback()
        assert "hello tmux" in output
    finally:
        session.close()


@pytest.mark.asyncio()
async def test_alive_property() -> None:
    session = TmuxSession(session_name="test-alive", cols=80, rows=24)
    try:
        await session.spawn("bash", ["-c", "sleep 5"], cwd=".")
        assert session.alive
    finally:
        session.close()
    assert not session.alive


@pytest.mark.asyncio()
async def test_wait_returns_on_exit() -> None:
    session = TmuxSession(session_name="test-wait", cols=80, rows=24)
    try:
        await session.spawn("bash", ["-c", 'echo "done"'], cwd=".")
        exit_code = await session.wait(timeout=5.0)
        assert exit_code == 0
    finally:
        session.close()
