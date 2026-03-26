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

# Poll result file and session liveness every this many seconds.
_POLL_INTERVAL = 2.0

# Grace period after detecting a valid result before killing the session.
# Allows the worker to flush remaining writes (git commits, file saves).
_RESULT_GRACE_PERIOD = 30.0

# Kill the worker if no valid result file is produced within this time.
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
        env: dict[str, str] | None = None,
        model: str | None = None,
        extra_args: list[str] | None = None,
    ) -> WorkerOutcome: ...


@dataclass(frozen=True)
class KindConfig:
    """Describes how to invoke a specific CLI agent."""

    bin: str
    prompt_via: str  # "stdin" or "arg"
    subcommand: str | None = None
    default_args: tuple[str, ...] = ()


KIND_REGISTRY: dict[str, KindConfig] = {
    "claude-code": KindConfig(
        bin="claude",
        prompt_via="stdin",
        default_args=("--dangerously-skip-permissions", "--max-turns", "50"),
    ),
    "opencode": KindConfig(
        bin="opencode",
        prompt_via="arg",
        subcommand="run",
        default_args=(),
    ),
}


class CliAgentWorker:
    """Spawns a CLI agent as a subprocess, streams output to a session log, reads/validates result."""

    def __init__(self, repo_root: Path, kind_config: KindConfig) -> None:
        self._repo_root = repo_root
        self._kind_config = kind_config

    async def execute(
        self,
        effect: DispatchWorkerEffect,
        workdir: Path,
        result_path: Path,
        prompt_path: Path | None = None,
        inactivity_timeout: int | None = None,
        pty_session: PtySession | None = None,
        env: dict[str, str] | None = None,
        model: str | None = None,
        extra_args: list[str] | None = None,
    ) -> WorkerOutcome:
        assert pty_session is not None, "pty_session is required"

        # a. Delete previous result file
        result_path.unlink(missing_ok=True)

        # b. Render prompt
        if prompt_path is not None:
            prompt = render_prompt(prompt_path, self._repo_root, effect.issue, effect.result_format, result_path)
        else:
            prompt = ""

        # c. Build command
        cmd_parts: list[str] = [self._kind_config.bin]
        if self._kind_config.subcommand:
            cmd_parts.append(self._kind_config.subcommand)
        if self._kind_config.prompt_via == "arg":
            cmd_parts.append(prompt)
        cmd_parts.extend(self._kind_config.default_args)
        if extra_args:
            cmd_parts.extend(extra_args)
        if model:
            cmd_parts.extend(["-m", model])

        # d. Spawn in tmux session
        await pty_session.spawn(
            cmd_parts[0],
            cmd_parts[1:],
            cwd=workdir,
            stdin_data=prompt.encode() if self._kind_config.prompt_via == "stdin" else None,
            env=env,
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

        # e. Poll for result file or session exit
        effective_timeout = float(inactivity_timeout) if inactivity_timeout is not None else _INACTIVITY_TIMEOUT
        elapsed = 0.0
        result_detected_at: float | None = None
        result_detected_while_alive = False

        while True:
            await asyncio.sleep(_POLL_INTERVAL)
            elapsed += _POLL_INTERVAL

            # Check for valid result file
            if result_detected_at is None and result_path.exists():
                try:
                    candidate = json.loads(result_path.read_text())
                    error = validate_result(candidate, effect.result_format)
                    if error is None:
                        result_detected_at = elapsed
                        result_detected_while_alive = pty_session.alive
                        logger.info(
                            "Valid result detected for issue %s — grace period started",
                            effect.issue_id,
                            extra={"event": "result_detected", "issue_id": effect.issue_id},
                        )
                except (json.JSONDecodeError, OSError):
                    pass

            # Grace period elapsed — kill session, return success
            if result_detected_at is not None and elapsed - result_detected_at >= _RESULT_GRACE_PERIOD:
                result = json.loads(result_path.read_text())
                if pty_session.alive:
                    pty_session.kill()
                return WorkerSuccess(result=result)

            # Session exited on its own — check result
            if not pty_session.alive:
                if result_detected_at is not None:
                    # Result was already validated during grace period; session exited on its own.
                    # Kill to ensure cleanup if it was alive when result was detected.
                    if result_detected_while_alive:
                        pty_session.kill()
                    result = json.loads(result_path.read_text())
                    return WorkerSuccess(result=result)
                if result_path.exists():
                    try:
                        result = json.loads(result_path.read_text())
                        error = validate_result(result, effect.result_format)
                        if error is None:
                            return WorkerSuccess(result=result)
                        return WorkerFailure(error=error)
                    except (json.JSONDecodeError, OSError) as e:
                        return WorkerFailure(error=f"failed to parse result file: {e}")
                return WorkerFailure(error="result file not found after session exited")

            # Timeout — no result produced in time
            if result_detected_at is None and elapsed >= effective_timeout:
                logger.warning(
                    "Worker for issue %s timed out with no result",
                    effect.issue_id,
                    extra={"event": "worker_timeout", "issue_id": effect.issue_id},
                )
                pty_session.kill()
                return WorkerFailure(error=f"no valid result after {int(effective_timeout)}s")
