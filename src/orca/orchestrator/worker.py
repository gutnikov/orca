from __future__ import annotations

import asyncio
import contextlib
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
        log_path: Path | None = None,
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
        log_path: Path | None = None,
    ) -> WorkerOutcome:
        if pty_session is not None:
            return await self._execute_pty(
                effect, workdir, result_path, prompt_path, inactivity_timeout, pty_session, log_path
            )
        return await self._execute_piped(effect, workdir, result_path, prompt_path, inactivity_timeout)

    async def _execute_pty(
        self,
        effect: DispatchWorkerEffect,
        workdir: Path,
        result_path: Path,
        prompt_path: Path | None,
        inactivity_timeout: int | None,
        pty_session: PtySession,
        log_path: Path | None,
    ) -> WorkerOutcome:
        # a. Delete previous result file
        result_path.unlink(missing_ok=True)

        # b. Render prompt
        if prompt_path is not None:
            prompt = render_prompt(prompt_path, self._repo_root, effect.issue, effect.result_format, result_path)
        else:
            prompt = ""

        # c. Spawn claude via pty — pipe prompt through stdin
        await pty_session.spawn(
            "claude",
            ["--dangerously-skip-permissions", "--max-turns", "50"],
            cwd=workdir,
            log_path=log_path,
            stdin_data=prompt.encode(),
        )

        logger.debug(
            "Pty subprocess started for issue %s",
            effect.issue_id,
            extra={
                "event": "pty_subprocess_started",
                "issue_id": effect.issue_id,
                "state": effect.state,
                "pid": pty_session.pid,
                "workdir": str(workdir),
            },
        )

        # e. Run read_loop concurrently, wait for process to exit
        read_task = asyncio.create_task(pty_session.read_loop())

        effective_timeout = float(inactivity_timeout) if inactivity_timeout else _INACTIVITY_TIMEOUT
        try:
            await asyncio.wait_for(
                asyncio.to_thread(pty_session._proc.wait),  # type: ignore[union-attr]
                timeout=effective_timeout,
            )
        except TimeoutError:
            logger.warning(
                "Worker for issue %s inactive for %ds — killing",
                effect.issue_id,
                int(effective_timeout),
                extra={"event": "inactivity_timeout", "issue_id": effect.issue_id, "pid": pty_session.pid},
            )
            if pty_session._proc is not None:
                pty_session._proc.kill()
            read_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await read_task
            return WorkerFailure(error=f"worker killed after {int(effective_timeout)}s of inactivity")

        # Cancel read loop (it will finish on EIO naturally, but cancel as safety)
        read_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await read_task

        # f. Check exit code
        returncode = pty_session._proc.returncode if pty_session._proc else -1
        logger.debug(
            "Pty subprocess exited for issue %s with code %s",
            effect.issue_id,
            returncode,
            extra={
                "event": "pty_subprocess_exited",
                "issue_id": effect.issue_id,
                "state": effect.state,
                "returncode": returncode,
            },
        )
        if returncode != 0:
            return WorkerFailure(error=f"claude exited with non-zero exit code: {returncode}")

        # g. Read result_path, parse JSON
        if not result_path.exists():
            return WorkerFailure(error="result file not found after claude exited successfully")

        try:
            result: dict[str, Any] = json.loads(result_path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            return WorkerFailure(error=f"failed to parse result file: {e}")

        # h. Validate result
        error = validate_result(result, effect.result_format)
        if error is not None:
            return WorkerFailure(error=error)

        # i. Return WorkerSuccess
        return WorkerSuccess(result=result)

    async def _execute_piped(
        self,
        effect: DispatchWorkerEffect,
        workdir: Path,
        result_path: Path,
        prompt_path: Path | None,
        inactivity_timeout: int | None,
    ) -> WorkerOutcome:
        # a. Delete previous result file
        result_path.unlink(missing_ok=True)

        # b. Render prompt
        if prompt_path is not None:
            prompt = render_prompt(prompt_path, self._repo_root, effect.issue, effect.result_format, result_path)
        else:
            prompt = ""

        # c. Spawn claude subprocess
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
            limit=1024 * 1024,  # 1MB line buffer (default 64KB too small for large tool outputs)
        )

        logger.debug(
            "Subprocess started for issue %s",
            effect.issue_id,
            extra={
                "event": "subprocess_started",
                "issue_id": effect.issue_id,
                "state": effect.state,
                "pid": proc.pid,
                "workdir": str(workdir),
            },
        )

        # Write rendered prompt to stdin and close it
        if proc.stdin is not None:
            proc.stdin.write(prompt.encode())
            proc.stdin.close()

        # d. Read stdout until EOF or inactivity timeout
        timed_out = False
        effective_timeout = float(inactivity_timeout) if inactivity_timeout else _INACTIVITY_TIMEOUT
        assert proc.stdout is not None
        while True:
            try:
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=effective_timeout)
            except TimeoutError:
                logger.warning(
                    "Worker for issue %s inactive for %ds — killing",
                    effect.issue_id,
                    int(_INACTIVITY_TIMEOUT),
                    extra={"event": "inactivity_timeout", "issue_id": effect.issue_id, "pid": proc.pid},
                )
                proc.kill()
                timed_out = True
                break
            if not line:
                break  # EOF

        # f. Wait for process, check returncode
        await proc.wait()
        if timed_out:
            return WorkerFailure(
                error=f"worker killed after {int(_INACTIVITY_TIMEOUT)}s of inactivity",
            )
        logger.debug(
            "Subprocess exited for issue %s with code %s",
            effect.issue_id,
            proc.returncode,
            extra={
                "event": "subprocess_exited",
                "issue_id": effect.issue_id,
                "state": effect.state,
                "pid": proc.pid,
                "returncode": proc.returncode,
            },
        )
        if proc.returncode != 0:
            return WorkerFailure(
                error=f"claude exited with non-zero exit code: {proc.returncode}",
            )

        # g. Read result_path, parse JSON
        if not result_path.exists():
            return WorkerFailure(error="result file not found after claude exited successfully")

        try:
            result: dict[str, Any] = json.loads(result_path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            return WorkerFailure(error=f"failed to parse result file: {e}")

        # h. Validate result
        error = validate_result(result, effect.result_format)
        if error is not None:
            return WorkerFailure(error=error)

        # i. Return WorkerSuccess
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
