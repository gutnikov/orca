# Worker Blocking / Unblocking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow workers to signal they are blocked via `result.json`, keeping the tmux session alive with paused timers until an explicit unblock command pushes a message into the session.

**Architecture:** New `WorkerBlockedEvent`/`WorkerUnblockedEvent` in the engine for audit logging only. The orchestrator intercepts `{"outcome": "blocked"}` in `result.json` before validation, pauses the inactivity timer, and waits for an `asyncio.Event` set by the `unblock_worker()` method. Unblocking is exposed via MCP tool, HTTP API, and CLI.

**Tech Stack:** Python 3.12, asyncio, tmux (send-keys), Starlette HTTP, FastMCP, argparse

---

### Task 1: Add engine event types

**Files:**
- Modify: `src/orca/engine/types.py:185-213`
- Test: `tests/engine/test_types.py`

- [ ] **Step 1: Write the failing test**

In `tests/engine/test_types.py`, add a test verifying the new types exist in the `Event` union:

```python
from orca.engine.types import Event, WorkerBlockedEvent, WorkerUnblockedEvent

class TestBlockingEventTypes:
    def test_worker_blocked_event_in_union(self) -> None:
        event = WorkerBlockedEvent(issue_id="A", timestamp="2026-01-01T00:00:00Z")
        assert isinstance(event, WorkerBlockedEvent)
        # Verify it's part of the Event union (type checker enforces this,
        # but runtime check that the module exports it)
        assert event.issue_id == "A"
        assert event.timestamp == "2026-01-01T00:00:00Z"

    def test_worker_unblocked_event_in_union(self) -> None:
        event = WorkerUnblockedEvent(issue_id="B", message="PR merged", timestamp="2026-01-01T00:00:00Z")
        assert isinstance(event, WorkerUnblockedEvent)
        assert event.issue_id == "B"
        assert event.message == "PR merged"
        assert event.timestamp == "2026-01-01T00:00:00Z"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/engine/test_types.py::TestBlockingEventTypes -v`
Expected: FAIL with `ImportError: cannot import name 'WorkerBlockedEvent'`

- [ ] **Step 3: Add the event types**

In `src/orca/engine/types.py`, after `WorkerFailedEvent` (line ~210), add:

```python
@dataclass(frozen=True)
class WorkerBlockedEvent:
    issue_id: str
    timestamp: str


@dataclass(frozen=True)
class WorkerUnblockedEvent:
    issue_id: str
    message: str
    timestamp: str
```

Update the `Event` union (line ~213):

```python
Event = CreateEvent | AdvanceEvent | WorkerResultEvent | WorkerFailedEvent | WorkerBlockedEvent | WorkerUnblockedEvent
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/engine/test_types.py::TestBlockingEventTypes -v`
Expected: PASS

- [ ] **Step 5: Run linting and type checks**

Run: `uv run ruff check src/orca/engine/types.py && uv run mypy src/orca/engine/types.py`
Expected: clean

- [ ] **Step 6: Commit**

```bash
git add src/orca/engine/types.py tests/engine/test_types.py
git commit -m "feat(engine): add WorkerBlockedEvent and WorkerUnblockedEvent types"
```

---

### Task 2: Add reducer handler for WorkerBlockedEvent

**Files:**
- Modify: `src/orca/engine/reducer.py:1-54` (imports and dispatch)
- Test: `tests/engine/test_reducer_worker_blocked.py` (new)

- [ ] **Step 1: Write failing tests**

Create `tests/engine/test_reducer_worker_blocked.py`:

```python
from __future__ import annotations

from collections.abc import Callable

from orca.engine.config import parse_config
from orca.engine.reducer import reduce
from orca.engine.types import (
    CreateEvent,
    ErrorEffect,
    State,
    WorkerBlockedEvent,
)


def _counter() -> Callable[[], str]:
    n = 0
    def next_id() -> str:
        nonlocal n
        n += 1
        return f"id-{n}"
    return next_id


def _clock(value: str = "2026-01-01T00:00:00Z") -> Callable[[], str]:
    return lambda: value


class TestWorkerBlocked:
    """WorkerBlockedEvent appends event_log entry, no effects."""

    def test_happy_path(self, simple_config_yaml: str) -> None:
        config = parse_config(simple_config_yaml)
        state = State(issues={}, worker_queues={})
        gen = _counter()

        # Create issue -> worker dispatched, worker_active=True
        state, _ = reduce(
            config, state,
            CreateEvent(issue_id="A", fields={"title": "T"}, timestamp="t0"),
            gen, _clock(),
        )
        assert state.issues["A"].worker_active is True

        # Worker signals blocked
        state, effects = reduce(
            config, state,
            WorkerBlockedEvent(issue_id="A", timestamp="t1"),
            gen, _clock(),
        )

        # No effects emitted
        assert effects == []
        # worker_active still True
        assert state.issues["A"].worker_active is True
        # event_log has a worker_blocked entry
        log_types = [e.type for e in state.issues["A"].event_log]
        assert "worker_blocked" in log_types

    def test_nonexistent_issue(self, simple_config_yaml: str) -> None:
        config = parse_config(simple_config_yaml)
        state = State(issues={}, worker_queues={})
        gen = _counter()

        state, effects = reduce(
            config, state,
            WorkerBlockedEvent(issue_id="NOPE", timestamp="t0"),
            gen, _clock(),
        )
        assert len(effects) == 1
        assert isinstance(effects[0], ErrorEffect)
        assert "NOPE" in effects[0].message

    def test_worker_not_active(self, simple_config_yaml: str) -> None:
        config = parse_config(simple_config_yaml)
        state = State(issues={}, worker_queues={})
        gen = _counter()

        state, _ = reduce(
            config, state,
            CreateEvent(issue_id="A", fields={"title": "T"}, timestamp="t0"),
            gen, _clock(),
        )
        state.issues["A"].worker_active = False

        state, effects = reduce(
            config, state,
            WorkerBlockedEvent(issue_id="A", timestamp="t1"),
            gen, _clock(),
        )
        assert len(effects) == 1
        assert isinstance(effects[0], ErrorEffect)

    def test_terminal_state(self, simple_config_yaml: str) -> None:
        config = parse_config(simple_config_yaml)
        state = State(issues={}, worker_queues={})
        gen = _counter()

        state, _ = reduce(
            config, state,
            CreateEvent(issue_id="A", fields={"title": "T"}, timestamp="t0"),
            gen, _clock(),
        )
        state.issues["A"].state = "done"
        state.issues["A"].worker_active = True  # shouldn't happen, but test validation

        state, effects = reduce(
            config, state,
            WorkerBlockedEvent(issue_id="A", timestamp="t1"),
            gen, _clock(),
        )
        assert len(effects) == 1
        assert isinstance(effects[0], ErrorEffect)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/engine/test_reducer_worker_blocked.py -v`
Expected: FAIL — reducer doesn't handle `WorkerBlockedEvent` yet

- [ ] **Step 3: Implement the handler**

In `src/orca/engine/reducer.py`:

1. Add imports — add `WorkerBlockedEvent` and `WorkerUnblockedEvent` to the import from `orca.engine.types`.

2. Add the handler function after `_handle_worker_failed`:

```python
def _handle_worker_blocked(
    config: StateMachineConfig,
    state: State,
    event: WorkerBlockedEvent,
    effects: list[Effect],
    ts: str,
) -> None:
    if event.issue_id not in state.issues:
        effects.append(ErrorEffect(issue_id=event.issue_id, message=f"Issue '{event.issue_id}' does not exist"))
        return

    issue = state.issues[event.issue_id]

    if issue.state == "done":
        effects.append(
            ErrorEffect(issue_id=event.issue_id, message=f"Issue '{event.issue_id}' is in terminal state 'done'")
        )
        return

    if not issue.worker_active:
        effects.append(
            ErrorEffect(issue_id=event.issue_id, message=f"Issue '{event.issue_id}' has worker_active=False")
        )
        return

    append_log(issue, event.timestamp, "worker_blocked", {})
```

3. Add dispatch in `reduce()` — after the `elif isinstance(event, WorkerFailedEvent):` block:

```python
    elif isinstance(event, WorkerBlockedEvent):
        _handle_worker_blocked(config, new_state, event, effects, ts)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/engine/test_reducer_worker_blocked.py -v`
Expected: PASS

- [ ] **Step 5: Run linting and type checks**

Run: `uv run ruff check src/orca/engine/reducer.py && uv run mypy src/orca/engine/reducer.py`
Expected: clean

- [ ] **Step 6: Commit**

```bash
git add src/orca/engine/reducer.py tests/engine/test_reducer_worker_blocked.py
git commit -m "feat(engine): add WorkerBlockedEvent reducer handler"
```

---

### Task 3: Add reducer handler for WorkerUnblockedEvent

**Files:**
- Modify: `src/orca/engine/reducer.py`
- Test: `tests/engine/test_reducer_worker_blocked.py` (append to same file)

- [ ] **Step 1: Write failing tests**

Append to `tests/engine/test_reducer_worker_blocked.py`:

```python
from orca.engine.types import WorkerUnblockedEvent


class TestWorkerUnblocked:
    """WorkerUnblockedEvent appends event_log entry with message, no effects."""

    def test_happy_path(self, simple_config_yaml: str) -> None:
        config = parse_config(simple_config_yaml)
        state = State(issues={}, worker_queues={})
        gen = _counter()

        state, _ = reduce(
            config, state,
            CreateEvent(issue_id="A", fields={"title": "T"}, timestamp="t0"),
            gen, _clock(),
        )
        assert state.issues["A"].worker_active is True

        state, effects = reduce(
            config, state,
            WorkerUnblockedEvent(issue_id="A", message="PR merged", timestamp="t1"),
            gen, _clock(),
        )

        assert effects == []
        assert state.issues["A"].worker_active is True
        # Find the unblocked log entry
        unblocked_entries = [e for e in state.issues["A"].event_log if e.type == "worker_unblocked"]
        assert len(unblocked_entries) == 1
        assert unblocked_entries[0].data == {"message": "PR merged"}

    def test_nonexistent_issue(self, simple_config_yaml: str) -> None:
        config = parse_config(simple_config_yaml)
        state = State(issues={}, worker_queues={})
        gen = _counter()

        state, effects = reduce(
            config, state,
            WorkerUnblockedEvent(issue_id="NOPE", message="hi", timestamp="t0"),
            gen, _clock(),
        )
        assert len(effects) == 1
        assert isinstance(effects[0], ErrorEffect)

    def test_worker_not_active(self, simple_config_yaml: str) -> None:
        config = parse_config(simple_config_yaml)
        state = State(issues={}, worker_queues={})
        gen = _counter()

        state, _ = reduce(
            config, state,
            CreateEvent(issue_id="A", fields={"title": "T"}, timestamp="t0"),
            gen, _clock(),
        )
        state.issues["A"].worker_active = False

        state, effects = reduce(
            config, state,
            WorkerUnblockedEvent(issue_id="A", message="hi", timestamp="t1"),
            gen, _clock(),
        )
        assert len(effects) == 1
        assert isinstance(effects[0], ErrorEffect)

    def test_terminal_state(self, simple_config_yaml: str) -> None:
        config = parse_config(simple_config_yaml)
        state = State(issues={}, worker_queues={})
        gen = _counter()

        state, _ = reduce(
            config, state,
            CreateEvent(issue_id="A", fields={"title": "T"}, timestamp="t0"),
            gen, _clock(),
        )
        state.issues["A"].state = "done"
        state.issues["A"].worker_active = True

        state, effects = reduce(
            config, state,
            WorkerUnblockedEvent(issue_id="A", message="hi", timestamp="t1"),
            gen, _clock(),
        )
        assert len(effects) == 1
        assert isinstance(effects[0], ErrorEffect)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/engine/test_reducer_worker_blocked.py::TestWorkerUnblocked -v`
Expected: FAIL

- [ ] **Step 3: Implement the handler**

In `src/orca/engine/reducer.py`, add after `_handle_worker_blocked`:

```python
def _handle_worker_unblocked(
    config: StateMachineConfig,
    state: State,
    event: WorkerUnblockedEvent,
    effects: list[Effect],
    ts: str,
) -> None:
    if event.issue_id not in state.issues:
        effects.append(ErrorEffect(issue_id=event.issue_id, message=f"Issue '{event.issue_id}' does not exist"))
        return

    issue = state.issues[event.issue_id]

    if issue.state == "done":
        effects.append(
            ErrorEffect(issue_id=event.issue_id, message=f"Issue '{event.issue_id}' is in terminal state 'done'")
        )
        return

    if not issue.worker_active:
        effects.append(
            ErrorEffect(issue_id=event.issue_id, message=f"Issue '{event.issue_id}' has worker_active=False")
        )
        return

    append_log(issue, event.timestamp, "worker_unblocked", {"message": event.message})
```

Add dispatch in `reduce()` after the `WorkerBlockedEvent` branch:

```python
    elif isinstance(event, WorkerUnblockedEvent):
        _handle_worker_unblocked(config, new_state, event, effects, ts)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/engine/test_reducer_worker_blocked.py -v`
Expected: all PASS

- [ ] **Step 5: Run full engine test suite + type checks**

Run: `uv run pytest tests/engine/ -v && uv run mypy src/orca/engine/`
Expected: all PASS, no type errors

- [ ] **Step 6: Commit**

```bash
git add src/orca/engine/reducer.py tests/engine/test_reducer_worker_blocked.py
git commit -m "feat(engine): add WorkerUnblockedEvent reducer handler"
```

---

### Task 4: Worker polling loop — blocked detection and unblock

**Files:**
- Modify: `src/orca/orchestrator/worker.py:60-76,121-304`
- Test: `tests/orchestrator/test_worker.py`

This is the largest task. The `execute()` method gains two new parameters (`unblock_event`, `unblock_message`) and the polling loop gets a blocked sub-loop.

- [ ] **Step 1: Write failing tests**

Append to `tests/orchestrator/test_worker.py`:

```python
@pytest.mark.asyncio()
class TestWorkerBlocking:
    """Tests for the blocked outcome detection and unblock mechanism."""

    async def test_blocked_outcome_pauses_and_unblocks(self, tmp_path: Path) -> None:
        """Worker writes blocked, then gets unblocked, then writes real result."""
        effect = _make_effect()
        result_path = tmp_path / "result.json"
        prompt_path = tmp_path / "prompt.md"
        prompt_path.write_text("Do the thing")

        unblock_event = asyncio.Event()
        unblock_message: list[str] = []

        # Track what happens: session stays alive, writes blocked first,
        # then after unblock writes the real result
        call_count = 0
        phase = "blocked"  # "blocked" -> "unblocked"

        pty = MagicMock()
        pty.session_name = "mock-session"
        pty.spawn = AsyncMock()
        pty.kill = MagicMock()
        pty.close = MagicMock()
        pty.send_keys = MagicMock(return_value=True)

        def _alive() -> bool:
            return True  # session stays alive throughout

        type(pty).alive = property(lambda self: _alive())

        # Write blocked result on spawn
        async def _spawn(*args: Any, **kwargs: Any) -> None:
            result_path.write_text(json.dumps({"outcome": "blocked"}))

        pty.spawn = AsyncMock(side_effect=_spawn)

        worker = CliAgentWorker(repo_root=tmp_path, kind_config=KIND_REGISTRY["claude-code"])

        # Schedule unblock after a short delay
        async def _delayed_unblock() -> None:
            await asyncio.sleep(0.1)
            # After blocked is detected, result.json should be deleted
            # Write the real result
            result_path.write_text(json.dumps({"outcome": "done", "summary": "Finished"}))
            unblock_message.clear()
            unblock_message.append("PR merged, continue")
            unblock_event.set()

        task = asyncio.create_task(_delayed_unblock())

        outcome = await worker.execute(
            effect, tmp_path, result_path, prompt_path,
            pty_session=pty,
            unblock_event=unblock_event,
            unblock_message=unblock_message,
        )

        await task
        assert isinstance(outcome, WorkerSuccess)
        assert outcome.result["outcome"] == "done"
        # send_keys was called with the unblock message
        pty.send_keys.assert_called_once_with("PR merged, continue")

    async def test_blocked_session_dies_returns_failure(self, tmp_path: Path) -> None:
        """If session dies while blocked, return WorkerFailure."""
        effect = _make_effect()
        result_path = tmp_path / "result.json"
        prompt_path = tmp_path / "prompt.md"
        prompt_path.write_text("Do the thing")

        unblock_event = asyncio.Event()
        unblock_message: list[str] = []

        alive_checks = 0

        pty = MagicMock()
        pty.session_name = "mock-session"
        pty.kill = MagicMock()
        pty.close = MagicMock()
        pty.send_keys = MagicMock(return_value=True)

        def _alive() -> bool:
            nonlocal alive_checks
            alive_checks += 1
            # Alive for first 2 checks (during initial poll + blocked detection),
            # then dies
            return alive_checks <= 2

        type(pty).alive = property(lambda self: _alive())

        async def _spawn(*args: Any, **kwargs: Any) -> None:
            result_path.write_text(json.dumps({"outcome": "blocked"}))

        pty.spawn = AsyncMock(side_effect=_spawn)

        worker = CliAgentWorker(repo_root=tmp_path, kind_config=KIND_REGISTRY["claude-code"])
        outcome = await worker.execute(
            effect, tmp_path, result_path, prompt_path,
            pty_session=pty,
            unblock_event=unblock_event,
            unblock_message=unblock_message,
        )

        assert isinstance(outcome, WorkerFailure)

    async def test_multiple_block_unblock_cycles(self, tmp_path: Path) -> None:
        """Worker blocks, unblocks, blocks again, unblocks again, then writes real result."""
        effect = _make_effect()
        result_path = tmp_path / "result.json"
        prompt_path = tmp_path / "prompt.md"
        prompt_path.write_text("Do the thing")

        unblock_event = asyncio.Event()
        unblock_message: list[str] = []
        cycle = 0

        pty = MagicMock()
        pty.session_name = "mock-session"
        pty.kill = MagicMock()
        pty.close = MagicMock()
        pty.send_keys = MagicMock(return_value=True)
        type(pty).alive = property(lambda self: True)

        async def _spawn(*args: Any, **kwargs: Any) -> None:
            result_path.write_text(json.dumps({"outcome": "blocked"}))

        pty.spawn = AsyncMock(side_effect=_spawn)

        worker = CliAgentWorker(repo_root=tmp_path, kind_config=KIND_REGISTRY["claude-code"])

        async def _delayed_unblocks() -> None:
            nonlocal cycle
            for i in range(2):
                await asyncio.sleep(0.1)
                cycle += 1
                if cycle < 2:
                    # Write blocked again after unblock
                    result_path.write_text(json.dumps({"outcome": "blocked"}))
                else:
                    # Final cycle: write real result
                    result_path.write_text(json.dumps({"outcome": "done", "summary": "Finally done"}))
                unblock_message.clear()
                unblock_message.append(f"Unblock cycle {cycle}")
                unblock_event.set()

        task = asyncio.create_task(_delayed_unblocks())

        outcome = await worker.execute(
            effect, tmp_path, result_path, prompt_path,
            pty_session=pty,
            unblock_event=unblock_event,
            unblock_message=unblock_message,
        )

        await task
        assert isinstance(outcome, WorkerSuccess)
        assert outcome.result["outcome"] == "done"
        # send_keys called twice (once per unblock)
        assert pty.send_keys.call_count == 2

    async def test_no_unblock_params_blocked_treated_as_stale(self, tmp_path: Path) -> None:
        """Without unblock_event, blocked outcome is treated like any unknown outcome
        (stale result deleted), and session eventually times out."""
        effect = _make_effect()
        result_path = tmp_path / "result.json"
        prompt_path = tmp_path / "prompt.md"
        prompt_path.write_text("Do the thing")

        pty = _make_polling_pty(alive_count=9999)

        async def _spawn(*args: Any, **kwargs: Any) -> None:
            result_path.write_text(json.dumps({"outcome": "blocked"}))

        pty.spawn = AsyncMock(side_effect=_spawn)

        worker = CliAgentWorker(repo_root=tmp_path, kind_config=KIND_REGISTRY["claude-code"])
        outcome = await worker.execute(
            effect, tmp_path, result_path, prompt_path,
            inactivity_timeout=0,
            pty_session=pty,
        )

        # Without unblock support, blocked is just a stale outcome → timeout
        assert isinstance(outcome, WorkerFailure)
```

Add `import asyncio` to the test file imports if not already present.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/orchestrator/test_worker.py::TestWorkerBlocking -v`
Expected: FAIL — `execute()` doesn't accept `unblock_event`/`unblock_message`

- [ ] **Step 3: Implement blocked detection and unblock in the polling loop**

In `src/orca/orchestrator/worker.py`:

1. Update the `Worker` protocol (lines 60-75) to add optional params:

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
        session_manifest: SessionManifest | None = None,
        session_id: str | None = None,
        run_context: dict[str, Any] | None = None,
        unblock_event: asyncio.Event | None = None,
        unblock_message: list[str] | None = None,
        on_blocked: Callable[[], None] | None = None,
        on_unblocked: Callable[[str], None] | None = None,
    ) -> WorkerOutcome: ...
```

2. Update `CliAgentWorker.execute()` signature (lines 121-135) to add the params:

```python
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
        on_blocked: Callable[[], None] | None = None,
        on_unblocked: Callable[[str], None] | None = None,
    ) -> WorkerOutcome:
```

3. In the polling loop, after JSON parsing succeeds (around line 203) but **before** calling `validate_result`, add blocked detection:

```python
            if result_detected_at is None and result_path.exists():
                try:
                    candidate = json.loads(result_path.read_text())

                    # Check for built-in "blocked" outcome before validation
                    if candidate.get("outcome") == "blocked" and unblock_event is not None:
                        # Check session is still alive before entering blocked state
                        if not pty_session.alive:
                            return WorkerFailure(error="session died while reporting blocked")
                        result_path.unlink(missing_ok=True)
                        logger.info(
                            "Worker blocked for issue %s — pausing timer",
                            effect.issue_id,
                            extra={"event": "worker_blocked", "issue_id": effect.issue_id},
                        )
                        if on_blocked is not None:
                            on_blocked()

                        # Blocked sub-loop: wait for unblock or session death
                        while True:
                            await asyncio.sleep(_POLL_INTERVAL)
                            if not pty_session.alive:
                                return WorkerFailure(error="session died while blocked")
                            if unblock_event.is_set():
                                unblock_event.clear()
                                msg = unblock_message[0] if unblock_message else ""
                                pty_session.send_keys(msg)
                                result_path.unlink(missing_ok=True)
                                logger.info(
                                    "Worker unblocked for issue %s",
                                    effect.issue_id,
                                    extra={"event": "worker_unblocked", "issue_id": effect.issue_id},
                                )
                                if on_unblocked is not None:
                                    on_unblocked(msg)
                                break
                        # Resume normal polling — do NOT increment elapsed for blocked time
                        continue

                    error = validate_result(candidate, effect.result_format)
                    # ... rest of existing validation logic
```

Note: the `continue` after the blocked sub-loop skips the rest of the iteration body (grace period check, session exit check, timeout check), restarting the normal poll loop. `elapsed` is not incremented during the blocked sub-loop since the outer loop's `elapsed += _POLL_INTERVAL` is only reached at the top of each outer iteration.

4. Also handle the case where `unblock_event is None` and outcome is `"blocked"` — it falls through to the existing stale-result-deletion logic since `"blocked"` won't be in `valid_outcomes`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/orchestrator/test_worker.py::TestWorkerBlocking -v`
Expected: PASS

- [ ] **Step 5: Run existing worker tests to verify no regression**

Run: `uv run pytest tests/orchestrator/test_worker.py -v`
Expected: all PASS

- [ ] **Step 6: Run type checks**

Run: `uv run mypy src/orca/orchestrator/worker.py`
Expected: clean

- [ ] **Step 7: Commit**

```bash
git add src/orca/orchestrator/worker.py tests/orchestrator/test_worker.py
git commit -m "feat(worker): add blocked outcome detection and unblock mechanism in polling loop"
```

---

### Task 5: Orchestrator — blocked workers registry and unblock_worker()

**Files:**
- Modify: `src/orca/orchestrator/orchestrator.py:44-100,344-441,617-655`
- Test: `tests/orchestrator/test_orchestrator.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/orchestrator/test_orchestrator.py` (or create a new test file if the existing one is large — check first). Add a unit test for the `unblock_worker` method:

```python
class TestUnblockWorker:
    def test_unblock_blocked_worker(self) -> None:
        """unblock_worker returns True and sets event for a blocked worker."""
        from orca.orchestrator.orchestrator import Orchestrator
        import asyncio

        # Create a minimal orchestrator (mock dependencies as needed)
        # ... (use existing test fixtures/patterns from the file)
        # Register a blocked worker manually
        event = asyncio.Event()
        msg_box: list[str] = []
        orchestrator._blocked_workers["issue-1"] = (event, msg_box)

        result = orchestrator.unblock_worker("issue-1", "PR merged")
        assert result is True
        assert event.is_set()
        assert msg_box == ["PR merged"]

    def test_unblock_non_blocked_worker(self) -> None:
        """unblock_worker returns False for a non-blocked worker."""
        # ... (use existing test fixtures)
        result = orchestrator.unblock_worker("issue-1", "hi")
        assert result is False
```

Note: adapt the test to match the existing test patterns in `test_orchestrator.py`. The exact fixture setup depends on how the file creates `Orchestrator` instances. Read the file first and follow its conventions.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/orchestrator/test_orchestrator.py::TestUnblockWorker -v`
Expected: FAIL — `_blocked_workers` doesn't exist

- [ ] **Step 3: Implement the registry and method**

In `src/orca/orchestrator/orchestrator.py`:

1. Add to `__init__` (after `self._progress_sessions`, around line 85):

```python
        # Maps issue_id -> (unblock_event, message_box) for blocked workers
        self._blocked_workers: dict[str, tuple[asyncio.Event, list[str]]] = {}
```

2. Add the `unblock_worker` method (after `set_cold_session`, around line 172):

```python
    def unblock_worker(self, issue_id: str, message: str) -> bool:
        """Unblock a blocked worker by setting its event and message.

        Returns False if the issue is not currently blocked.
        """
        entry = self._blocked_workers.get(issue_id)
        if entry is None:
            return False
        event, msg_box = entry
        msg_box.clear()
        msg_box.append(message)
        event.set()
        return True
```

3. In `_run_worker()` (around line 344), create the unblock event/message and pass to `worker.execute()`. Before the `try: outcome = await worker.execute(...)` block:

```python
        # Create unblock channel for this worker
        unblock_event = asyncio.Event()
        unblock_message: list[str] = []
```

4. Pass them to `worker.execute()`:

```python
            outcome = await worker.execute(
                enriched_effect,
                workdir,
                result_path,
                prompt_path,
                inactivity_timeout,
                pty_session=tmux_session,
                model=model,
                extra_args=list(extra_args) if extra_args else None,
                session_manifest=self._session_sync.manifest if self._session_sync else None,
                session_id=tracking_id,
                run_context=run_context,
                unblock_event=unblock_event,
                unblock_message=unblock_message,
            )
```

5. Register the unblock channel in `_blocked_workers` before execute, remove in `finally`:

```python
        self._blocked_workers[effect.issue_id] = (unblock_event, unblock_message)
```

In the `finally` block (after existing cleanup):

```python
        finally:
            self._blocked_workers.pop(effect.issue_id, None)
            # ... existing scrollback save + tmux cleanup
```

6. Define `on_blocked`/`on_unblocked` callbacks in `_run_worker()` that emit engine events:

```python
        def _on_blocked() -> None:
            from orca.engine.types import WorkerBlockedEvent
            ts = self.now()
            self._state, _ = reduce(
                self._config, self._state,
                WorkerBlockedEvent(issue_id=effect.issue_id, timestamp=ts),
                self.generate_id, self.now,
            )
            self.persistence.save(self._state)

        def _on_unblocked(message: str) -> None:
            from orca.engine.types import WorkerUnblockedEvent
            ts = self.now()
            self._state, _ = reduce(
                self._config, self._state,
                WorkerUnblockedEvent(issue_id=effect.issue_id, message=message, timestamp=ts),
                self.generate_id, self.now,
            )
            self.persistence.save(self._state)
```

7. Pass all four params to `worker.execute()`:

```python
            outcome = await worker.execute(
                ...,
                unblock_event=unblock_event,
                unblock_message=unblock_message,
                on_blocked=_on_blocked,
                on_unblocked=_on_unblocked,
            )
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/orchestrator/test_orchestrator.py::TestUnblockWorker -v`
Expected: PASS

- [ ] **Step 5: Run full orchestrator test suite + type checks**

Run: `uv run pytest tests/orchestrator/ -v && uv run mypy src/orca/orchestrator/`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add src/orca/orchestrator/orchestrator.py src/orca/orchestrator/worker.py
git commit -m "feat(orchestrator): add blocked workers registry, unblock_worker, and engine event emission"
```

---

### Task 6: RunManager — unblock_worker()

**Files:**
- Modify: `src/orca/daemon/manager.py`
- Test: `tests/daemon/test_manager.py`

- [ ] **Step 1: Write failing test**

Append to `tests/daemon/test_manager.py`:

```python
class TestUnblockWorker:
    def test_not_found_run(self, manager: RunManager) -> None:
        with pytest.raises(ValueError, match="not found"):
            manager.unblock_worker("nonexistent:default", "issue-1", "hello")

    def test_no_orchestrator(self, manager: RunManager) -> None:
        # Create a run entry without an orchestrator
        # ... (follow existing patterns in the file for creating run entries)
        with pytest.raises(ValueError, match="no orchestrator"):
            manager.unblock_worker(run_id, "issue-1", "hello")
```

Adapt to the existing test patterns in `test_manager.py`.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/daemon/test_manager.py::TestUnblockWorker -v`
Expected: FAIL — `unblock_worker` doesn't exist

- [ ] **Step 3: Implement**

In `src/orca/daemon/manager.py`, add after `retry_issue`:

```python
    def unblock_worker(self, run_id: str, issue_id: str, message: str) -> None:
        """Unblock a blocked worker in a run."""
        run_info = self._runs.get(run_id)
        if run_info is None:
            msg = f"Run '{run_id}' not found"
            raise ValueError(msg)
        if run_info.orchestrator is None:
            msg = f"Run '{run_id}' has no orchestrator"
            raise ValueError(msg)
        if not run_info.orchestrator.unblock_worker(issue_id, message):
            msg = f"Issue '{issue_id}' is not blocked in run '{run_id}'"
            raise ValueError(msg)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/daemon/test_manager.py::TestUnblockWorker -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/orca/daemon/manager.py tests/daemon/test_manager.py
git commit -m "feat(daemon): add RunManager.unblock_worker()"
```

---

### Task 7: HTTP API — unblock endpoint

**Files:**
- Modify: `src/orca/daemon/http_api.py:224-244`
- Test: `tests/daemon/test_http_api.py`

- [ ] **Step 1: Write failing test**

Append to `tests/daemon/test_http_api.py`:

```python
class TestUnblockWorker:
    def test_run_not_found(self, client: TestClient) -> None:
        resp = client.post(
            "/api/runs/nonexistent:default/unblock/issue-1",
            json={"message": "hello"},
        )
        assert resp.status_code == 404

    def test_missing_message(self, client: TestClient) -> None:
        resp = client.post(
            "/api/runs/nonexistent:default/unblock/issue-1",
            json={},
        )
        assert resp.status_code == 400
        assert "message" in resp.json()["error"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/daemon/test_http_api.py::TestUnblockWorker -v`
Expected: FAIL — route doesn't exist (404 from Starlette, not our custom 404)

- [ ] **Step 3: Implement**

In `src/orca/daemon/http_api.py`:

1. Add the handler function (after `_retry_issue`):

```python
async def _unblock_worker(request: Request) -> JSONResponse:
    manager: RunManager = request.app.state.manager
    run_id: str = request.path_params["run_id"]
    issue_id: str = request.path_params["issue_id"]

    try:
        body: dict[str, Any] = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON body"}, status_code=400)

    message = body.get("message")
    if not message:
        return JSONResponse({"error": "message is required"}, status_code=400)

    try:
        manager.unblock_worker(run_id, issue_id, message)
    except ValueError as exc:
        error_msg = str(exc)
        status = 404 if "not found" in error_msg else 400
        return JSONResponse({"error": error_msg}, status_code=status)

    return JSONResponse({"status": "ok"})
```

2. Add the route (in `create_app`, before the catch-all `_get_run` route):

```python
        Route("/api/runs/{run_id:path}/unblock/{issue_id}", _unblock_worker, methods=["POST"]),
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/daemon/test_http_api.py::TestUnblockWorker -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/orca/daemon/http_api.py tests/daemon/test_http_api.py
git commit -m "feat(daemon): add POST /api/runs/{run_id}/unblock/{issue_id} endpoint"
```

---

### Task 8: DaemonClient — unblock_worker()

**Files:**
- Modify: `src/orca/daemon/client.py`
- Test: `tests/daemon/test_client.py`

- [ ] **Step 1: Write failing test**

Append to `tests/daemon/test_client.py` (follow existing patterns):

```python
class TestUnblockWorker:
    async def test_method_exists(self) -> None:
        """Verify the unblock_worker method exists on DaemonClient."""
        from orca.daemon.client import DaemonClient
        client = DaemonClient(Path("/tmp/fake.sock"))
        assert hasattr(client, "unblock_worker")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/daemon/test_client.py::TestUnblockWorker -v`
Expected: FAIL

- [ ] **Step 3: Implement**

In `src/orca/daemon/client.py`, add after `retry_issue`:

```python
    async def unblock_worker(self, run_id: str, issue_id: str, message: str) -> dict[str, Any]:
        return await self._post_json(
            f"/api/runs/{run_id}/unblock/{issue_id}",
            {"message": message},
        )
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/daemon/test_client.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/orca/daemon/client.py tests/daemon/test_client.py
git commit -m "feat(daemon): add DaemonClient.unblock_worker()"
```

---

### Task 9: MCP tool — orca_unblock_worker

**Files:**
- Modify: `src/orca/daemon/mcp_tools.py`
- Test: `tests/daemon/test_mcp_tools.py`

- [ ] **Step 1: Write failing test**

Append to `tests/daemon/test_mcp_tools.py` (follow existing patterns):

```python
class TestUnblockWorkerTool:
    def test_tool_registered(self) -> None:
        from orca.daemon.mcp_tools import create_mcp_server
        server = create_mcp_server()
        tool_names = [t.name for t in server._tool_manager.list_tools()]
        assert "orca_unblock_worker" in tool_names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/daemon/test_mcp_tools.py::TestUnblockWorkerTool -v`
Expected: FAIL

- [ ] **Step 3: Implement**

In `src/orca/daemon/mcp_tools.py`, add the tool function (after `orca_resume_run`):

```python
    async def orca_unblock_worker(root: str, run_id: str, issue_id: str, message: str) -> str:
        """Unblock a blocked worker by sending it a message.

        Args:
            root: Absolute path to the target project's repo root.
            run_id: The run identifier.
            issue_id: The issue identifier of the blocked worker.
            message: Message to send to the worker explaining what changed.

        Returns JSON with status, or an error message.
        """
        result = await _get_client(root).unblock_worker(run_id, issue_id, message)
        return json.dumps(result)
```

Register it (after `orca_resume_run` registration):

```python
    server.add_tool(orca_unblock_worker, name="orca_unblock_worker")
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/daemon/test_mcp_tools.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/orca/daemon/mcp_tools.py tests/daemon/test_mcp_tools.py
git commit -m "feat(mcp): add orca_unblock_worker tool"
```

---

### Task 10: CLI — orca unblock command

**Files:**
- Create: `src/orca/cli/unblock_cmd.py`
- Modify: `src/orca/cli/main.py`
- Test: `tests/cli/test_main.py`

- [ ] **Step 1: Write failing test**

Append to `tests/cli/test_main.py`:

```python
class TestUnblockParser:
    def test_parser_accepts_unblock(self) -> None:
        from orca.cli.main import build_parser
        parser = build_parser()
        args = parser.parse_args(["unblock", "my-run:default", "issue-1", "-m", "PR merged"])
        assert args.subcommand == "unblock"
        assert args.run_id == "my-run:default"
        assert args.issue_id == "issue-1"
        assert args.message == "PR merged"

    def test_parser_requires_message(self) -> None:
        from orca.cli.main import build_parser
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["unblock", "my-run:default", "issue-1"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/cli/test_main.py::TestUnblockParser -v`
Expected: FAIL — `unblock` subcommand doesn't exist

- [ ] **Step 3: Add parser entry**

In `src/orca/cli/main.py`, add after the `logs_parser` block (around line 78):

```python
    # orca unblock <run_id> <issue_id> -m "message"
    unblock_parser = sub.add_parser("unblock", help="Unblock a blocked worker")
    unblock_parser.add_argument("run_id", type=str)
    unblock_parser.add_argument("issue_id", type=str)
    unblock_parser.add_argument("-m", "--message", type=str, required=True, help="Message to send to the worker")
```

Add the dispatch in `main()` (after the `logs` block):

```python
    elif args.subcommand == "unblock":
        from orca.cli.unblock_cmd import unblock_command

        unblock_command(args.run_id, args.issue_id, args.message, root=args.root)
```

- [ ] **Step 4: Create the command handler**

Create `src/orca/cli/unblock_cmd.py`:

```python
"""orca unblock <run_id> <issue_id> -m <message> — unblock a blocked worker."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import aiohttp


def unblock_command(run_id: str, issue_id: str, message: str, root: Path | None = None) -> None:
    """POST /api/runs/{run_id}/unblock/{issue_id} to the daemon."""
    import asyncio

    from orca.cli.daemon_cmd import _repo_root
    from orca.daemon.lifecycle import check_daemon_running, socket_path

    repo = _repo_root(root)
    if not check_daemon_running(repo):
        print("Error: daemon is not running. Start it with: orca daemon start", file=sys.stderr)
        raise SystemExit(1)

    sock = socket_path(repo)

    async def _unblock() -> None:
        connector = aiohttp.UnixConnector(path=str(sock))
        async with (
            aiohttp.ClientSession(connector=connector) as session,
            session.post(
                f"http://localhost/api/runs/{run_id}/unblock/{issue_id}",
                json={"message": message},
            ) as resp,
        ):
            body = await resp.json()
            if resp.status == 200:
                print(f"Worker unblocked: {issue_id} in run {run_id}")
            else:
                print(f"Error: {body.get('error', json.dumps(body))}", file=sys.stderr)
                raise SystemExit(1)

    asyncio.run(_unblock())
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/cli/test_main.py::TestUnblockParser -v`
Expected: PASS

- [ ] **Step 6: Run linting and type checks on new files**

Run: `uv run ruff check src/orca/cli/unblock_cmd.py src/orca/cli/main.py && uv run mypy src/orca/cli/`
Expected: clean

- [ ] **Step 7: Commit**

```bash
git add src/orca/cli/unblock_cmd.py src/orca/cli/main.py tests/cli/test_main.py
git commit -m "feat(cli): add orca unblock command"
```

---

### Task 11: Full integration test and final verification

**Files:**
- Test: run all tests

- [ ] **Step 1: Run full test suite**

Run: `uv run pytest -v`
Expected: all PASS

- [ ] **Step 2: Run linting**

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: clean

- [ ] **Step 3: Run type checks**

Run: `uv run mypy src/`
Expected: clean

- [ ] **Step 4: Final commit if any formatting fixes needed**

```bash
git add -A
git commit -m "chore: formatting fixes"
```
