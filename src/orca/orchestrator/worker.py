from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from orca.engine.types import DispatchWorkerEffect
from orca.orchestrator.template import render_prompt
from orca.orchestrator.validation import validate_result


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
    ) -> WorkerOutcome:
        # a. Delete previous result file
        result_path.unlink(missing_ok=True)

        # b. Render prompt
        if prompt_path is not None:
            prompt = render_prompt(prompt_path, self._repo_root, effect.issue, effect.result_format, result_path)
        else:
            prompt = ""

        # c. Create session log path
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
        sessions_dir = workdir / ".orca" / "sessions"
        sessions_dir.mkdir(parents=True, exist_ok=True)
        session_log_path = sessions_dir / f"{effect.state}-{timestamp}.jsonl"

        # d. Spawn claude subprocess
        proc = await asyncio.create_subprocess_exec(
            "claude",
            "--print",
            "--output-format",
            "stream-json",
            "--max-turns",
            "50",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            cwd=workdir,
        )

        # Write rendered prompt to stdin and close it
        if proc.stdin is not None:
            proc.stdin.write(prompt.encode())
            proc.stdin.close()

        # e. Stream stdout lines to session log file
        with session_log_path.open("wb") as log_file:
            async for line in proc.stdout:  # type: ignore[union-attr]
                log_file.write(line)

        # f. Wait for process, check returncode
        await proc.wait()
        if proc.returncode != 0:
            return WorkerFailure(error=f"claude exited with non-zero exit code: {proc.returncode}")

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
