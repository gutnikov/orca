from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from orca.engine.types import DispatchWorkerEffect
from orca.orchestrator.worker import (
    KIND_REGISTRY,
    CliAgentWorker,
    KindConfig,
    WorkerFailure,
    WorkerSuccess,
    parse_progress,
)


def _make_effect(state: str = "implementing") -> DispatchWorkerEffect:
    return DispatchWorkerEffect(
        issue_id="issue-1",
        issue_type="default",
        state=state,
        result_format={
            "outcome": {"type": "enum", "values": ["done"], "description": "Outcome"},
            "summary": {"type": "string", "description": "Summary", "required_when": ["done"]},
        },
        issue={"fields": {"title": "Test"}, "event_log": [], "decomposed_from": None, "depends_on": [], "children": []},
    )


def _make_polling_pty(
    *,
    alive_count: int = 0,
    write_result: dict[str, Any] | None = None,
    result_path: Path | None = None,
    write_after_spawns: int = 0,
) -> MagicMock:
    """Create a mock PtySession for the polling-based worker.

    Args:
        alive_count: How many times .alive returns True before returning False.
            0 means session exits immediately after spawn.
        write_result: If set, write this JSON to result_path.
        result_path: Where to write the result file.
        write_after_spawns: Write result file after this many .alive checks.
            0 means write on spawn. Only used if write_result is set.
    """
    pty = MagicMock()
    pty.session_name = "mock-session"

    call_count = 0
    written = False

    def _alive_side_effect() -> bool:
        nonlocal call_count, written
        call_count += 1
        if not written and write_result is not None and result_path is not None and call_count > write_after_spawns:
            result_path.write_text(json.dumps(write_result))
            written = True
        return call_count <= alive_count

    type(pty).alive = property(lambda self: _alive_side_effect())

    async def _spawn(*args: Any, **kwargs: Any) -> None:
        nonlocal written
        if write_after_spawns == 0 and write_result is not None and result_path is not None:
            result_path.write_text(json.dumps(write_result))
            written = True

    pty.spawn = AsyncMock(side_effect=_spawn)
    pty.kill = MagicMock()
    pty.close = MagicMock()
    return pty


def _make_mock_pty(
    *,
    exit_code: int = 0,
    write_result: dict[str, Any] | None = None,
    result_path: Path | None = None,
) -> MagicMock:
    """Create a simple mock PtySession that writes result on spawn and exits immediately."""
    pty = MagicMock()
    pty.session_name = "mock-session"

    async def _spawn(*args: Any, **kwargs: Any) -> None:
        if write_result is not None and result_path is not None:
            result_path.write_text(json.dumps(write_result))

    pty.spawn = AsyncMock(side_effect=_spawn)
    type(pty).alive = property(lambda self: False)
    pty.kill = MagicMock()
    pty.close = MagicMock()
    return pty


@pytest.mark.asyncio()
class TestCommandAssembly:
    """Verify CliAgentWorker builds the correct CLI command per kind."""

    async def _spawn_and_capture(
        self,
        kind_config: KindConfig,
        tmp_path: Path,
        model: str | None = None,
        extra_args: list[str] | None = None,
    ) -> tuple[str, list[str], bytes | None]:
        """Run worker with a mock pty that captures spawn args. Returns (cmd, args, stdin_data)."""
        effect = _make_effect()
        result_path = tmp_path / "result.json"
        prompt_path = tmp_path / "prompt.md"
        prompt_path.write_text("Do the thing")
        valid_result: dict[str, Any] = {"outcome": "done", "summary": "All done"}
        pty = _make_mock_pty(exit_code=0, write_result=valid_result, result_path=result_path)

        worker = CliAgentWorker(repo_root=tmp_path, kind_config=kind_config)
        await worker.execute(
            effect,
            tmp_path,
            result_path,
            prompt_path,
            pty_session=pty,
            model=model,
            extra_args=extra_args,
        )
        call_args = pty.spawn.call_args
        return call_args[0][0], list(call_args[0][1]), call_args[1].get("stdin_data")

    async def test_claude_code_command(self, tmp_path: Path) -> None:
        kind_config = KIND_REGISTRY["claude-code"]
        cmd, args, stdin_data = await self._spawn_and_capture(kind_config, tmp_path)
        assert cmd == "claude"
        assert "--dangerously-skip-permissions" in args
        assert "--max-turns" in args
        assert "50" in args
        assert stdin_data is not None
        assert len(stdin_data) > 0

    async def test_opencode_command(self, tmp_path: Path) -> None:
        kind_config = KIND_REGISTRY["opencode"]
        cmd, args, stdin_data = await self._spawn_and_capture(
            kind_config, tmp_path, model="anthropic/claude-sonnet-4-5"
        )
        assert cmd == "opencode"
        assert args[0] == "run"
        # Prompt is the second arg (positional after subcommand)
        assert len(args[1]) > 0  # prompt text
        assert "-m" in args
        assert "anthropic/claude-sonnet-4-5" in args
        assert stdin_data is None

    async def test_extra_args_appended(self, tmp_path: Path) -> None:
        kind_config = KIND_REGISTRY["claude-code"]
        cmd, args, stdin_data = await self._spawn_and_capture(
            kind_config,
            tmp_path,
            extra_args=["--verbose"],
        )
        assert "--verbose" in args
        # Default args still present
        assert "--dangerously-skip-permissions" in args

    async def test_model_ignored_when_none(self, tmp_path: Path) -> None:
        kind_config = KIND_REGISTRY["claude-code"]
        cmd, args, stdin_data = await self._spawn_and_capture(kind_config, tmp_path, model=None)
        assert "-m" not in args


@pytest.mark.asyncio()
class TestCliAgentWorker:
    async def test_result_detected_while_alive(self, tmp_path: Path) -> None:
        """Result file appears while session is alive -> WorkerSuccess, session killed."""
        effect = _make_effect()
        result_path = tmp_path / "result.json"
        prompt_path = tmp_path / "prompt.md"
        prompt_path.write_text("Do the thing")

        valid_result: dict[str, Any] = {"outcome": "done", "summary": "All done"}
        # Session stays alive (alive_count=3), result written after 1 alive check
        pty = _make_polling_pty(
            alive_count=3,
            write_result=valid_result,
            result_path=result_path,
            write_after_spawns=1,
        )

        worker = CliAgentWorker(repo_root=tmp_path, kind_config=KIND_REGISTRY["claude-code"])
        outcome = await worker.execute(effect, tmp_path, result_path, prompt_path, pty_session=pty)

        assert isinstance(outcome, WorkerSuccess)
        assert outcome.result == valid_result
        pty.kill.assert_called_once()

    async def test_timeout_no_result(self, tmp_path: Path) -> None:
        """Session stays alive, no result written -> timeout -> WorkerFailure."""
        effect = _make_effect()
        result_path = tmp_path / "result.json"
        prompt_path = tmp_path / "prompt.md"
        prompt_path.write_text("Do the thing")

        # Session stays alive forever (high alive_count), no result written
        pty = _make_polling_pty(alive_count=9999)

        worker = CliAgentWorker(repo_root=tmp_path, kind_config=KIND_REGISTRY["claude-code"])
        # Use inactivity_timeout=0 for immediate timeout
        outcome = await worker.execute(
            effect, tmp_path, result_path, prompt_path, inactivity_timeout=0, pty_session=pty
        )

        assert isinstance(outcome, WorkerFailure)

    async def test_session_exits_no_result(self, tmp_path: Path) -> None:
        """Session exits naturally with no result file -> WorkerFailure."""
        effect = _make_effect()
        result_path = tmp_path / "result.json"
        prompt_path = tmp_path / "prompt.md"
        prompt_path.write_text("Do the thing")

        # Session exits immediately (alive_count=0), no result written
        pty = _make_polling_pty(alive_count=0)

        worker = CliAgentWorker(repo_root=tmp_path, kind_config=KIND_REGISTRY["claude-code"])
        outcome = await worker.execute(effect, tmp_path, result_path, prompt_path, pty_session=pty)

        assert isinstance(outcome, WorkerFailure)

    async def test_invalid_result_validation(self, tmp_path: Path) -> None:
        """Result file has missing required field -> WorkerFailure."""
        effect = _make_effect()
        result_path = tmp_path / "result.json"
        prompt_path = tmp_path / "prompt.md"
        prompt_path.write_text("Do the thing")

        invalid_result: dict[str, Any] = {"outcome": "done"}  # missing required summary
        # Session exits immediately, result written on spawn
        pty = _make_polling_pty(alive_count=0, write_result=invalid_result, result_path=result_path)

        worker = CliAgentWorker(repo_root=tmp_path, kind_config=KIND_REGISTRY["claude-code"])
        outcome = await worker.execute(effect, tmp_path, result_path, prompt_path, pty_session=pty)

        assert isinstance(outcome, WorkerFailure)
        assert "summary" in outcome.error

    async def test_previous_result_file_deleted(self, tmp_path: Path) -> None:
        """Stale result deleted, session exits with no new result -> WorkerFailure."""
        effect = _make_effect()
        result_path = tmp_path / "result.json"
        prompt_path = tmp_path / "prompt.md"
        prompt_path.write_text("Do the thing")

        # Write stale result file before running
        stale_result: dict[str, Any] = {"outcome": "done", "summary": "Stale"}
        result_path.write_text(json.dumps(stale_result))

        # Session exits immediately, writes nothing new — stale file was deleted by worker
        pty = _make_polling_pty(alive_count=0)

        worker = CliAgentWorker(repo_root=tmp_path, kind_config=KIND_REGISTRY["claude-code"])
        outcome = await worker.execute(effect, tmp_path, result_path, prompt_path, pty_session=pty)

        assert isinstance(outcome, WorkerFailure)

    async def test_session_exits_with_valid_result(self, tmp_path: Path) -> None:
        """Session exits naturally with valid result -> WorkerSuccess, kill NOT called."""
        effect = _make_effect()
        result_path = tmp_path / "result.json"
        prompt_path = tmp_path / "prompt.md"
        prompt_path.write_text("Do the thing")

        valid_result: dict[str, Any] = {"outcome": "done", "summary": "All done"}
        # Session exits immediately (alive_count=0), result written on spawn
        pty = _make_polling_pty(alive_count=0, write_result=valid_result, result_path=result_path)

        worker = CliAgentWorker(repo_root=tmp_path, kind_config=KIND_REGISTRY["claude-code"])
        outcome = await worker.execute(effect, tmp_path, result_path, prompt_path, pty_session=pty)

        assert isinstance(outcome, WorkerSuccess)
        assert outcome.result == valid_result
        pty.kill.assert_not_called()

    async def test_env_passed_to_pty_session(self, tmp_path: Path) -> None:
        """Verify env dict is forwarded to pty_session.spawn."""
        effect = _make_effect()
        result_path = tmp_path / "result.json"
        prompt_path = tmp_path / "prompt.md"
        prompt_path.write_text("Do the thing")

        valid_result: dict[str, Any] = {"outcome": "done", "summary": "All done"}
        pty = _make_mock_pty(exit_code=0, write_result=valid_result, result_path=result_path)

        env = {"SLACK_HITL_MCP_URL": "http://127.0.0.1:9999/sse"}
        worker = CliAgentWorker(repo_root=tmp_path, kind_config=KIND_REGISTRY["claude-code"])
        await worker.execute(effect, tmp_path, result_path, prompt_path, pty_session=pty, env=env)

        # Verify env was passed to spawn
        pty.spawn.assert_called_once()
        spawn_kwargs = pty.spawn.call_args.kwargs
        assert spawn_kwargs.get("env") == env


class TestParseProgress:
    def test_basic_marker(self) -> None:
        scrollback = "some output\n<!-- PROGRESS: 42 | Writing tests -->\nmore output"
        result = parse_progress(scrollback)
        assert result == (42, "Writing tests")

    def test_last_marker_wins(self) -> None:
        scrollback = "<!-- PROGRESS: 10 | Starting -->\nwork\n<!-- PROGRESS: 75 | Almost done -->"
        result = parse_progress(scrollback)
        assert result == (75, "Almost done")

    def test_no_marker(self) -> None:
        scrollback = "just normal output with no markers"
        result = parse_progress(scrollback)
        assert result is None

    def test_marker_without_status(self) -> None:
        scrollback = "<!-- PROGRESS: 50 -->"
        result = parse_progress(scrollback)
        assert result == (50, None)

    def test_clamps_to_100(self) -> None:
        scrollback = "<!-- PROGRESS: 150 | Overshot -->"
        result = parse_progress(scrollback)
        assert result == (100, "Overshot")

    def test_zero_progress(self) -> None:
        scrollback = "<!-- PROGRESS: 0 | Just started -->"
        result = parse_progress(scrollback)
        assert result == (0, "Just started")

    def test_whitespace_tolerance(self) -> None:
        scrollback = "<!--  PROGRESS:  68  |  Exploring sidebar...  -->"
        result = parse_progress(scrollback)
        assert result == (68, "Exploring sidebar...")

    def test_marker_with_ansi_codes(self) -> None:
        """Scrollback from tmux may contain ANSI escape sequences around the marker."""
        scrollback = "\x1b[0m<!-- PROGRESS: 30 | Parsing files -->\x1b[0m"
        result = parse_progress(scrollback)
        assert result == (30, "Parsing files")


@pytest.mark.asyncio()
class TestWorkerBlocking:
    """Tests for the blocked outcome detection and unblock mechanism."""

    @pytest.fixture(autouse=True)
    def _fast_poll(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import orca.orchestrator.worker as _mod

        monkeypatch.setattr(_mod, "_POLL_INTERVAL", 0.05)
        monkeypatch.setattr(_mod, "_RESULT_GRACE_PERIOD", 0.1)

    async def test_blocked_outcome_pauses_and_unblocks(self, tmp_path: Path) -> None:
        """Worker writes blocked, then gets unblocked, then writes real result."""
        effect = _make_effect()
        result_path = tmp_path / "result.json"
        prompt_path = tmp_path / "prompt.md"
        prompt_path.write_text("Do the thing")

        unblock_event = asyncio.Event()
        unblock_message: list[str] = []

        pty = MagicMock()
        pty.session_name = "mock-session"
        pty.kill = MagicMock()
        pty.close = MagicMock()
        pty.send_keys = MagicMock(return_value=True)
        type(pty).alive = property(lambda self: True)

        async def _spawn(*args: Any, **kwargs: Any) -> None:
            result_path.write_text(json.dumps({"outcome": "waiting"}))

        pty.spawn = AsyncMock(side_effect=_spawn)

        worker = CliAgentWorker(repo_root=tmp_path, kind_config=KIND_REGISTRY["claude-code"])

        # Schedule unblock after a short delay
        async def _delayed_unblock() -> None:
            await asyncio.sleep(0.1)
            # Write the real result before setting the event
            result_path.write_text(json.dumps({"outcome": "done", "summary": "Finished"}))
            unblock_message.clear()
            unblock_message.append("PR merged, continue")
            unblock_event.set()

        task = asyncio.create_task(_delayed_unblock())

        outcome = await worker.execute(
            effect,
            tmp_path,
            result_path,
            prompt_path,
            pty_session=pty,
            unblock_event=unblock_event,
            unblock_message=unblock_message,
        )

        await task
        assert isinstance(outcome, WorkerSuccess)
        assert outcome.result["outcome"] == "done"
        pty.send_keys.assert_called_once_with("PR merged, continue")

    async def test_blocked_session_dies_returns_failure(self, tmp_path: Path) -> None:
        """If session dies while blocked, return WorkerFailure."""
        effect = _make_effect()
        result_path = tmp_path / "result.json"
        prompt_path = tmp_path / "prompt.md"
        prompt_path.write_text("Do the thing")

        unblock_event = asyncio.Event()
        unblock_message: list[str] = []

        alive_checks = 0

        pty = MagicMock()
        pty.session_name = "mock-session"
        pty.kill = MagicMock()
        pty.close = MagicMock()
        pty.send_keys = MagicMock(return_value=True)

        def _alive() -> bool:
            nonlocal alive_checks
            alive_checks += 1
            # Alive for first 2 checks, then dies in blocked sub-loop
            return alive_checks <= 2

        type(pty).alive = property(lambda self: _alive())

        async def _spawn(*args: Any, **kwargs: Any) -> None:
            result_path.write_text(json.dumps({"outcome": "waiting"}))

        pty.spawn = AsyncMock(side_effect=_spawn)

        worker = CliAgentWorker(repo_root=tmp_path, kind_config=KIND_REGISTRY["claude-code"])
        outcome = await worker.execute(
            effect,
            tmp_path,
            result_path,
            prompt_path,
            pty_session=pty,
            unblock_event=unblock_event,
            unblock_message=unblock_message,
        )

        assert isinstance(outcome, WorkerFailure)
        assert "waiting" in outcome.error

    async def test_blocked_without_unblock_event_treated_as_stale(self, tmp_path: Path) -> None:
        """Without unblock_event, blocked outcome is unknown -> stale -> deleted -> timeout."""
        effect = _make_effect()
        result_path = tmp_path / "result.json"
        prompt_path = tmp_path / "prompt.md"
        prompt_path.write_text("Do the thing")

        pty = _make_polling_pty(alive_count=9999)

        async def _spawn(*args: Any, **kwargs: Any) -> None:
            result_path.write_text(json.dumps({"outcome": "waiting"}))

        pty.spawn = AsyncMock(side_effect=_spawn)

        worker = CliAgentWorker(repo_root=tmp_path, kind_config=KIND_REGISTRY["claude-code"])
        outcome = await worker.execute(
            effect,
            tmp_path,
            result_path,
            prompt_path,
            inactivity_timeout=0,
            pty_session=pty,
        )

        assert isinstance(outcome, WorkerFailure)

    async def test_on_blocked_callback_called(self, tmp_path: Path) -> None:
        """on_blocked callback is called when worker enters blocked state."""
        effect = _make_effect()
        result_path = tmp_path / "result.json"
        prompt_path = tmp_path / "prompt.md"
        prompt_path.write_text("Do the thing")

        unblock_event = asyncio.Event()
        unblock_message: list[str] = []
        blocked_called = False
        unblocked_called_with: str | None = None

        def _on_blocked(reason: str) -> None:
            nonlocal blocked_called
            blocked_called = True

        def _on_unblocked(msg: str) -> None:
            nonlocal unblocked_called_with
            unblocked_called_with = msg

        pty = MagicMock()
        pty.session_name = "mock-session"
        pty.kill = MagicMock()
        pty.close = MagicMock()
        pty.send_keys = MagicMock(return_value=True)
        type(pty).alive = property(lambda self: True)

        async def _spawn(*args: Any, **kwargs: Any) -> None:
            result_path.write_text(json.dumps({"outcome": "waiting"}))

        pty.spawn = AsyncMock(side_effect=_spawn)

        worker = CliAgentWorker(repo_root=tmp_path, kind_config=KIND_REGISTRY["claude-code"])

        async def _delayed_unblock() -> None:
            await asyncio.sleep(0.1)
            result_path.write_text(json.dumps({"outcome": "done", "summary": "ok"}))
            unblock_message.clear()
            unblock_message.append("go")
            unblock_event.set()

        task = asyncio.create_task(_delayed_unblock())

        outcome = await worker.execute(
            effect,
            tmp_path,
            result_path,
            prompt_path,
            pty_session=pty,
            unblock_event=unblock_event,
            unblock_message=unblock_message,
            on_blocked=_on_blocked,
            on_unblocked=_on_unblocked,
        )

        await task
        assert isinstance(outcome, WorkerSuccess)
        assert blocked_called is True
        assert unblocked_called_with == "go"
