from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from orca.engine.types import DispatchWorkerEffect
from orca.orchestrator.pty_session import PtySession
from orca.orchestrator.template import render_prompt
from orca.orchestrator.validation import validate_result

logger = logging.getLogger(__name__)

# Kill the worker if no stdout output is received for this long.
_INACTIVITY_TIMEOUT = 300.0  # 5 minutes


@dataclass(frozen=True)
class WorkerSuccess:
    result: dict[str, Any]


@dataclass(frozen=True)
class WorkerFailure:
    error: str


WorkerOutcome = WorkerSuccess | WorkerFailure


class Worker(Protocol):
    async def execute(
        self,
        effect: DispatchWorkerEffect,
        workdir: Path,
        result_path: Path,
        prompt_path: Path | None = None,
        inactivity_timeout: int | None = None,
        pty_session: PtySession | None = None,
    ) -> WorkerOutcome: ...


class ClaudeCodeWorker:
    """Spawns claude CLI as a subprocess, streams output to a session log, reads/validates result."""

    def __init__(self, repo_root: Path) -> None:
        self._repo_root = repo_root

    async def execute(
        self,
        effect: DispatchWorkerEffect,
        workdir: Path,
        result_path: Path,
        prompt_path: Path | None = None,
        inactivity_timeout: int | None = None,
        pty_session: PtySession | None = None,
    ) -> WorkerOutcome:
        assert pty_session is not None, "pty_session is required"

        # a. Delete previous result file
        result_path.unlink(missing_ok=True)

        # b. Render prompt
        if prompt_path is not None:
            prompt = render_prompt(prompt_path, self._repo_root, effect.issue, effect.result_format, result_path)
        else:
            prompt = ""

        # c. Spawn claude in a tmux session — prompt piped via file
        await pty_session.spawn(
            "claude",
            ["--dangerously-skip-permissions", "--max-turns", "50"],
            cwd=workdir,
            stdin_data=prompt.encode(),
        )

        logger.debug(
            "Tmux session started for issue %s",
            effect.issue_id,
            extra={
                "event": "tmux_session_started",
                "issue_id": effect.issue_id,
                "state": effect.state,
                "session": pty_session.session_name,
                "workdir": str(workdir),
            },
        )

        # d. Wait for tmux session to end (process exits -> session closes)
        effective_timeout = float(inactivity_timeout) if inactivity_timeout else _INACTIVITY_TIMEOUT
        exit_code = await pty_session.wait(timeout=effective_timeout)

        if exit_code != 0:
            logger.warning(
                "Worker for issue %s timed out or failed",
                effect.issue_id,
                extra={"event": "tmux_session_failed", "issue_id": effect.issue_id},
            )
            return WorkerFailure(error=f"worker killed after {int(effective_timeout)}s of inactivity")

        # e. Read result_path, parse JSON
        if not result_path.exists():
            return WorkerFailure(error="result file not found after claude exited successfully")

        try:
            result: dict[str, Any] = json.loads(result_path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            return WorkerFailure(error=f"failed to parse result file: {e}")

        # f. Validate result
        error = validate_result(result, effect.result_format)
        if error is not None:
            return WorkerFailure(error=error)

        return WorkerSuccess(result=result)

    async def execute_raw(
        self,
        prompt: str,
        workdir: Path,
        session_log_path: Path,
        timeout: float | None = None,
    ) -> WorkerOutcome:
        """Run Claude with a pre-rendered prompt. No result.json parsing.

        Unlike execute(), this accepts a ready-to-use prompt string and does not
        read or validate a result file. Used for sidecar tasks like insights.

        Returns WorkerSuccess(result={}) on exit code 0, WorkerFailure otherwise.
        """
        session_log_path.parent.mkdir(parents=True, exist_ok=True)

        proc = await asyncio.create_subprocess_exec(
            "claude",
            "--print",
            "--output-format",
            "stream-json",
            "--verbose",
            "--max-turns",
            "50",
            "--dangerously-skip-permissions",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            cwd=workdir,
            limit=1024 * 1024,
        )

        if proc.stdin is not None:
            proc.stdin.write(prompt.encode())
            proc.stdin.close()

        async def _stream_and_wait() -> None:
            with session_log_path.open("wb") as log_file:
                async for line in proc.stdout:  # type: ignore[union-attr]
                    log_file.write(line)
            await proc.wait()

        try:
            await asyncio.wait_for(_stream_and_wait(), timeout=timeout)
        except TimeoutError:
            proc.kill()
            return WorkerFailure(error="insights worker timed out")

        if proc.returncode != 0:
            return WorkerFailure(
                error=f"claude exited with non-zero exit code: {proc.returncode}",
            )

        return WorkerSuccess(result={})
