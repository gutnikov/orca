# Built-in `done` and `failed` States — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `terminal: true` with two built-in reserved states (`done` and `failed`) so the engine distinguishes success exits from retryable failures.

**Architecture:** Remove `terminal` field from `StateDef`. Add `BUILTIN_STATES` constant. In the reducer, when a transition targets `failed`, emit a `WorkerFailedEvent` instead of transitioning. When targeting `done`, transition as before but use `issue.state == "done"` for terminal checks. Update all ~20 call sites that check `state_def.terminal`.

**Tech Stack:** Python 3.12, dataclasses, pytest

---

### Task 1: Add `BUILTIN_STATES` constant and remove `terminal` from `StateDef`

**Files:**
- Modify: `src/orca/engine/types.py:64-69`
- Test: `tests/engine/test_types.py`

- [ ] **Step 1: Write the failing test**

In `tests/engine/test_types.py`, add:

```python
from orca.engine.types import BUILTIN_STATES, StateDef


def test_builtin_states_contains_done_and_failed() -> None:
    assert BUILTIN_STATES == frozenset({"done", "failed"})


def test_state_def_has_no_terminal_field() -> None:
    sd = StateDef()
    assert not hasattr(sd, "terminal")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/engine/test_types.py::test_builtin_states_contains_done_and_failed tests/engine/test_types.py::test_state_def_has_no_terminal_field -v`
Expected: FAIL — `BUILTIN_STATES` doesn't exist, `StateDef` still has `terminal`

- [ ] **Step 3: Modify `types.py`**

In `src/orca/engine/types.py`, add the constant before `StateDef`:

```python
BUILTIN_STATES = frozenset({"done", "failed"})
```

Remove `terminal: bool = False` from the `StateDef` dataclass so it becomes:

```python
@dataclass(frozen=True)
class StateDef:
    worker: WorkerDef | None = None
    on: dict[str, OnRule] = field(default_factory=dict)
    max_workers: int | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/engine/test_types.py::test_builtin_states_contains_done_and_failed tests/engine/test_types.py::test_state_def_has_no_terminal_field -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/orca/engine/types.py tests/engine/test_types.py
git commit -m "feat(engine): add BUILTIN_STATES, remove terminal from StateDef"
```

---

### Task 2: Update config parsing — remove `terminal`, add built-in state validation, synthetic `done` StateDef

**Files:**
- Modify: `src/orca/engine/config.py:82-131` (parsing), `src/orca/engine/config.py:156-303` (validation)
- Modify: `src/orca/engine/types.py:89-90` (`get_state`)
- Test: `tests/engine/test_config.py`

- [ ] **Step 1: Write failing tests**

In `tests/engine/test_config.py`, add a new test class:

```python
class TestBuiltinStates:
    def test_done_not_in_states_dict(self, simple_config_yaml: str) -> None:
        """done is not in the states dict — it's built-in."""
        cfg = parse_config(simple_config_yaml)
        assert "done" not in cfg.types["default"].states

    def test_get_state_done_returns_synthetic(self, simple_config_yaml: str) -> None:
        """get_state for 'done' returns a StateDef with no worker/on."""
        cfg = parse_config(simple_config_yaml)
        sd = cfg.get_state("default", "done")
        assert sd.worker is None
        assert sd.on == {}

    def test_get_state_failed_raises(self, simple_config_yaml: str) -> None:
        """get_state for 'failed' should raise — failed is never an issue state."""
        cfg = parse_config(simple_config_yaml)
        with pytest.raises(KeyError):
            cfg.get_state("default", "failed")

    def test_defining_done_in_states_raises(self) -> None:
        yaml_str = """\
issue:
  fields:
    title:
      type: string
      description: t

states:
  work:
    worker:
      kind: claude-code
      prompt: p.md
      result_format:
        outcome:
          type: enum
          values: [finish]
          description: d
    on:
      finish: done

  done:
    worker:
      kind: claude-code
      prompt: p.md

initial: work
"""
        with pytest.raises(ConfigValidationError, match="reserved"):
            parse_config(yaml_str)

    def test_defining_failed_in_states_raises(self) -> None:
        yaml_str = """\
issue:
  fields:
    title:
      type: string
      description: t

states:
  work:
    worker:
      kind: claude-code
      prompt: p.md
      result_format:
        outcome:
          type: enum
          values: [finish]
          description: d
    on:
      finish: done

  failed:
    worker:
      kind: claude-code
      prompt: p.md

initial: work
"""
        with pytest.raises(ConfigValidationError, match="reserved"):
            parse_config(yaml_str)

    def test_transition_to_failed_is_valid(self) -> None:
        yaml_str = """\
issue:
  fields:
    title:
      type: string
      description: t

states:
  work:
    worker:
      kind: claude-code
      prompt: p.md
      result_format:
        outcome:
          type: enum
          values: [ok, fail]
          description: d
    on:
      ok: done
      fail: failed

initial: work
"""
        cfg = parse_config(yaml_str)
        state = cfg.get_state("default", "work")
        assert state.on["fail"] == OnTransition(target="failed")
        assert state.on["ok"] == OnTransition(target="done")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/engine/test_config.py::TestBuiltinStates -v`
Expected: FAIL

- [ ] **Step 3: Update conftest fixtures**

In `tests/engine/conftest.py`, update **all four** YAML fixtures to remove the `done: terminal: true` block. The configs use `done` as a transition target which is now built-in.

For `simple_config_yaml`, remove lines:
```yaml
  done:
    terminal: true
```

For `decompose_config_yaml`, remove lines:
```yaml
  done:
    terminal: true
```

For `max_workers_config_yaml`, remove lines:
```yaml
  done:
    terminal: true
```

For `feedback_config_yaml`, remove lines:
```yaml
  done:
    terminal: true
```

- [ ] **Step 4: Update `_parse_state` in config.py**

In `src/orca/engine/config.py`, function `_parse_state` (line 82): remove the `terminal` parsing and the `terminal=terminal` kwarg:

```python
def _parse_state(name: str, raw_data: dict[str, Any] | None) -> StateDef:
    if raw_data is None:
        raw_data = {}
    # YAML parses bare `on` as boolean True key; normalize to string key
    data: dict[str, Any] = {}
    for k, v in raw_data.items():
        data[str(k)] = v

    max_workers = data.get("max_workers")

    worker: WorkerDef | None = None
    worker_data = data.get("worker")
    if worker_data is not None:
        kind: str = worker_data.get("kind", "")
        prompt: str = worker_data.get("prompt", "")
        timeout: int | None = worker_data.get("timeout")
        inactivity_timeout: int | None = worker_data.get("inactivity_timeout")
        rf_data: dict[str, Any] = worker_data.get("result_format", {})
        result_format: dict[str, ResultFormatField] = {}
        for field_name, field_data in rf_data.items():
            result_format[field_name] = _parse_result_format_field(field_name, field_data)
        model: str | None = worker_data.get("model")
        raw_args = worker_data.get("args")
        args: tuple[str, ...] | None = tuple(str(a) for a in raw_args) if raw_args is not None else None
        progress: bool = bool(worker_data.get("progress", False))
        worker = WorkerDef(
            kind=kind,
            prompt=prompt,
            result_format=result_format,
            timeout=timeout,
            inactivity_timeout=inactivity_timeout,
            model=model,
            args=args,
            progress=progress,
        )

    on: dict[str, OnRule] = {}
    on_data = data.get("True") or data.get("on")
    if on_data is not None:
        for key, value in on_data.items():
            on[key] = _parse_on_rule(key, value)

    return StateDef(
        worker=worker,
        on=on,
        max_workers=max_workers,
    )
```

- [ ] **Step 5: Update `_validate` in config.py**

Add `from orca.engine.types import BUILTIN_STATES` to the imports.

In `_validate`, apply these changes:

1. **Add reserved-name check** at the top of the type loop (after `state_names = ...`):

```python
        # Reject built-in state names defined by the user
        for reserved in BUILTIN_STATES:
            if reserved in state_names:
                msg = f"Type '{type_name}': state '{reserved}' is reserved (built-in) and must not be defined"
                raise ConfigValidationError(msg)
```

2. **Remove** the "Rule 6: at least one terminal state" block (lines 177-181). `done` is always available as a built-in.

3. **Update Rule 2** (transition target validation, line 256-262): allow `done` and `failed` as valid targets:

```python
            # Rule 2: every on target references an existing state or built-in
            for key, rule in state.on.items():
                if isinstance(rule, OnTransition):
                    if rule.target not in state_names and rule.target not in BUILTIN_STATES:
                        msg = (
                            f"Type '{type_name}', on.{key} target '{rule.target}' in state '{name}' "
                            f"does not exist in states"
                        )
                        raise ConfigValidationError(msg)
                    reachable.add(rule.target)
```

4. **Update Rule 5** (terminal states validation, lines 217-221): remove entirely — no more `terminal` field.

5. **Update Rule 8** (reachability, lines 292-303): remove the terminal exemption since there's no `state.terminal` anymore. The check becomes:

```python
        # Rule 8: every non-initial, non-passive state must be reachable
        for name, state in type_def.states.items():
            if name in reachable:
                continue
            # Passive states (no worker, no on) are exempt
            is_passive = state.worker is None and not state.on
            if is_passive:
                continue
            msg = f"Type '{type_name}', state '{name}' is not reachable from any on rule"
            raise ConfigValidationError(msg)
```

- [ ] **Step 6: Update `get_state` in types.py**

In `src/orca/engine/types.py`, the `StateMachineConfig.get_state` method must return a synthetic `StateDef` for `done` and raise for `failed`:

```python
    _DONE_SENTINEL = StateDef()

    def get_state(self, type_name: str, state_name: str) -> StateDef:
        if state_name == "done":
            return self._DONE_SENTINEL
        return self.types[type_name].states[state_name]
```

Note: `_DONE_SENTINEL` is a class-level constant defined just above the method. Since `StateDef` is frozen with defaults `worker=None, on={}, max_workers=None`, this works as a sentinel with no behavior. `failed` is not handled — accessing it raises `KeyError` naturally since it's not in any states dict.

- [ ] **Step 7: Update existing test that checks `terminal`**

In `tests/engine/test_config.py`, class `TestParseSimpleConfig`, update `test_terminal_state`:

```python
    def test_done_is_builtin(self, simple_config_yaml: str) -> None:
        cfg = parse_config(simple_config_yaml)
        # done is not in the states dict
        assert "done" not in cfg.types["default"].states
        # but get_state returns a synthetic StateDef
        sd = cfg.get_state("default", "done")
        assert sd.worker is None
        assert sd.on == {}
```

Remove the old `test_terminal_state` method.

- [ ] **Step 8: Run all config tests**

Run: `uv run pytest tests/engine/test_config.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add src/orca/engine/types.py src/orca/engine/config.py tests/engine/test_config.py tests/engine/conftest.py
git commit -m "feat(engine): built-in done/failed in config parsing and validation"
```

---

### Task 3: Update reducer — handle `failed` target as `WorkerFailedEvent`, replace `terminal` checks

**Files:**
- Modify: `src/orca/engine/reducer.py`
- Test: `tests/engine/test_reducer_worker_result.py`

- [ ] **Step 1: Write failing tests**

In `tests/engine/test_reducer_worker_result.py`, add:

```python
class TestFailedBuiltinTarget:
    """When a transition targets 'failed', the engine treats it as a worker failure."""

    def test_failed_target_keeps_issue_in_current_state(self) -> None:
        yaml_str = """\
issue:
  fields:
    title:
      type: string
      description: t

states:
  work:
    worker:
      kind: claude-code
      prompt: p.md
      result_format:
        outcome:
          type: enum
          values: [ok, fail]
          description: d
    on:
      ok: done
      fail: failed

initial: work
"""
        config = parse_config(yaml_str)
        state = State(issues={}, worker_queues={})
        state, _ = reduce(config, state, CreateEvent(issue_id="i1", fields={"title": "t"}, timestamp="t0"), _id, _now)

        # Worker returns fail
        state, effects = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="i1", result={"outcome": "fail", "reason": "broken"}, timestamp="t1"),
            _id,
            _now,
        )

        issue = state.issues["i1"]
        # Issue stays in 'work', NOT moved to 'failed' or 'done'
        assert issue.state == "work"
        assert issue.failure_count == 1
        assert issue.worker_active is False

    def test_failed_target_uses_reason_field(self) -> None:
        yaml_str = """\
issue:
  fields:
    title:
      type: string
      description: t

states:
  work:
    worker:
      kind: claude-code
      prompt: p.md
      result_format:
        outcome:
          type: enum
          values: [ok, fail]
          description: d
        reason:
          type: string
          description: Why it failed
          required_when: [fail]
    on:
      ok: done
      fail: failed

initial: work

max-retries: 5
"""
        config = parse_config(yaml_str)
        state = State(issues={}, worker_queues={})
        state, _ = reduce(config, state, CreateEvent(issue_id="i1", fields={"title": "t"}, timestamp="t0"), _id, _now)

        state, effects = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="i1", result={"outcome": "fail", "reason": "MCP server down"}, timestamp="t1"),
            _id,
            _now,
        )

        # Should have emitted a re-dispatch (auto-retry)
        dispatch_effects = [e for e in effects if isinstance(e, DispatchWorkerEffect)]
        assert len(dispatch_effects) == 1

        # Check the worker_failed log entry contains the reason
        issue = state.issues["i1"]
        failed_logs = [e for e in issue.event_log if e.type == "worker_failed"]
        assert len(failed_logs) == 1
        assert "MCP server down" in failed_logs[0].data["error"]

    def test_failed_target_exhausts_retries(self) -> None:
        yaml_str = """\
issue:
  fields:
    title:
      type: string
      description: t

states:
  work:
    worker:
      kind: claude-code
      prompt: p.md
      result_format:
        outcome:
          type: enum
          values: [ok, fail]
          description: d
    on:
      ok: done
      fail: failed

initial: work

max-retries: 2
"""
        config = parse_config(yaml_str)
        state = State(issues={}, worker_queues={})
        state, _ = reduce(config, state, CreateEvent(issue_id="i1", fields={"title": "t"}, timestamp="t0"), _id, _now)

        # First failure — should auto-retry
        state, effects1 = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="i1", result={"outcome": "fail"}, timestamp="t1"),
            _id,
            _now,
        )
        assert any(isinstance(e, DispatchWorkerEffect) for e in effects1)

        # Second failure — retries exhausted
        state, effects2 = reduce(
            config,
            state,
            WorkerResultEvent(issue_id="i1", result={"outcome": "fail"}, timestamp="t2"),
            _id,
            _now,
        )
        assert not any(isinstance(e, DispatchWorkerEffect) for e in effects2)
        assert state.issues["i1"].failure_count == 2
        assert state.issues["i1"].worker_active is False
```

Make sure the test file has these imports at the top (some may already exist):

```python
from orca.engine.config import parse_config
from orca.engine.types import (
    CreateEvent,
    DispatchWorkerEffect,
    State,
    WorkerResultEvent,
)
from orca.engine.reducer import reduce
```

And helper fixtures/functions (`_id` and `_now`) — check the file for existing ones. Typically:

```python
_id = lambda: "gen-id"
_now = lambda: "2026-01-01T00:00:00Z"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/engine/test_reducer_worker_result.py::TestFailedBuiltinTarget -v`
Expected: FAIL

- [ ] **Step 3: Update `_handle_worker_result` in reducer.py**

In the `_handle_worker_result` function, after the rule is resolved from `state_def.on[outcome]` (around line 236), and **before** the existing decompose validation and mutation blocks, add handling for the `failed` target:

After line 236 (`rule = state_def.on[outcome]`), add:

```python
    # Built-in 'failed' target: treat as worker failure, not a state transition
    if isinstance(rule, OnTransition) and rule.target == "failed":
        reason = str(event.result.get("reason", "Worker returned failure outcome"))
        # Re-use the existing worker-failed machinery
        issue.worker_active = False
        issue.failure_count += 1
        append_log(issue, event.timestamp, "worker_result", event.result)
        append_log(issue, ts, "worker_failed", {"state": issue.state, "error": reason})

        # Store failure context if the type defines it
        issue_fields = config.get_type(issue.type).fields
        if "failure_context" in issue_fields:
            issue.fields["failure_context"] = reason

        # Slot backfill
        if state_def.max_workers is not None:
            backfill_queue(config, state, f"{issue.type}:{issue.state}", effects)

        # Check retry limit
        if config.max_worker_retries is not None and issue.failure_count >= config.max_worker_retries:
            append_log(
                issue,
                ts,
                "worker_retries_exhausted",
                {"state": issue.state, "failure_count": issue.failure_count},
            )
            effects.append(
                ErrorEffect(
                    issue_id=event.issue_id,
                    message=f"Issue '{event.issue_id}' failed {issue.failure_count} times in state "
                    f"'{issue.state}' — retries exhausted",
                )
            )
            return

        # Retry — re-dispatch
        append_log(issue, ts, "worker_dispatched", {"state": issue.state})
        effects.append(
            DispatchWorkerEffect(
                issue_id=event.issue_id,
                issue_type=issue.type,
                state=issue.state,
                result_format=build_result_format(config, issue.type, issue.state),
                issue=build_issue_context(state, event.issue_id),
                progress_enabled=state_def.worker.progress if state_def.worker else False,
            )
        )
        return
```

- [ ] **Step 4: Replace `state_def.terminal` checks in reducer.py**

There are 4 locations in `reducer.py` that check `.terminal`:

1. **Line 114** in `_handle_advance`: `if current_state_def.worker is not None or current_state_def.terminal:` → change to `if current_state_def.worker is not None or issue.state == "done":` 

2. **Line 193** in `_handle_worker_result`: `if state_def.terminal:` → change to `if issue.state == "done":`

3. **Line 373** in `_handle_feedback_received`: `if state_def.terminal:` → change to `if issue.state == "done":`

4. **Line 494** in `_apply_transition`: `if target_def.terminal:` → change to `if target_state == "done":`

5. **Lines 636-637** in `_cascading_unblock`: `config.get_state(...).terminal` → change to `state.issues[cid].state == "done"`:

```python
        all_terminal = all(state.issues[cid].state == "done" for cid in children)
```

6. **Lines 660-661** in `_cascading_unblock`: same pattern for dependency check:

```python
            all_deps_terminal = all(state.issues[dep_id].state == "done" for dep_id in iss.depends_on)
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/engine/test_reducer_worker_result.py -v`
Expected: PASS

Run: `uv run pytest tests/engine/ -v`
Expected: PASS (all engine tests, verifying nothing else broke)

- [ ] **Step 6: Commit**

```bash
git add src/orca/engine/reducer.py tests/engine/test_reducer_worker_result.py
git commit -m "feat(engine): handle failed target as worker failure in reducer"
```

---

### Task 4: Update dispatch.py — replace `terminal` checks

**Files:**
- Modify: `src/orca/engine/dispatch.py:24-44`

- [ ] **Step 1: Update `is_blocked` in dispatch.py**

Replace the two `.terminal` checks (lines 34 and 41):

```python
def is_blocked(state: State, config: StateMachineConfig, issue_id: str) -> bool:
    """Returns True if the issue is decomposition-blocked or dependency-blocked."""
    issue = state.issues[issue_id]

    # Decomposition-blocked: has children not all done
    children = get_children(state, issue_id)
    if children:
        for child_id in children:
            child = state.issues[child_id]
            if child.state != "done":
                return True

    # Dependency-blocked: has depends_on entries not all done
    for dep_id in issue.depends_on:
        dep = state.issues[dep_id]
        if dep.state != "done":
            return True

    return False
```

This removes the `config` parameter dependency for these checks, but keep the `config` parameter in the signature since `is_blocked` is called from many places and `config` is still used indirectly via `try_dispatch`.

- [ ] **Step 2: Run engine tests**

Run: `uv run pytest tests/engine/ -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add src/orca/engine/dispatch.py
git commit -m "refactor(engine): replace terminal checks with state=='done' in dispatch"
```

---

### Task 5: Update formatting.py — replace `terminal` checks

**Files:**
- Modify: `src/orca/engine/formatting.py:58,115`

- [ ] **Step 1: Update `_render_issue` and root rendering**

In `_render_issue` (line 58): replace `is_terminal = state_def.terminal` with `is_terminal = issue.state == "done"`. Remove the `state_def` variable since it's only used for `terminal`:

```python
    issue = state.issues[issue_id]
    is_terminal = issue.state == "done"
```

In the root rendering block (line 115): same replacement:

```python
            issue = state.issues[root_id]
            is_terminal = issue.state == "done"
```

Remove the `state_def = config.get_state(...)` calls at lines 57 and 114 since they were only used for the terminal check.

- [ ] **Step 2: Run formatting tests**

Run: `uv run pytest tests/engine/test_formatting.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add src/orca/engine/formatting.py
git commit -m "refactor(engine): replace terminal checks in formatting"
```

---

### Task 6: Update orchestrator.py and runner.py — replace `terminal` checks

**Files:**
- Modify: `src/orca/orchestrator/orchestrator.py:179-190`
- Modify: `src/orca/orchestrator/runner.py:79-85,217,352,557`

- [ ] **Step 1: Update `_is_terminal` in orchestrator.py**

Replace the method at line 179:

```python
    def _is_terminal(self, issue_id: str) -> bool:
        """Return True if the issue's current state is 'done' (built-in terminal)."""
        issue = self._state.issues.get(issue_id)
        if issue is None:
            return False
        return issue.state == "done"
```

- [ ] **Step 2: Update `_is_terminal` in runner.py**

Replace the function at line 79:

```python
def _is_terminal(issue: Issue, config: StateMachineConfig) -> bool:
    """Check if an issue is in a terminal state."""
    return issue.state == "done"
```

Note: keep the `config` parameter for API compatibility even though it's no longer used — callers pass it.

- [ ] **Step 3: Update remaining `terminal` checks in runner.py**

Line 217 (`if state_def is None or state_def.terminal:`):
```python
        if issue.state == "done":
            continue
```
Remove the `state_def` lookup above it (line 216-217 become just the `done` check).

Line 352 (`if type_def and issue.state in type_def.states and type_def.states[issue.state].terminal:`):
```python
            if issue.state == "done":
```

Line 556-557 (terminal count):
```python
        terminal = sum(
            1 for iss in prev_state.issues.values() if iss.state == "done"
        )
```

- [ ] **Step 4: Run orchestrator/runner tests**

Run: `uv run pytest tests/ -v -k "not test_integration"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/orca/orchestrator/orchestrator.py src/orca/orchestrator/runner.py
git commit -m "refactor(orchestrator): replace terminal checks with state=='done'"
```

---

### Task 7: Update daemon manager.py — replace `terminal` checks

**Files:**
- Modify: `src/orca/daemon/manager.py` (lines 71, 166, 405, 600-607)

- [ ] **Step 1: Update all `terminal` checks**

Line 71 (`if state_def is not None and state_def.terminal:`):
```python
                    if issue.state == "done":
```
Remove the `state_def` lookup above it.

Line 166 (`if type_def and issue.state in type_def.states and type_def.states[issue.state].terminal:`):
```python
                if issue.state == "done":
```

Line 405 (same pattern):
```python
            if issue.state == "done":
```

Lines 600-608 (`scan_interrupted_runs` all-terminal check):
```python
                all_terminal = all(issue.state == "done" for issue in state.issues.values())
```

Remove the `type_def` / `state_def` lookups that were only used for terminal checks.

- [ ] **Step 2: Run daemon tests**

Run: `uv run pytest tests/daemon/ -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add src/orca/daemon/manager.py
git commit -m "refactor(daemon): replace terminal checks with state=='done'"
```

---

### Task 8: Update TUI — replace `terminal` checks, make retry visible

**Files:**
- Modify: `src/orca/tui/app.py` (lines 412, 425-440)
- Modify: `src/orca/tui/widgets/header.py` (lines 105-113, 125)
- Modify: `src/orca/tui/widgets/issue_tree.py` (lines 62, 82)

- [ ] **Step 1: Update `app.py`**

Line 412 (`if root.state in type_states and type_states[root.state].terminal:`):
```python
                if root.state == "done":
```

Make the retry keybinding visible — find the `Binding` for `n` and change `show=False` to `show=True`.

- [ ] **Step 2: Update `header.py`**

`_all_terminal` method (line 105-113):
```python
    def _all_terminal(self) -> bool:
        """Check if all issues are in the done state."""
        if self._state is None or self._config is None:
            return False
        return all(issue.state == "done" for issue in self._state.issues.values())
```

`_step_text` method (line 125):
```python
        non_terminal_states = list(self._config.root_type_def.states.keys())
```
(All user-defined states are non-terminal since `done`/`failed` aren't in the states dict.)

- [ ] **Step 3: Update `issue_tree.py`**

Line 62 (`not sdef.terminal`):
```python
    non_terminal = list(config.root_type_def.states.keys())
```

Line 82 (`not sdef.terminal`):
```python
        name for name in config.root_type_def.states if name not in visit_counts
```

- [ ] **Step 4: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: PASS

- [ ] **Step 5: Run linting and type checking**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy src/`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add src/orca/tui/app.py src/orca/tui/widgets/header.py src/orca/tui/widgets/issue_tree.py
git commit -m "refactor(tui): replace terminal checks, make retry keybinding visible"
```

---

### Task 9: Migrate sme-web workflow YAMLs

**Files:**
- Modify: `/Users/agutnikov/work/projects/sme-web/sme-web/orca.prd.yml`
- Modify: `/Users/agutnikov/work/projects/sme-web/sme-web/orca.qa-specs.yml`
- Modify: `/Users/agutnikov/work/projects/sme-web/sme-web/orca.e2e.yml`

- [ ] **Step 1: Update each workflow YAML**

For each file:
1. Remove the `done: terminal: true` state definition
2. Change `fail: done` to `fail: failed` where the failure should be retryable (e.g., `recon_prd`, `generate_prd`)
3. Keep graceful degradation transitions unchanged (e.g., `field_observer: fail: recon_prd`)

For `orca.prd.yml` specifically, based on the current config:
- `generate_prd: on: fail: done` → `fail: failed` (retryable)
- `recon_prd: on: fail: done` → `fail: failed` (retryable)
- Remove `done: terminal: true` block
- Keep `field_observer: on: fail: recon_prd` (graceful degradation, unchanged)
- Keep `territory_map: on: fail: build_and_run` (graceful degradation, unchanged)

- [ ] **Step 2: Verify configs parse**

Run from the orca project:
```bash
uv run python -c "
from pathlib import Path
from orca.engine.config import parse_config
for f in ['orca.prd.yml', 'orca.qa-specs.yml', 'orca.e2e.yml']:
    p = Path('/Users/agutnikov/work/projects/sme-web/sme-web') / f
    if p.exists():
        parse_config(p.read_text())
        print(f'{f}: OK')
"
```
Expected: All parse successfully

- [ ] **Step 3: Commit** (in the sme-web repo)

```bash
cd /Users/agutnikov/work/projects/sme-web/sme-web
git add orca.prd.yml orca.qa-specs.yml orca.e2e.yml
git commit -m "chore: migrate orca workflows to built-in done/failed states"
```
