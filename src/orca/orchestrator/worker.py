from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from orca.engine.types import DispatchWorkerEffect
from orca.orchestrator.pty_session import PtySession
from orca.orchestrator.session_sync import SessionManifest
from orca.orchestrator.template import TemplateRenderError, render_prompt, render_prompt_string
from orca.orchestrator.template_persist import persist_rendered_prompt
from orca.orchestrator.validation import validate_result

logger = logging.getLogger(__name__)

_PROGRESS_RE = re.compile(r"PROGRESS:\s*(\d{1,3})\s*\|\s*(.*?)(?:\s*-->)?\s*$", re.MULTILINE)


def parse_progress(scrollback: str) -> tuple[int, str | None] | None:
    """Parse the last progress marker from scrollback text.

    Returns (percent, status) or None if no marker found.
    """
    matches = _PROGRESS_RE.findall(scrollback)
    # Skip the first match — it's the example from the injected instruction
    if len(matches) <= 1:
        return None
    percent_str, status = matches[-1]
    percent = min(int(percent_str), 100)
    return (percent, status.strip() or None)


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
    startup: bool = False


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
        session_manifest: SessionManifest | None = None,
        session_id: str | None = None,
        run_context: dict[str, Any] | None = None,
        unblock_event: asyncio.Event | None = None,
        unblock_message: list[str] | None = None,
        on_blocked: Callable[[str], None] | None = None,
        on_unblocked: Callable[[str], None] | None = None,
        prompt_text: str | None = None,
        effort: str | None = None,
    ) -> WorkerOutcome: ...


@dataclass(frozen=True)
class KindConfig:
    """Describes how to invoke a specific CLI agent."""

    bin: str
    prompt_via: str  # "stdin" or "arg"
    subcommand: str | None = None
    default_args: tuple[str, ...] = ()
    # CLI flag this kind uses for a reasoning-effort hint. None means the
    # kind doesn't expose one — worker silently drops any configured /
    # overridden `effort` for that kind instead of passing an unrecognised
    # flag.
    effort_flag: str | None = None


KIND_REGISTRY: dict[str, KindConfig] = {
    "claude-code": KindConfig(
        bin="claude",
        prompt_via="stdin",
        default_args=("--dangerously-skip-permissions", "--max-turns", "50"),
        # claude code: effort is implicit in the model choice (opus / sonnet /
        # haiku), no separate flag.
        effort_flag=None,
    ),
    "opencode": KindConfig(
        bin="opencode",
        prompt_via="arg",
        subcommand="run",
        default_args=(),
        effort_flag=None,
    ),
    "codex": KindConfig(
        bin="codex",
        prompt_via="arg",
        subcommand="exec",
        default_args=(),
        effort_flag="--reasoning-effort",
    ),
}


def _build_correction_message(error: str, result_format: dict[str, Any], result_path: Path) -> str:
    """Build a message telling the worker to fix its invalid result.json."""
    format_json = json.dumps(result_format, indent=2)
    return (
        f"URGENT: Your result file at {result_path} is INVALID. "
        f"Error: {error}. "
        f"You MUST rewrite the file with the correct format. "
        f"Required schema: {format_json}"
    )


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
        session_manifest: SessionManifest | None = None,
        session_id: str | None = None,
        run_context: dict[str, Any] | None = None,
        unblock_event: asyncio.Event | None = None,
        unblock_message: list[str] | None = None,
        on_blocked: Callable[[str], None] | None = None,
        on_unblocked: Callable[[str], None] | None = None,
        prompt_text: str | None = None,
        effort: str | None = None,
    ) -> WorkerOutcome:
        assert pty_session is not None, "pty_session is required"

        # a. Delete previous result file
        result_path.unlink(missing_ok=True)

        # b. Render prompt
        try:
            if prompt_text is not None:
                prompt = render_prompt_string(
                    prompt_text,
                    effect.issue,
                    effect.result_format,
                    result_path,
                    progress=effect.progress_enabled,
                    run=run_context,
                )
            elif prompt_path is not None:
                prompt = render_prompt(
                    prompt_path,
                    self._repo_root,
                    effect.issue,
                    effect.result_format,
                    result_path,
                    progress=effect.progress_enabled,
                    run=run_context,
                )
            else:
                prompt = ""
        except TemplateRenderError as exc:
            return WorkerFailure(error=str(exc))

        # b2. Persist rendered prompt for debug review (best effort)
        if session_id:
            with contextlib.suppress(Exception):
                persist_rendered_prompt(
                    workdir=workdir,
                    state_id=effect.state,
                    session_id=session_id,
                    rendered_prompt=prompt,
                )

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
            cmd_parts.extend(["--model", model])
        # Reasoning-effort hint, only if this kind knows the flag. Kinds
        # without `effort_flag` (e.g. claude-code) silently drop the value
        # so workflows can declare effort once and have it apply only
        # where it's meaningful.
        if effort and self._kind_config.effort_flag:
            cmd_parts.extend([self._kind_config.effort_flag, effort])

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
        last_validation_error: str | None = None
        correction_sent = False

        while True:
            await asyncio.sleep(_POLL_INTERVAL)
            elapsed += _POLL_INTERVAL

            # Check for valid result file
            if result_detected_at is None and result_path.exists():
                try:
                    candidate = json.loads(result_path.read_text())

                    # Check for built-in "waiting" outcome before validation
                    if candidate.get("outcome") == "waiting" and unblock_event is not None:
                        # Check session is still alive before entering waiting state
                        if not pty_session.alive:
                            return WorkerFailure(error="session died while reporting waiting")
                        reason = candidate.get("reason", "")

                        # Validate: reason must be non-empty. An empty reason
                        # leaves the run un-diagnosable from state.json /
                        # `orca runs` — the waiting issue records `reason: ""`
                        # and the only place the worker's actual blocker is
                        # described is the tmux pane (gh#14). Nudge the worker
                        # to rewrite with a non-empty reason.
                        if not isinstance(reason, str) or not reason.strip():
                            result_path.unlink(missing_ok=True)
                            logger.warning(
                                "Worker reported outcome:waiting with empty `reason` for issue %s",
                                effect.issue_id,
                                extra={
                                    "event": "waiting_reason_empty",
                                    "issue_id": effect.issue_id,
                                },
                            )
                            if not correction_sent and pty_session.alive:
                                correction_msg = (
                                    f"URGENT: Your result file at {result_path} declared "
                                    f"`outcome: waiting` but the `reason` field was empty. "
                                    f"Rewrite the file with a `reason` of at least one "
                                    f"sentence describing what is blocking. Workers that "
                                    f"pause without a reason leave the run un-diagnosable "
                                    f"from state.json or `orca runs`."
                                )
                                if pty_session.send_keys(correction_msg):
                                    correction_sent = True
                                    logger.info(
                                        "Sent empty-reason correction to worker for issue %s",
                                        effect.issue_id,
                                        extra={
                                            "event": "correction_sent",
                                            "issue_id": effect.issue_id,
                                            "kind": "empty_waiting_reason",
                                        },
                                    )
                            # Keep polling — worker may rewrite, or we'll
                            # hit the inactivity timeout.
                            continue

                        result_path.unlink(missing_ok=True)
                        logger.info(
                            "Worker waiting for issue %s — pausing timer",
                            effect.issue_id,
                            extra={"event": "worker_waiting", "issue_id": effect.issue_id},
                        )
                        if on_blocked is not None:
                            on_blocked(reason)

                        # Blocked sub-loop: wait for unblock or session death
                        while True:
                            await asyncio.sleep(_POLL_INTERVAL)
                            if not pty_session.alive:
                                return WorkerFailure(error="session died while waiting")
                            if unblock_event.is_set():
                                unblock_event.clear()
                                msg = unblock_message[0] if unblock_message else ""
                                pty_session.send_keys(msg)
                                logger.info(
                                    "Worker resumed for issue %s",
                                    effect.issue_id,
                                    extra={"event": "worker_resumed", "issue_id": effect.issue_id},
                                )
                                if on_unblocked is not None:
                                    on_unblocked(msg)
                                break
                        # Resume normal polling — do NOT increment elapsed for blocked time
                        continue

                    error = validate_result(candidate, effect.result_format)
                    if error is None:
                        result_detected_at = elapsed
                        result_detected_while_alive = pty_session.alive
                        last_validation_error = None
                        if session_manifest and session_id:
                            session_manifest.update_result_error(session_id, None)
                        logger.info(
                            "Valid result detected for issue %s — grace period started",
                            effect.issue_id,
                            extra={"event": "result_detected", "issue_id": effect.issue_id},
                        )
                    else:
                        # Check if this is a stale result from a previous state:
                        # the outcome value doesn't match any valid value for the
                        # current state.  Delete the file so it doesn't block
                        # polling for the real result.
                        outcome_def = effect.result_format.get("outcome", {})
                        valid_outcomes = outcome_def.get("values", [])
                        candidate_outcome = candidate.get("outcome")
                        if (
                            isinstance(candidate_outcome, str)
                            and candidate_outcome
                            and candidate_outcome not in valid_outcomes
                        ):
                            result_path.unlink(missing_ok=True)
                            logger.info(
                                "Deleted stale result.json for issue %s (outcome '%s' not in %s)",
                                effect.issue_id,
                                candidate_outcome,
                                valid_outcomes,
                                extra={
                                    "event": "stale_result_deleted",
                                    "issue_id": effect.issue_id,
                                    "stale_outcome": candidate_outcome,
                                },
                            )
                            continue

                        last_validation_error = error
                        logger.warning(
                            "Invalid result.json for issue %s: %s",
                            effect.issue_id,
                            error,
                            extra={
                                "event": "result_validation_failed",
                                "issue_id": effect.issue_id,
                                "validation_error": error,
                            },
                        )
                        if session_manifest and session_id:
                            session_manifest.update_result_error(session_id, error)
                        # Send correction message to the worker (once)
                        if not correction_sent and pty_session.alive:
                            correction_msg = _build_correction_message(error, effect.result_format, result_path)
                            if pty_session.send_keys(correction_msg):
                                correction_sent = True
                                logger.info(
                                    "Sent result correction message to worker for issue %s",
                                    effect.issue_id,
                                    extra={"event": "correction_sent", "issue_id": effect.issue_id},
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
                # Session exited with no result — likely a startup failure
                # (invalid model, missing binary, auth error). Flag as startup
                # failure if it happened quickly (< 30s) so orchestrator can
                # skip retries for config errors.
                is_startup = elapsed < 30.0
                return WorkerFailure(
                    error="result file not found after session exited",
                    startup=is_startup,
                )

            # Timeout — no result produced in time
            if result_detected_at is None and elapsed >= effective_timeout:
                error_detail = f"no valid result after {int(effective_timeout)}s"
                if last_validation_error:
                    error_detail += f" (result.json invalid: {last_validation_error})"
                logger.warning(
                    "Worker for issue %s timed out: %s",
                    effect.issue_id,
                    error_detail,
                    extra={"event": "worker_timeout", "issue_id": effect.issue_id},
                )
                pty_session.kill()
                return WorkerFailure(error=error_detail)
