from __future__ import annotations

import asyncio
import contextlib

import pytest

from orca.orchestrator.pty_session import PtySession


@pytest.mark.asyncio()
async def test_spawn_and_read_output() -> None:
    """Spawn echo via pty, verify pyte screen captures the output."""
    session = PtySession(cols=80, rows=24)
    await session.spawn("python3", ["-c", 'print("hello pty")'], cwd=".")
    read_task = asyncio.create_task(session.read_loop())
    await asyncio.sleep(0.5)
    read_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await read_task

    screen_text = ""
    for row in range(session.screen.lines):
        line = session.screen.display[row].rstrip()
        if line:
            screen_text += line + "\n"
    assert "hello pty" in screen_text
    session.close()


@pytest.mark.asyncio()
async def test_alive_property() -> None:
    """Session reports alive correctly."""
    session = PtySession(cols=80, rows=24)
    await session.spawn("python3", ["-c", 'print("done")'], cwd=".")
    read_task = asyncio.create_task(session.read_loop())
    await asyncio.sleep(0.5)
    read_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await read_task
    assert not session.alive
    session.close()
