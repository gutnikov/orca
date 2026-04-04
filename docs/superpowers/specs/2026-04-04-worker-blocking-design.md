# Worker Blocking / Unblocking

Workers can signal that they are blocked by writing `{"outcome": "blocked"}` to `result.json`. The orchestrator keeps the tmux session alive, pauses the inactivity timer, and waits for an explicit unblock command that pushes a message into the session.

## Motivation

Today, once a worker writes `result.json` the session is killed after a 30-second grace period. There is no way for a worker to say "I'm stuck and need external input" while preserving its conversation context. Killing and restarting loses the full session history. This feature lets workers pause and resume in-place.

## Design Decisions

- **Keep session alive** (not kill-and-restart): preserves the worker's full conversation context.
- **`blocked` is a built-in outcome** like `done` and `failed`: available to any worker without opt-in from the workflow author.
- **Approach 3 (thin engine awareness)**: engine records blocked/unblocked events for audit logging; all lifecycle management lives in the orchestrator.
- **Signal via result.json**: reuses the existing communication channel. No MCP dependency from worker to orca.
- **Unblock message is required**: the caller must provide context about what changed. No generic fallback.
- **No blocked timeout**: waits forever. Operator must explicitly unblock or stop the run.
- **Multiple cycles**: a worker can block and unblock repeatedly in a single session.

## Engine Changes

### New Event Types

In `engine/types.py`:

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

The `Event` union adds both types:

```python
Event = CreateEvent | AdvanceEvent | WorkerResultEvent | WorkerFailedEvent | WorkerBlockedEvent | WorkerUnblockedEvent
```

### Reducer Handlers

In `engine/reducer.py`:

**`_handle_worker_blocked`**: validates issue exists, `worker_active == True`, not terminal. Appends `event_log` entry `{"type": "worker_blocked"}`. Returns unchanged state, no effects.

**`_handle_worker_unblocked`**: same validation. Appends `event_log` entry `{"type": "worker_unblocked", "data": {"message": ...}}`. Returns unchanged state, no effects.

Error cases (produce `ErrorEffect`): non-existent issue, `worker_active=False`, terminal state.

No new fields on `Issue`. `worker_active` stays `True` throughout the blocked cycle.

### Built-in Outcome Interception

`blocked` is intercepted by the orchestrator *before* validation against `state_def.on`. Workflow authors do not declare it in `result_format.outcome.values`. The orchestrator checks for `outcome == "blocked"` right after parsing `result.json`, before checking if the outcome is in the state's valid outcomes.

## Orchestrator Changes

### Polling Loop (`worker.py`)

New behavior in `CliAgentWorker.execute()` polling loop:

1. After parsing `result.json` as valid JSON, check `outcome == "blocked"` **before** calling `validate_result()`. If blocked:
   - Delete `result.json` (so the worker can write a new one after unblocking)
   - Stop incrementing `elapsed` (pause inactivity timer)
   - Enter a **blocked polling sub-loop**

2. Blocked sub-loop checks:
   - `pty_session.alive` — if session dies while blocked, return `WorkerFailure`
   - `unblock_event.is_set()` — if set, push message via `pty_session.send_keys()`, clear event, delete `result.json`, resume normal polling with timer

3. After unblock, normal polling resumes. If the worker writes `blocked` again, the same logic repeats.

The worker receives an `asyncio.Event` and a `list[str]` message container:
- `unblock_event: asyncio.Event` — set by the orchestrator when unblock is called
- `unblock_message: list[str]` — single-element list used as a message box

### Orchestrator Registry (`orchestrator.py`)

New field:

```python
_blocked_workers: dict[str, tuple[asyncio.Event, list[str]]]
```

Maps `issue_id` to its unblock event and message container. Populated when the polling loop detects `blocked`, removed when the worker finishes.

New method:

```python
def unblock_worker(self, issue_id: str, message: str) -> bool:
    """Unblock a blocked worker. Returns False if issue not blocked."""
    entry = self._blocked_workers.get(issue_id)
    if entry is None:
        return False
    event, msg_box = entry
    msg_box.clear()
    msg_box.append(message)
    event.set()
    return True
```

### Event Emission

When the orchestrator detects `blocked`, it emits `WorkerBlockedEvent` to the reducer. When unblock fires, it emits `WorkerUnblockedEvent`. Both are for logging only — the reducer returns unchanged state.

## MCP, HTTP API, and CLI

### MCP Tool (`daemon/mcp_tools.py`)

```python
async def orca_unblock_worker(root: str, run_id: str, issue_id: str, message: str) -> str:
    """Unblock a blocked worker by sending it a message.

    Args:
        root: Absolute path to the target project's repo root.
        run_id: The run identifier.
        issue_id: The issue identifier of the blocked worker.
        message: Message to send to the worker explaining what changed.
    """
```

### HTTP API Route (`daemon/http_api.py`)

```
POST /api/runs/{run_id}/unblock/{issue_id}
Body: {"message": "PR #42 merged, you can continue"}
```

Returns `{"status": "ok"}` or `{"error": "issue is not blocked"}` (400).

### CLI Command

```
orca unblock <run_id> <issue_id> -m "message"
```

`-m` is required. CLI errors if omitted.

### Call Chain

```
CLI / MCP tool
  -> DaemonClient.unblock_worker(run_id, issue_id, message)
    -> HTTP POST /api/runs/{run_id}/unblock/{issue_id}
      -> RunManager.unblock_worker(run_id, issue_id, message)
        -> Orchestrator.unblock_worker(issue_id, message)
          -> sets asyncio.Event, stores message
```

New method on `DaemonClient` and `RunManager` to complete the chain.

## Edge Cases

**Stop while blocked**: `stop_run` cancels all in-flight tasks including blocked ones. Tmux session is killed. On `resume_run`, the issue re-dispatches as a fresh worker. Blocked state is lost. Matches current stop/resume semantics.

**Worker dies while blocked**: Blocked sub-loop checks `pty_session.alive`. If dead, return `WorkerFailure`. Normal retry semantics apply.

**Unblock called for non-blocked worker**: `unblock_worker()` returns `False`, HTTP returns 400.

**Unblock called for wrong run/issue**: Manager/HTTP layer returns 404.

**Worker writes `blocked` but session already exited**: Polling loop checks session liveness before entering blocked state. If session is dead and result says `blocked`, treat as `WorkerFailure`.

**`blocked` not in result_format validation**: Intercepted before validation. Workflow authors don't declare it.

**Result.json schema for blocked**: Minimal — `{"outcome": "blocked"}`. No additional fields required. Workers can optionally include a `"reason"` for logging but it is not validated.

## Testing Strategy

**Engine tests** (unit, pure):
- `WorkerBlockedEvent` handler: validates preconditions, appends log entry, returns unchanged state + no effects.
- `WorkerUnblockedEvent` handler: same validation, appends log entry with message.
- Error cases: non-existent issue, `worker_active=False`, terminal state.

**Worker polling tests** (unit, with mock `PtySession`):
- Worker writes `{"outcome": "blocked"}` — loop pauses timer, deletes `result.json`, enters blocked sub-loop.
- Unblock event fires — `send_keys` called with message, `result.json` deleted, normal polling resumes.
- Multiple block/unblock cycles in one session.
- Session dies while blocked — `WorkerFailure`.
- Elapsed time during blocked period does not count toward inactivity timeout.

**Orchestrator integration tests**:
- `unblock_worker()` on blocked issue returns `True`, worker receives message.
- `unblock_worker()` on non-blocked issue returns `False`.
- Stop while blocked kills session cleanly.

**MCP/HTTP/CLI**: thin wrappers over the manager, tested at the HTTP layer with a mock manager.
