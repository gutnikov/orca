from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

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
