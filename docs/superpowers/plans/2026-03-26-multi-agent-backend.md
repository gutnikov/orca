# Multi-Agent Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow per-state worker kind selection in `orca.yml` so different states can use Claude Code, OpenCode, or future CLI agents within the same workflow.

**Architecture:** Replace the hardcoded `ClaudeCodeWorker` with a generic `CliAgentWorker` driven by a `KindConfig` registry. Each worker kind is a config entry describing CLI invocation differences (binary, prompt delivery, default flags). All shared logic (tmux, result polling, grace period) stays in one class.

**Tech Stack:** Python 3.12, dataclasses, asyncio, pytest

**Spec:** `docs/superpowers/specs/2026-03-26-multi-agent-backend-design.md`

---

### Task 1: Add `model` and `args` fields to `WorkerDef`

**Files:**
- Modify: `src/orca/engine/types.py:38-44`
- Test: `tests/engine/test_config.py`

- [ ] **Step 1: Write failing tests for new WorkerDef fields**

Add to `tests/engine/test_config.py` at the end of `TestWorkerDefFields`:

```python
def test_parse_worker_with_model(self) -> None:
    yaml_str = """\
issue:
  fields: {}
states:
  todo:
    worker:
      kind: claude-code
      prompt: prompts/work.md
      model: anthropic/claude-sonnet-4-5
      result_format:
        outcome:
          type: enum
          values: [go]
          description: d
    on:
      go: done
  done:
    terminal: true
initial: todo
"""
    cfg = parse_config(yaml_str)
    worker = cfg.states["todo"].worker
    assert worker is not None
    assert worker.model == "anthropic/claude-sonnet-4-5"

def test_parse_worker_with_args(self) -> None:
    yaml_str = """\
issue:
  fields: {}
states:
  todo:
    worker:
      kind: claude-code
      prompt: prompts/work.md
      args: ["--max-turns", "100"]
      result_format:
        outcome:
          type: enum
          values: [go]
          description: d
    on:
      go: done
  done:
    terminal: true
initial: todo
"""
    cfg = parse_config(yaml_str)
    worker = cfg.states["todo"].worker
    assert worker is not None
    assert worker.args == ("--max-turns", "100")

def test_parse_worker_model_and_args_default_none(self) -> None:
    yaml_str = """\
issue:
  fields: {}
states:
  todo:
    worker:
      kind: claude-code
      prompt: prompts/work.md
      result_format:
        outcome:
          type: enum
          values: [go]
          description: d
    on:
      go: done
  done:
    terminal: true
initial: todo
"""
    cfg = parse_config(yaml_str)
    worker = cfg.states["todo"].worker
    assert worker is not None
    assert worker.model is None
    assert worker.args is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/engine/test_config.py::TestWorkerDefFields -v`
Expected: FAIL — `WorkerDef` does not have `model` or `args` attributes.

- [ ] **Step 3: Add fields to WorkerDef**

In `src/orca/engine/types.py`, change the `WorkerDef` dataclass to:

```python
@dataclass(frozen=True)
class WorkerDef:
    kind: str
    prompt: str
    result_format: dict[str, ResultFormatField]
    timeout: int | None = None
    inactivity_timeout: int | None = None
    model: str | None = None
    args: tuple[str, ...] | None = None
```

- [ ] **Step 4: Parse new fields in config.py**

In `src/orca/engine/config.py`, in `_parse_state()`, update the `WorkerDef` construction (around line 99-105) to:

```python
model: str | None = worker_data.get("model")
raw_args = worker_data.get("args")
args: tuple[str, ...] | None = tuple(str(a) for a in raw_args) if raw_args is not None else None
worker = WorkerDef(
    kind=kind,
    prompt=prompt,
    result_format=result_format,
    timeout=timeout,
    inactivity_timeout=inactivity_timeout,
    model=model,
    args=args,
)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/engine/test_config.py::TestWorkerDefFields -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/orca/engine/types.py src/orca/engine/config.py tests/engine/test_config.py
git commit -m "feat: add model and args fields to WorkerDef"
```

---

### Task 2: Allow `opencode` as a worker kind in config validation

**Files:**
- Modify: `src/orca/engine/config.py:161-163`
- Test: `tests/engine/test_config.py`

- [ ] **Step 1: Write failing test for opencode kind**

Add to `tests/engine/test_config.py` at the end of `TestWorkerDefFields`:

```python
def test_opencode_kind_accepted(self) -> None:
    yaml_str = """\
issue:
  fields: {}
states:
  todo:
    worker:
      kind: opencode
      prompt: prompts/work.md
      model: anthropic/claude-sonnet-4-5
      result_format:
        outcome:
          type: enum
          values: [go]
          description: d
    on:
      go: done
  done:
    terminal: true
initial: todo
"""
    cfg = parse_config(yaml_str)
    worker = cfg.states["todo"].worker
    assert worker is not None
    assert worker.kind == "opencode"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/engine/test_config.py::TestWorkerDefFields::test_opencode_kind_accepted -v`
Expected: FAIL — `ConfigValidationError: kind must be 'claude-code'`

- [ ] **Step 3: Update validation to accept opencode**

In `src/orca/engine/config.py`, add a module-level constant and replace the kind check in `_validate()`:

```python
_ALLOWED_WORKER_KINDS = {"claude-code", "opencode"}
```

Replace lines 161-163:
```python
if state.worker.kind != "claude-code":
    msg = f"Worker for state '{name}': kind must be 'claude-code', got '{state.worker.kind}'"
    raise ConfigValidationError(msg)
```

With:
```python
if state.worker.kind not in _ALLOWED_WORKER_KINDS:
    msg = f"Worker for state '{name}': kind must be one of {sorted(_ALLOWED_WORKER_KINDS)}, got '{state.worker.kind}'"
    raise ConfigValidationError(msg)
```

- [ ] **Step 4: Update existing test for invalid kind error message**

In `tests/engine/test_config.py`, find `test_invalid_kind_rejected` and update the match pattern:

```python
def test_invalid_kind_rejected(self) -> None:
    yaml_str = """\
issue:
  fields: {}
states:
  todo:
    worker:
      kind: unknown-worker
      prompt: prompts/work.md
      result_format:
        outcome:
          type: enum
          values: [go]
          description: d
    on:
      go: done
  done:
    terminal: true
initial: todo
"""
    with pytest.raises(ConfigValidationError, match="kind must be one of"):
        parse_config(yaml_str)
```

- [ ] **Step 5: Run all config tests to verify they pass**

Run: `uv run pytest tests/engine/test_config.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add src/orca/engine/config.py tests/engine/test_config.py
git commit -m "feat: accept opencode as valid worker kind"
```

---

### Task 3: Replace `ClaudeCodeWorker` with `CliAgentWorker`

**Files:**
- Modify: `src/orca/orchestrator/worker.py`
- Modify: `tests/orchestrator/test_worker.py`

- [ ] **Step 1: Write test for command assembly — claude-code kind**

In `tests/orchestrator/test_worker.py`, replace the import of `ClaudeCodeWorker` and add command assembly tests. First, update imports at the top of the file:

```python
from orca.orchestrator.worker import CliAgentWorker, KindConfig, KIND_REGISTRY, WorkerFailure, WorkerSuccess
```

Add a new test class after the existing `_make_mock_pty` helper:

```python
class TestCommandAssembly:
    """Verify CliAgentWorker builds the correct CLI command per kind."""

    async def _spawn_and_capture(
        self,
        kind_config: KindConfig,
        tmp_path: Path,
        model: str | None = None,
        extra_args: list[str] | None = None,
    ) -> tuple[str, list[str], bytes | None]:
        """Run worker with a mock pty that captures spawn args. Returns (cmd, args, stdin_data)."""
        effect = _make_effect()
        result_path = tmp_path / "result.json"
        prompt_path = tmp_path / "prompt.md"
        prompt_path.write_text("Do the thing")
        valid_result: dict[str, Any] = {"outcome": "done", "summary": "All done"}
        pty = _make_mock_pty(exit_code=0, write_result=valid_result, result_path=result_path)

        worker = CliAgentWorker(repo_root=tmp_path, kind_config=kind_config)
        await worker.execute(
            effect, tmp_path, result_path, prompt_path, pty_session=pty, model=model, extra_args=extra_args,
        )
        call_args = pty.spawn.call_args
        return call_args[0][0], list(call_args[0][1]), call_args[1].get("stdin_data")

    @pytest.mark.asyncio()
    async def test_claude_code_command(self, tmp_path: Path) -> None:
        kind_config = KIND_REGISTRY["claude-code"]
        cmd, args, stdin_data = await self._spawn_and_capture(kind_config, tmp_path)
        assert cmd == "claude"
        assert "--dangerously-skip-permissions" in args
        assert "--max-turns" in args
        assert "50" in args
        assert stdin_data is not None
        assert len(stdin_data) > 0

    @pytest.mark.asyncio()
    async def test_opencode_command(self, tmp_path: Path) -> None:
        kind_config = KIND_REGISTRY["opencode"]
        cmd, args, stdin_data = await self._spawn_and_capture(kind_config, tmp_path, model="anthropic/claude-sonnet-4-5")
        assert cmd == "opencode"
        assert args[0] == "run"
        # Prompt is the second arg (positional after subcommand)
        assert len(args[1]) > 0  # prompt text
        assert "-m" in args
        assert "anthropic/claude-sonnet-4-5" in args
        assert stdin_data is None

    @pytest.mark.asyncio()
    async def test_extra_args_appended(self, tmp_path: Path) -> None:
        kind_config = KIND_REGISTRY["claude-code"]
        cmd, args, stdin_data = await self._spawn_and_capture(
            kind_config, tmp_path, extra_args=["--verbose"],
        )
        assert "--verbose" in args
        # Default args still present
        assert "--dangerously-skip-permissions" in args

    @pytest.mark.asyncio()
    async def test_model_ignored_when_none(self, tmp_path: Path) -> None:
        kind_config = KIND_REGISTRY["claude-code"]
        cmd, args, stdin_data = await self._spawn_and_capture(kind_config, tmp_path, model=None)
        assert "-m" not in args
```

- [ ] **Step 2: Run command assembly tests to verify they fail**

Run: `uv run pytest tests/orchestrator/test_worker.py::TestCommandAssembly -v`
Expected: FAIL — `CliAgentWorker` and `KindConfig` do not exist yet.

- [ ] **Step 3: Implement KindConfig, KIND_REGISTRY, and CliAgentWorker**

In `src/orca/orchestrator/worker.py`, replace the `ClaudeCodeWorker` class (lines 54-163) with:

```python
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
```

Keep the `Worker` protocol but add the new parameters:

```python
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
```

- [ ] **Step 4: Update existing tests to use CliAgentWorker**

In `tests/orchestrator/test_worker.py`, rename the test class `TestClaudeCodeWorker` to `TestCliAgentWorker` and update all instances of `ClaudeCodeWorker(repo_root=tmp_path)` to `CliAgentWorker(repo_root=tmp_path, kind_config=KIND_REGISTRY["claude-code"])`.

There are 7 test methods to update:
- `test_result_detected_while_alive`
- `test_timeout_no_result`
- `test_session_exits_no_result`
- `test_invalid_result_validation`
- `test_previous_result_file_deleted`
- `test_session_exits_with_valid_result`
- `test_env_passed_to_pty_session`

Each one changes from:
```python
worker = ClaudeCodeWorker(repo_root=tmp_path)
```
To:
```python
worker = CliAgentWorker(repo_root=tmp_path, kind_config=KIND_REGISTRY["claude-code"])
```

- [ ] **Step 5: Run all worker tests to verify they pass**

Run: `uv run pytest tests/orchestrator/test_worker.py -v`
Expected: All PASS (both `TestCliAgentWorker` and `TestCommandAssembly`)

- [ ] **Step 6: Update `__init__.py` exports**

In `src/orca/orchestrator/__init__.py`, replace `ClaudeCodeWorker` with `CliAgentWorker` and add `KindConfig` and `KIND_REGISTRY`:

Replace:
```python
from orca.orchestrator.worker import (
    ClaudeCodeWorker,
    Worker,
    WorkerFailure,
    WorkerOutcome,
    WorkerSuccess,
)
```

With:
```python
from orca.orchestrator.worker import (
    CliAgentWorker,
    KIND_REGISTRY,
    KindConfig,
    Worker,
    WorkerFailure,
    WorkerOutcome,
    WorkerSuccess,
)
```

And in `__all__`, replace `"ClaudeCodeWorker"` with `"CliAgentWorker"`, `"KIND_REGISTRY"`, `"KindConfig"`.

- [ ] **Step 7: Run all worker tests to verify they pass**

Run: `uv run pytest tests/orchestrator/test_worker.py -v`
Expected: All PASS (both `TestCliAgentWorker` and `TestCommandAssembly`)

- [ ] **Step 8: Commit**

```bash
git add src/orca/orchestrator/worker.py src/orca/orchestrator/__init__.py tests/orchestrator/test_worker.py
git commit -m "feat: replace ClaudeCodeWorker with generic CliAgentWorker"
```

---

### Task 4: Pass `model` and `args` through orchestrator to worker

**Files:**
- Modify: `src/orca/orchestrator/orchestrator.py:257-258,308-316`

- [ ] **Step 1: Update `_run_worker` signature and call**

In `src/orca/orchestrator/orchestrator.py`, update the `_run_worker` method signature (line 257-258) to accept `model` and `extra_args`:

```python
async def _run_worker(
    self,
    effect: DispatchWorkerEffect,
    worker: Worker,
    prompt_template: str,
    tracking_id: str,
    model: str | None = None,
    extra_args: tuple[str, ...] | None = None,
) -> WorkerOutcome:
```

Then update the `worker.execute()` call (around line 308-316) to pass them:

```python
outcome = await worker.execute(
    enriched_effect,
    workdir,
    result_path,
    prompt_path,
    inactivity_timeout,
    pty_session=tmux_session,
    env=worker_env,
    model=model,
    extra_args=list(extra_args) if extra_args else None,
)
```

- [ ] **Step 2: Update `_run_worker_with_backoff` to forward model and args**

Update `_run_worker_with_backoff` signature (line 238-244) and the call to `_run_worker` (line 255):

```python
async def _run_worker_with_backoff(
    self,
    effect: DispatchWorkerEffect,
    worker: Worker,
    prompt_template: str,
    backoff: float,
    tracking_id: str,
    model: str | None = None,
    extra_args: tuple[str, ...] | None = None,
) -> WorkerOutcome:
    """Wait for backoff delay, then run the worker."""
    if backoff > 0:
        logger.info(
            "Backing off %.0fs before retrying issue %s",
            backoff,
            effect.issue_id,
            extra={"event": "worker_backoff", "issue_id": effect.issue_id, "backoff_seconds": backoff},
        )
        await asyncio.sleep(backoff)
    return await self._run_worker(effect, worker, prompt_template, tracking_id, model=model, extra_args=extra_args)
```

- [ ] **Step 3: Update `_spawn_worker` to extract and pass model/args**

In `_spawn_worker` (around line 213-216), update the `asyncio.create_task` call to pass `model` and `args` from the state's worker definition:

```python
task: asyncio.Task[WorkerOutcome] = asyncio.create_task(
    self._run_worker_with_backoff(
        effect,
        worker,
        state_def.worker.prompt,
        backoff,
        tracking_id,
        model=state_def.worker.model,
        extra_args=state_def.worker.args,
    )
)
```

- [ ] **Step 4: Run type checker to verify correctness**

Run: `uv run mypy src/orca/orchestrator/orchestrator.py`
Expected: PASS with no errors

- [ ] **Step 5: Commit**

```bash
git add src/orca/orchestrator/orchestrator.py
git commit -m "feat: pass model and args from WorkerDef through to worker.execute"
```

---

### Task 5: Build workers from registry in runner.py

**Files:**
- Modify: `src/orca/orchestrator/runner.py:33,358,372`

- [ ] **Step 1: Update imports in runner.py**

Replace the import on line 33:

```python
from orca.orchestrator.worker import ClaudeCodeWorker
```

With:

```python
from orca.orchestrator.worker import CliAgentWorker, KIND_REGISTRY
```

- [ ] **Step 2: Build workers dict from registry**

Replace line 358:

```python
worker = ClaudeCodeWorker(repo_root)
```

With:

```python
workers = {name: CliAgentWorker(repo_root, config) for name, config in KIND_REGISTRY.items()}
```

- [ ] **Step 3: Update orchestrator instantiation**

Replace line 372:

```python
workers={"claude-code": worker},
```

With:

```python
workers=workers,
```

- [ ] **Step 4: Run type checker on runner.py**

Run: `uv run mypy src/orca/orchestrator/runner.py`
Expected: PASS with no errors

- [ ] **Step 5: Commit**

```bash
git add src/orca/orchestrator/runner.py
git commit -m "feat: build workers from KIND_REGISTRY instead of hardcoded ClaudeCodeWorker"
```

---

### Task 6: Full verification

**Files:** None (verification only)

- [ ] **Step 1: Run all tests**

Run: `uv run pytest -v`
Expected: All PASS

- [ ] **Step 2: Run linter**

Run: `uv run ruff check .`
Expected: No errors

- [ ] **Step 3: Run formatter check**

Run: `uv run ruff format --check .`
Expected: No errors

- [ ] **Step 4: Run type checker**

Run: `uv run mypy src/`
Expected: No errors

- [ ] **Step 5: Commit any remaining fixes if needed**

Only if previous steps revealed issues that needed fixing.
