from __future__ import annotations

import asyncio
import subprocess

import pytest

from orca.orchestrator.pty_session import _TMUX_PREFIX, TmuxSession


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


def test_build_tmux_args_no_cast_uses_plain_command():
    session = TmuxSession(session_name="abc", cols=120, rows=40)
    args = session._build_tmux_args("export FOO='bar'; claude --x")
    name = f"{_TMUX_PREFIX}abc"
    assert args == [
        "tmux",
        "new-session",
        "-d",
        "-s",
        name,
        "-x",
        "120",
        "-y",
        "40",
        "export FOO='bar'; claude --x",
    ]


def test_build_tmux_args_with_cast_wraps_in_asciinema():
    session = TmuxSession(session_name="abc", cast_path="/tmp/run/plan-20260530.cast")
    full_cmd = "export FOO='bar'; cat /tmp/.prompt | claude --x"
    args = session._build_tmux_args(full_cmd)
    # full_cmd survives intact as ONE argument after --command
    assert args[-1] == "/tmp/run/plan-20260530.cast"
    assert "asciinema" in args
    assert "--command" in args
    cmd_idx = args.index("--command")
    assert args[cmd_idx + 1] == full_cmd
    assert "-q" in args
    assert "asciicast-v2" in args
    # never headless — would blank out capture-pane
    assert "--headless" not in args


def test_update_cast_path_sets_field(tmp_path):
    from orca.orchestrator.session_sync import SessionManifest

    manifest = SessionManifest(run_dir=tmp_path)
    manifest.append(
        issue_id="i1",
        state="plan",
        session_id="s1",
        worktree_path="/wt",
        started_at="2026-05-30T00:00:00Z",
    )
    manifest.update_cast_path("s1", "/wt/.orca-state/sessions/plan-x.cast")
    entry = manifest.read()[0]
    assert entry["cast_path"] == "/wt/.orca-state/sessions/plan-x.cast"
