# Result-Based Worker Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect worker completion by polling for a valid `result.json` file instead of waiting for the tmux session to exit (which never happens with Claude CLI).

**Architecture:** Replace the single `pty_session.wait(timeout)` call in `ClaudeCodeWorker.execute()` with an async polling loop that checks both session liveness and result file validity every 2 seconds. Append a "result file = session over" warning to all rendered prompts via `template.py`.

**Tech Stack:** Python 3.12, asyncio, JSON file I/O, Jinja2

---

### File Map

- Modify: `src/orca/orchestrator/worker.py` — replace `wait()` call with polling loop
- Modify: `src/orca/orchestrator/template.py` — append result-file warning suffix
- Modify: `tests/orchestrator/test_worker.py` — rewrite mocks for new polling loop, add new test cases
- Modify: `tests/orchestrator/test_template.py` — add test for appended warning

---

### Task 1: Rewrite worker tests for polling-based completion

**Files:**
- Modify: `tests/orchestrator/test_worker.py`

The existing tests mock `pty_session.wait()` which the worker will no longer call. Replace with mocks that expose `.alive` and `.kill()`, and simulate result file creation at controlled times.

- [ ] **Step 1: Replace `_make_mock_pty` helper with polling-compatible version**

Replace the entire `_make_mock_pty` function and add a new `_make_polling_pty` helper:

```python
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
        if (
            not written
            and write_result is not None
            and result_path is not None
            and call_count > write_after_spawns
        ):
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
```

- [ ] **Step 2: Rewrite `test_successful_execution` — result detected while session alive**

```python
async def test_result_detected_while_alive(self, tmp_path: Path) -> None:
    """Result file appears while session is alive -> WorkerSuccess, session killed."""
    effect = _make_effect()
    result_path = tmp_path / "result.json"
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text("Do the thing")

    valid_result: dict[str, Any] = {"outcome": "done", "summary": "All done"}
    pty = _make_polling_pty(
        alive_count=100,  # stays alive forever
        write_result=valid_result,
        result_path=result_path,
        write_after_spawns=0,  # write on spawn
    )

    worker = ClaudeCodeWorker(repo_root=tmp_path)
    outcome = await worker.execute(effect, tmp_path, result_path, prompt_path, pty_session=pty)

    assert isinstance(outcome, WorkerSuccess)
    assert outcome.result == valid_result
    pty.kill.assert_called_once()
```

- [ ] **Step 3: Rewrite `test_nonzero_exit_code` as `test_timeout_no_result`**

```python
async def test_timeout_no_result(self, tmp_path: Path) -> None:
    """Session stays alive, no result file -> timeout -> WorkerFailure."""
    effect = _make_effect()
    result_path = tmp_path / "result.json"
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text("Do the thing")

    pty = _make_polling_pty(alive_count=999)  # stays alive, no result

    worker = ClaudeCodeWorker(repo_root=tmp_path)
    outcome = await worker.execute(
        effect, tmp_path, result_path, prompt_path,
        inactivity_timeout=0,  # immediate timeout
        pty_session=pty,
    )

    assert isinstance(outcome, WorkerFailure)
    assert "no valid result" in outcome.error
    pty.kill.assert_called_once()
```

- [ ] **Step 4: Rewrite `test_missing_result_file` — session exits naturally, no result**

```python
async def test_session_exits_no_result(self, tmp_path: Path) -> None:
    """Session exits on its own, no result file -> WorkerFailure."""
    effect = _make_effect()
    result_path = tmp_path / "result.json"
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text("Do the thing")

    pty = _make_polling_pty(alive_count=2)  # exits after 2 checks

    worker = ClaudeCodeWorker(repo_root=tmp_path)
    outcome = await worker.execute(effect, tmp_path, result_path, prompt_path, pty_session=pty)

    assert isinstance(outcome, WorkerFailure)
    assert "result file not found" in outcome.error
```

- [ ] **Step 5: Keep `test_invalid_result_validation` and `test_previous_result_file_deleted` with updated mocks**

```python
async def test_invalid_result_validation(self, tmp_path: Path) -> None:
    """Result file has missing required summary -> WorkerFailure."""
    effect = _make_effect()
    result_path = tmp_path / "result.json"
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text("Do the thing")

    invalid_result: dict[str, Any] = {"outcome": "done"}  # missing required summary
    pty = _make_polling_pty(alive_count=2, write_result=invalid_result, result_path=result_path)

    worker = ClaudeCodeWorker(repo_root=tmp_path)
    outcome = await worker.execute(effect, tmp_path, result_path, prompt_path, pty_session=pty)

    assert isinstance(outcome, WorkerFailure)
    assert "summary" in outcome.error

async def test_previous_result_file_deleted(self, tmp_path: Path) -> None:
    """Pre-existing stale result file is deleted before spawn."""
    effect = _make_effect()
    result_path = tmp_path / "result.json"
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text("Do the thing")

    stale_result: dict[str, Any] = {"outcome": "done", "summary": "Stale"}
    result_path.write_text(json.dumps(stale_result))

    pty = _make_polling_pty(alive_count=2)  # exits, no new result written

    worker = ClaudeCodeWorker(repo_root=tmp_path)
    outcome = await worker.execute(effect, tmp_path, result_path, prompt_path, pty_session=pty)

    assert isinstance(outcome, WorkerFailure)
    assert "result file" in outcome.error
```

- [ ] **Step 6: Add test for session exits naturally WITH valid result**

```python
async def test_session_exits_with_valid_result(self, tmp_path: Path) -> None:
    """Session exits on its own with a valid result file -> WorkerSuccess."""
    effect = _make_effect()
    result_path = tmp_path / "result.json"
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text("Do the thing")

    valid_result: dict[str, Any] = {"outcome": "done", "summary": "All done"}
    pty = _make_polling_pty(
        alive_count=2,
        write_result=valid_result,
        result_path=result_path,
        write_after_spawns=0,
    )

    worker = ClaudeCodeWorker(repo_root=tmp_path)
    outcome = await worker.execute(effect, tmp_path, result_path, prompt_path, pty_session=pty)

    assert isinstance(outcome, WorkerSuccess)
    assert outcome.result == valid_result
    pty.kill.assert_not_called()  # session exited naturally
```

- [ ] **Step 7: Run tests — all should FAIL (worker still uses old `wait()` API)**

Run: `uv run pytest tests/orchestrator/test_worker.py -v`
Expected: All tests FAIL because the worker still calls `pty.wait()` which no longer exists on the mock.

- [ ] **Step 8: Commit test changes**

```bash
git add tests/orchestrator/test_worker.py
git commit -m "test: rewrite worker tests for polling-based completion"
```

---

### Task 2: Implement polling loop in worker

**Files:**
- Modify: `src/orca/orchestrator/worker.py`

Replace the `pty_session.wait(timeout)` call and post-wait logic with an async polling loop.

- [ ] **Step 1: Add constants for polling**

At the top of `worker.py`, update the constants section:

```python
# Poll result file and session liveness every this many seconds.
_POLL_INTERVAL = 2.0

# Grace period after detecting a valid result before killing the session.
# Allows the worker to flush remaining writes (git commits, file saves).
_RESULT_GRACE_PERIOD = 30.0

# Kill the worker if no valid result file is produced within this time.
_INACTIVITY_TIMEOUT = 300.0  # 5 minutes
```

- [ ] **Step 2: Replace the wait + result-check logic in `execute()`**

Replace everything from the `# d. Wait for tmux session` comment through the end of the method (lines 91-132) with:

```python
        # d. Poll for result file or session exit
        effective_timeout = float(inactivity_timeout) if inactivity_timeout else _INACTIVITY_TIMEOUT
        elapsed = 0.0
        result_detected_at: float | None = None

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
```

- [ ] **Step 3: Add `import asyncio` at the top of the file**

Add to the imports section:

```python
import asyncio
```

- [ ] **Step 4: Run tests — all should PASS**

Run: `uv run pytest tests/orchestrator/test_worker.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Run linter and type checker**

Run: `uv run ruff check src/orca/orchestrator/worker.py && uv run mypy src/orca/orchestrator/worker.py`
Expected: No errors.

- [ ] **Step 6: Commit**

```bash
git add src/orca/orchestrator/worker.py
git commit -m "feat: poll result.json for worker completion instead of waiting for session exit"
```

---

### Task 3: Append result-file warning to rendered prompts

**Files:**
- Modify: `src/orca/orchestrator/template.py`
- Modify: `tests/orchestrator/test_template.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/orchestrator/test_template.py`:

```python
def test_result_file_warning_appended(self, tmp_path: Path) -> None:
    """Rendered prompt includes the result-file termination warning."""
    template_content = "Do the thing. Write result to {{ result_path }}."
    template_file = tmp_path / "template.md"
    template_file.write_text(template_content)

    issue: dict[str, Any] = {
        "fields": {"title": "Fix bug"},
        "event_log": [],
        "decomposed_from": None,
        "depends_on": [],
        "children": [],
    }
    result_format: dict[str, Any] = {}
    result_path = Path("/tmp/result.json")

    output = render_prompt(template_file, tmp_path, issue, result_format, result_path)

    assert "final action" in output.lower()
    assert "terminate this session" in output.lower()
```

- [ ] **Step 2: Run test — should FAIL**

Run: `uv run pytest tests/orchestrator/test_template.py::TestRenderPrompt::test_result_file_warning_appended -v`
Expected: FAIL — warning not yet appended.

- [ ] **Step 3: Implement the warning suffix in `render_prompt()`**

In `src/orca/orchestrator/template.py`, add the constant and modify `render_prompt()`:

```python
_RESULT_FILE_WARNING = """

---

**IMPORTANT: Writing the result file is the final action of your session. \
The orchestrator will terminate this session shortly after detecting the result file. \
Complete ALL other work — git commits, file writes, code changes — before writing the result file.**"""
```

At the end of `render_prompt()`, change the return statement from:

```python
    return template.render(context)
```

to:

```python
    rendered = template.render(context)
    return rendered + _RESULT_FILE_WARNING
```

- [ ] **Step 4: Run test — should PASS**

Run: `uv run pytest tests/orchestrator/test_template.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Run linter and type checker**

Run: `uv run ruff check src/orca/orchestrator/template.py && uv run mypy src/orca/orchestrator/template.py`
Expected: No errors.

- [ ] **Step 6: Commit**

```bash
git add src/orca/orchestrator/template.py tests/orchestrator/test_template.py
git commit -m "feat: append result-file termination warning to all rendered prompts"
```

---

### Task 4: Full test suite + cleanup

**Files:**
- Modify: `src/orca/orchestrator/worker.py` (verify no dead code remains)

- [ ] **Step 1: Run full test suite**

Run: `uv run pytest -x -q`
Expected: All tests pass (303+).

- [ ] **Step 2: Run full lint + type check**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy src/`
Expected: No errors.

- [ ] **Step 3: Verify the old `_make_mock_pty` helper is removed from test_worker.py**

The old helper function should have been replaced in Task 1. Verify it doesn't exist:

Run: `grep -n "_make_mock_pty" tests/orchestrator/test_worker.py`
Expected: No output (function fully removed).

- [ ] **Step 4: Commit if any cleanup was needed**

```bash
git add -A
git commit -m "chore: cleanup after result-based worker completion"
```
