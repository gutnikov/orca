from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from orca.engine.types import DispatchWorkerEffect
from orca.orchestrator.worker import ClaudeCodeWorker, WorkerFailure, WorkerSuccess


def _make_effect(state: str = "implementing") -> DispatchWorkerEffect:
    return DispatchWorkerEffect(
        issue_id="issue-1",
        state=state,
        result_format={
            "outcome": {"type": "enum", "values": ["done"], "description": "Outcome"},
            "summary": {"type": "string", "description": "Summary", "required_when": ["done"]},
        },
        issue={"fields": {"title": "Test"}, "event_log": [], "decomposed_from": None, "depends_on": [], "children": []},
    )


class AsyncLineIterator:
    def __init__(self, lines: list[bytes]) -> None:
        self._lines = lines
        self._index = 0

    def __aiter__(self) -> AsyncLineIterator:
        return self

    async def __anext__(self) -> bytes:
        if self._index >= len(self._lines):
            raise StopAsyncIteration
        line = self._lines[self._index]
        self._index += 1
        return line

    async def readline(self) -> bytes:
        if self._index >= len(self._lines):
            return b""
        line = self._lines[self._index]
        self._index += 1
        return line


def _make_mock_proc(returncode: int, stdout_lines: list[bytes] | None = None) -> MagicMock:
    proc = MagicMock()
    proc.returncode = returncode
    proc.stdout = AsyncLineIterator(stdout_lines or [])
    proc.wait = AsyncMock(return_value=returncode)
    proc.stdin = MagicMock()
    proc.stdin.close = MagicMock()
    return proc


def _make_mock_pty(
    exit_code: int = 0, write_result: dict[str, Any] | None = None, result_path: Path | None = None
) -> MagicMock:
    """Create a mock PtySession that optionally writes a result file on spawn."""
    pty = MagicMock()
    pty.session_name = "mock-session"

    async def _spawn(*args: Any, **kwargs: Any) -> None:
        if write_result is not None and result_path is not None:
            result_path.write_text(json.dumps(write_result))

    pty.spawn = AsyncMock(side_effect=_spawn)
    pty.wait = AsyncMock(return_value=exit_code)
    pty.close = MagicMock()
    return pty


@pytest.mark.asyncio()
class TestClaudeCodeWorker:
    async def test_successful_execution(self, tmp_path: Path) -> None:
        """Pty session exits 0, writes valid result file, assert WorkerSuccess."""
        effect = _make_effect()
        result_path = tmp_path / "result.json"
        prompt_path = tmp_path / "prompt.md"
        prompt_path.write_text("Do the thing")

        valid_result: dict[str, Any] = {"outcome": "done", "summary": "All done"}
        pty = _make_mock_pty(exit_code=0, write_result=valid_result, result_path=result_path)

        worker = ClaudeCodeWorker(repo_root=tmp_path)
        outcome = await worker.execute(effect, tmp_path, result_path, prompt_path, pty_session=pty)

        assert isinstance(outcome, WorkerSuccess)
        assert outcome.result == valid_result

    async def test_nonzero_exit_code(self, tmp_path: Path) -> None:
        """Pty session exits -1 (timeout), assert WorkerFailure with 'inactivity' in error."""
        effect = _make_effect()
        result_path = tmp_path / "result.json"
        prompt_path = tmp_path / "prompt.md"
        prompt_path.write_text("Do the thing")

        pty = _make_mock_pty(exit_code=-1)

        worker = ClaudeCodeWorker(repo_root=tmp_path)
        outcome = await worker.execute(effect, tmp_path, result_path, prompt_path, pty_session=pty)

        assert isinstance(outcome, WorkerFailure)
        assert "inactivity" in outcome.error

    async def test_missing_result_file(self, tmp_path: Path) -> None:
        """Pty session succeeds but no result file written, assert WorkerFailure with 'result file'."""
        effect = _make_effect()
        result_path = tmp_path / "result.json"
        prompt_path = tmp_path / "prompt.md"
        prompt_path.write_text("Do the thing")

        pty = _make_mock_pty(exit_code=0)

        worker = ClaudeCodeWorker(repo_root=tmp_path)
        outcome = await worker.execute(effect, tmp_path, result_path, prompt_path, pty_session=pty)

        assert isinstance(outcome, WorkerFailure)
        assert "result file" in outcome.error

    async def test_invalid_result_validation(self, tmp_path: Path) -> None:
        """Result file has missing required summary, assert WorkerFailure with 'summary'."""
        effect = _make_effect()
        result_path = tmp_path / "result.json"
        prompt_path = tmp_path / "prompt.md"
        prompt_path.write_text("Do the thing")

        invalid_result: dict[str, Any] = {"outcome": "done"}  # missing required summary
        pty = _make_mock_pty(exit_code=0, write_result=invalid_result, result_path=result_path)

        worker = ClaudeCodeWorker(repo_root=tmp_path)
        outcome = await worker.execute(effect, tmp_path, result_path, prompt_path, pty_session=pty)

        assert isinstance(outcome, WorkerFailure)
        assert "summary" in outcome.error

    async def test_previous_result_file_deleted(self, tmp_path: Path) -> None:
        """Pre-existing stale result file: pty session exits 0 but writes nothing -> WorkerFailure."""
        effect = _make_effect()
        result_path = tmp_path / "result.json"
        prompt_path = tmp_path / "prompt.md"
        prompt_path.write_text("Do the thing")

        # Write stale result file before running
        stale_result: dict[str, Any] = {"outcome": "done", "summary": "Stale"}
        result_path.write_text(json.dumps(stale_result))

        pty = _make_mock_pty(exit_code=0)
        # pty session exits 0 but writes nothing new -- stale file was deleted

        worker = ClaudeCodeWorker(repo_root=tmp_path)
        outcome = await worker.execute(effect, tmp_path, result_path, prompt_path, pty_session=pty)

        assert isinstance(outcome, WorkerFailure)
        assert "result file" in outcome.error


@pytest.mark.asyncio()
class TestClaudeCodeWorkerExecuteRaw:
    async def test_successful_raw_execution(self, tmp_path: Path) -> None:
        """exit code 0 -> WorkerSuccess with empty result dict."""
        proc = _make_mock_proc(0)
        session_log = tmp_path / "session.jsonl"

        with patch("orca.orchestrator.worker.asyncio.create_subprocess_exec", return_value=proc):
            worker = ClaudeCodeWorker(repo_root=tmp_path)
            outcome = await worker.execute_raw("analyze this", tmp_path, session_log)

        assert isinstance(outcome, WorkerSuccess)
        assert outcome.result == {}
        assert session_log.exists()

    async def test_raw_nonzero_exit(self, tmp_path: Path) -> None:
        """exit code 1 -> WorkerFailure."""
        proc = _make_mock_proc(1)
        session_log = tmp_path / "session.jsonl"

        with patch("orca.orchestrator.worker.asyncio.create_subprocess_exec", return_value=proc):
            worker = ClaudeCodeWorker(repo_root=tmp_path)
            outcome = await worker.execute_raw("analyze this", tmp_path, session_log)

        assert isinstance(outcome, WorkerFailure)
        assert "exit code" in outcome.error

    async def test_raw_timeout_during_streaming(self, tmp_path: Path) -> None:
        """Worker killed after timeout during stdout streaming -> WorkerFailure."""

        class SlowLineIterator:
            """Simulates a subprocess that never finishes writing stdout."""

            def __aiter__(self) -> SlowLineIterator:
                return self

            async def __anext__(self) -> bytes:
                await asyncio.sleep(100)  # hang forever
                return b""

        proc = MagicMock()
        proc.returncode = -9
        proc.stdout = SlowLineIterator()
        proc.stdin = MagicMock()
        proc.stdin.close = MagicMock()
        proc.kill = MagicMock()
        proc.wait = AsyncMock(return_value=-9)

        session_log = tmp_path / "session.jsonl"

        with patch("orca.orchestrator.worker.asyncio.create_subprocess_exec", return_value=proc):
            worker = ClaudeCodeWorker(repo_root=tmp_path)
            outcome = await worker.execute_raw("analyze", tmp_path, session_log, timeout=0.1)

        assert isinstance(outcome, WorkerFailure)
        assert "timeout" in outcome.error.lower() or "timed out" in outcome.error.lower()
        proc.kill.assert_called_once()
