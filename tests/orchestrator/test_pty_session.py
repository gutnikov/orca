from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path

import pytest
from rich.text import Text

from orca.orchestrator.pty_session import PtySession


@pytest.mark.asyncio()
async def test_spawn_and_read_output() -> None:
    """Spawn echo via pty, verify pyte screen captures the output."""
    session = PtySession(cols=80, rows=24)
    await session.spawn("python3", ["-c", 'print("hello pty")'], cwd=".")
    read_task = asyncio.create_task(session.read_loop())
    await asyncio.sleep(1.0)
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
    await asyncio.sleep(1.0)
    read_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await read_task
    assert not session.alive
    session.close()


@pytest.mark.asyncio()
async def test_resize_updates_screen_and_pty() -> None:
    """Resize updates pyte screen dimensions and sends TIOCSWINSZ."""
    session = PtySession(cols=80, rows=24)
    await session.spawn("python3", ["-c", "import time; time.sleep(2)"], cwd=".")
    session.resize(120, 40)
    assert session.screen.columns == 120
    assert session.screen.lines == 40
    session.close()


@pytest.mark.asyncio()
async def test_snapshot_returns_rich_text_lines() -> None:
    """Snapshot converts pyte screen to list of Rich Text objects."""
    session = PtySession(cols=80, rows=24)
    await session.spawn("python3", ["-c", 'print("snapshot test")'], cwd=".")
    read_task = asyncio.create_task(session.read_loop())
    await asyncio.sleep(1.0)
    read_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await read_task

    lines = session.snapshot()
    assert isinstance(lines, list)
    assert len(lines) > 0
    assert all(isinstance(line, Text) for line in lines)
    combined = "\n".join(str(line) for line in lines)
    assert "snapshot test" in combined
    session.close()


@pytest.mark.asyncio()
async def test_log_path_writes_raw_bytes(tmp_path: Path) -> None:
    """When log_path is provided, raw pty bytes are written to file."""
    log_file = tmp_path / "session.raw"
    session = PtySession(cols=80, rows=24)
    await session.spawn("python3", ["-c", 'print("logged output")'], cwd=".", log_path=log_file)
    read_task = asyncio.create_task(session.read_loop())
    await asyncio.sleep(1.0)
    read_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await read_task

    session.close()
    assert log_file.exists()
    content = log_file.read_bytes()
    assert b"logged output" in content
