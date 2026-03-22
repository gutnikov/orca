from __future__ import annotations

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


def _make_mock_proc(returncode: int, stdout_lines: list[bytes] | None = None) -> MagicMock:
    proc = MagicMock()
    proc.returncode = returncode
    proc.stdout = AsyncLineIterator(stdout_lines or [])
    proc.wait = AsyncMock(return_value=returncode)
    proc.stdin = MagicMock()
    proc.stdin.close = MagicMock()
    return proc


@pytest.mark.asyncio()
class TestClaudeCodeWorker:
    async def test_successful_execution(self, tmp_path: Path) -> None:
        """Mock subprocess exits 0, writes valid result file, assert WorkerSuccess."""
        effect = _make_effect()
        result_path = tmp_path / "result.json"
        prompt_path = tmp_path / "prompt.md"
        prompt_path.write_text("Do the thing")

        valid_result: dict[str, Any] = {"outcome": "done", "summary": "All done"}

        proc = _make_mock_proc(0)

        async def fake_create(*args: Any, **kwargs: Any) -> MagicMock:
            result_path.write_text(json.dumps(valid_result))
            return proc

        with patch("orca.orchestrator.worker.asyncio.create_subprocess_exec", side_effect=fake_create):
            worker = ClaudeCodeWorker(repo_root=tmp_path)
            outcome = await worker.execute(effect, tmp_path, result_path, prompt_path)

        assert isinstance(outcome, WorkerSuccess)
        assert outcome.result == valid_result

    async def test_nonzero_exit_code(self, tmp_path: Path) -> None:
        """Mock subprocess exits 1, assert WorkerFailure with 'exit code' in error."""
        effect = _make_effect()
        result_path = tmp_path / "result.json"
        prompt_path = tmp_path / "prompt.md"
        prompt_path.write_text("Do the thing")

        proc = _make_mock_proc(1)

        with patch("orca.orchestrator.worker.asyncio.create_subprocess_exec", return_value=proc):
            worker = ClaudeCodeWorker(repo_root=tmp_path)
            outcome = await worker.execute(effect, tmp_path, result_path, prompt_path)

        assert isinstance(outcome, WorkerFailure)
        assert "exit code" in outcome.error

    async def test_missing_result_file(self, tmp_path: Path) -> None:
        """Subprocess succeeds but no result file written, assert WorkerFailure with 'result file'."""
        effect = _make_effect()
        result_path = tmp_path / "result.json"
        prompt_path = tmp_path / "prompt.md"
        prompt_path.write_text("Do the thing")

        proc = _make_mock_proc(0)

        with patch("orca.orchestrator.worker.asyncio.create_subprocess_exec", return_value=proc):
            worker = ClaudeCodeWorker(repo_root=tmp_path)
            outcome = await worker.execute(effect, tmp_path, result_path, prompt_path)

        assert isinstance(outcome, WorkerFailure)
        assert "result file" in outcome.error

    async def test_invalid_result_validation(self, tmp_path: Path) -> None:
        """Result file has missing required summary, assert WorkerFailure with 'summary'."""
        effect = _make_effect()
        result_path = tmp_path / "result.json"
        prompt_path = tmp_path / "prompt.md"
        prompt_path.write_text("Do the thing")

        invalid_result: dict[str, Any] = {"outcome": "done"}  # missing required summary

        proc = _make_mock_proc(0)

        async def fake_create(*args: Any, **kwargs: Any) -> MagicMock:
            result_path.write_text(json.dumps(invalid_result))
            return proc

        with patch("orca.orchestrator.worker.asyncio.create_subprocess_exec", side_effect=fake_create):
            worker = ClaudeCodeWorker(repo_root=tmp_path)
            outcome = await worker.execute(effect, tmp_path, result_path, prompt_path)

        assert isinstance(outcome, WorkerFailure)
        assert "summary" in outcome.error

    async def test_previous_result_file_deleted(self, tmp_path: Path) -> None:
        """Pre-existing stale result file: subprocess exits 0 but writes nothing → WorkerFailure."""
        effect = _make_effect()
        result_path = tmp_path / "result.json"
        prompt_path = tmp_path / "prompt.md"
        prompt_path.write_text("Do the thing")

        # Write stale result file before running
        stale_result: dict[str, Any] = {"outcome": "done", "summary": "Stale"}
        result_path.write_text(json.dumps(stale_result))

        proc = _make_mock_proc(0)
        # subprocess exits 0 but writes nothing new — stale file was deleted

        with patch("orca.orchestrator.worker.asyncio.create_subprocess_exec", return_value=proc):
            worker = ClaudeCodeWorker(repo_root=tmp_path)
            outcome = await worker.execute(effect, tmp_path, result_path, prompt_path)

        assert isinstance(outcome, WorkerFailure)
        assert "result file" in outcome.error

    async def test_session_log_created(self, tmp_path: Path) -> None:
        """Verify .orca/sessions/{state}-*.jsonl file created in workdir."""
        effect = _make_effect(state="implementing")
        result_path = tmp_path / "result.json"
        prompt_path = tmp_path / "prompt.md"
        prompt_path.write_text("Do the thing")

        output_line = b'{"type": "assistant", "content": "working"}\n'
        proc = _make_mock_proc(0, stdout_lines=[output_line])

        with patch("orca.orchestrator.worker.asyncio.create_subprocess_exec", return_value=proc):
            worker = ClaudeCodeWorker(repo_root=tmp_path)
            await worker.execute(effect, tmp_path, result_path, prompt_path)

        sessions_dir = tmp_path / ".orca" / "sessions"
        assert sessions_dir.exists()
        session_files = list(sessions_dir.glob("implementing-*.jsonl"))
        assert len(session_files) == 1
        assert session_files[0].read_bytes() == output_line
