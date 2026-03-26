# Result-Based Worker Completion

## Problem

Claude CLI never exits after finishing its work — it returns to the `>` prompt and waits for more input. The orchestrator currently uses a dumb session-lifespan timeout (`wait()` polls `tmux has-session` every 0.5s, kills after 300s). This means every successful worker wastes up to 5 minutes sitting idle before the orchestrator detects completion, and the kill is treated as a failure, triggering unnecessary retries.

The only reliable completion signal is the worker writing a valid `result.json` file to disk.

## Design

### 1. Worker completion loop (`worker.py`)

Replace the current `pty_session.wait(timeout)` call in `ClaudeCodeWorker.execute()` with a polling loop that checks for `result.json`:

```
spawn tmux session
loop every 2 seconds:
    if result_path exists and validates:
        wait 30 seconds (grace period for git commits, file writes)
        kill tmux session
        return WorkerSuccess
    if tmux session is no longer alive:
        check result_path -> WorkerSuccess or WorkerFailure
        break
    if elapsed > inactivity_timeout:
        kill tmux session
        return WorkerFailure("no valid result after {timeout}s")
```

Key behaviors:

- **Poll interval**: 2 seconds for the result file check. The alive check runs on the same cycle. This replaces the current 0.5s alive-only polling.
- **Grace period**: 30 seconds after detecting a valid result before killing the session. Gives claude time to finish flushing git commits or file writes that happen after writing result.json.
- **Timeout**: Still acts as a hard ceiling (default 300s from `_INACTIVITY_TIMEOUT`) but now means "no result produced within this time" rather than "session still alive after this time."
- **Natural exit**: If the tmux session exits on its own (unlikely for claude, but possible), we still check result.json — same as today's happy path.

`TmuxSession` is unchanged. The worker calls `pty_session.alive` and `pty_session.kill()` directly instead of delegating to `wait()`.

### 2. Prompt template warning (`template.py`)

Inject a warning into every rendered prompt via `render_prompt()`, appended as a suffix after Jinja2 rendering:

> **IMPORTANT: Writing the result file is the final action of your session. The orchestrator will terminate this session shortly after detecting the result file. Complete ALL other work — git commits, file writes, code changes — before writing the result file.**

This applies automatically to all workflows. Workflow authors don't need to add the warning to individual prompt templates.

### 3. Cleanup

Remove the check-result-after-kill fallback added earlier in the session (the `if result_path.exists()` block inside the `exit_code != 0` branch). The polling loop handles all cases:

- Result appears before timeout: grace period, kill, success.
- Session exits naturally: check result, success or failure.
- Timeout with no result: kill, failure.

## Files Changed

- `src/orca/orchestrator/worker.py` — new polling loop in `execute()`, remove post-kill result check
- `src/orca/orchestrator/template.py` — append result-file warning to rendered prompts

## Files NOT Changed

- `src/orca/orchestrator/pty_session.py` — `TmuxSession` stays generic, no changes
- `src/orca/engine/` — no engine changes, this is purely orchestrator-level
- Prompt templates — warning is injected by `template.py`, not added to individual templates
