# Built-in `done` and `failed` States

## Problem

The engine currently uses `terminal: true` on user-defined states to mark issue completion. This creates two problems:

1. **No distinction between success and failure exits.** A workflow routes both success (`complete: done`) and failure (`fail: done`) to the same terminal state. Once there, the engine can't tell them apart. The TUI retry logic checks `failure_count > 0`, but a worker that returns `outcome: fail` (a graceful failure result) doesn't increment `failure_count` — that only happens on worker crashes. So the TUI refuses to retry issues that failed via a result outcome.

2. **Boilerplate.** Every workflow must define `done: { terminal: true }`. This is mechanical — there's nothing to configure on a terminal state.

## Design

Replace `terminal: true` with two built-in reserved states: `done` and `failed`.

### `done` — success terminal

- Built-in. Never defined in `states:` block.
- The only terminal state. An issue in `done` is finished.
- Transitions targeting `done` work as today: issue moves to `done`, no worker dispatch.
- `_is_terminal` checks become `issue.state == "done"`.

### `failed` — worker failure signal

- Built-in. Never defined in `states:` block.
- Not a real state the issue transitions to. It's a signal to the engine.
- When a transition targets `failed`, the engine treats it as a worker failure:
  - Issue stays in its current state (e.g., `recon_prd`)
  - `failure_count` increments
  - Auto-retry logic (`max_worker_retries`) kicks in naturally
  - If retries exhausted, issue sits in current state with `worker_active: false`
- The worker's `reason` field from the result becomes the error message on the `WorkerFailedEvent`.

### Workflow YAML

Before:
```yaml
states:
  recon_prd:
    worker:
      kind: claude-code
      prompt: prompts/prd/recon.md
    on:
      complete: review_prd
      fail: done                 # lost — treated as success

  done:
    terminal: true               # boilerplate
```

After:
```yaml
states:
  recon_prd:
    worker:
      kind: claude-code
      prompt: prompts/prd/recon.md
    on:
      complete: review_prd
      fail: failed               # engine treats as worker crash
```

No `done:` block needed. Graceful degradation still works the same:
```yaml
field_observer:
  on:
    done: recon_prd
    fail: recon_prd              # skip and continue — unchanged
```

### Engine changes

#### Types (`engine/types.py`)

- Remove `terminal: bool` from `StateDef`.
- Add constant: `BUILTIN_STATES = frozenset({"done", "failed"})`.

#### Config parsing (`engine/config.py`)

- Error if `done` or `failed` appears in `states:` block.
- Remove `terminal` field parsing from state definitions.
- Validation: all transition targets must be a defined state, `done`, or `failed`.
- Remove validation that checks for at least one terminal state — `done` is always available.
- `get_state()` for `done`: return a synthetic `StateDef` with no worker, no transitions, acting as a sentinel. This avoids `None` checks at every call site (there are 15+ across the codebase). The synthetic def has `worker=None`, `on={}`.
- `failed` is never stored as `issue.state`, so `get_state("failed")` should never be called — raise if it is.

#### Reducer (`engine/reducer.py`)

In the transition logic (when processing `OnTransition` with a target):

- **Target is `done`:** Transition the issue to `done`. No worker dispatch. Proceed with parent/dependency propagation as today (checking `issue.state == "done"` instead of `state_def.terminal`).
- **Target is `failed`:** Do not transition. Emit a `WorkerFailedEvent` with the result's `reason` field (or a default message like `"Worker returned failure outcome"`). The existing failure/retry machinery handles the rest.
- **Target is a regular state:** Unchanged.

Replace all `state_def.terminal` checks with `issue.state == "done"`.

#### Dispatch (`engine/dispatch.py`)

- Replace `state_def.terminal` checks with `issue.state == "done"`.
- Children/dependency "all terminal" checks become "all in `done` state".

#### Formatting (`engine/formatting.py`)

- Replace `state_def.terminal` with `issue.state == "done"`.

### Orchestrator changes

#### `orchestrator.py`

- `_is_terminal()` becomes `self.state.issues[issue_id].state == "done"`.

#### `runner.py`

- `_is_terminal()` becomes `issue.state == "done"`.
- All `state_def.terminal` references updated.

### Daemon changes

#### `manager.py`

- All `state_def.terminal` checks become `issue.state == "done"`.

### TUI changes

#### `app.py`

- `action_retry_failed` validation: `failure_count > 0` check now works correctly because `failed` transitions increment `failure_count`.
- Make the retry keybinding visible: `show=True`.

#### `widgets/header.py`

- `_all_terminal()` checks `issue.state == "done"` instead of `state_def.terminal`.
- Step count: non-terminal states = all defined states (since `done`/`failed` aren't in the states dict).

#### `widgets/issue_tree.py`

- Progress bar and state display: use `issue.state == "done"` for terminal checks.
- Failed issues (those with `failure_count > 0` sitting in a non-done state) get red indicator.

### Migration

Existing workflows:
1. Remove `done: { terminal: true }` state definition.
2. Change `fail: done` to `fail: failed` where the failure should be retryable.
3. Keep `fail: <next_state>` for graceful degradation (skip and continue).
4. Keep `success_outcome: done` for success exits.

### What stays the same

- `failure_count`, `max_worker_retries`, auto-retry loop — untouched.
- Worker protocol (result.json format) — unchanged.
- TUI retry keybinding (`n`) and daemon retry API — unchanged, just work correctly now.
- `WorkerFailedEvent` type — unchanged, just emitted in a new place.
