# Worker Blocking / Unblocking

Workers can signal that they are waiting by writing `{"outcome": "waiting"}` to `result.json`. The orchestrator keeps the tmux session alive, pauses the inactivity timer, and waits for an explicit unblock command that pushes a message into the session.

## Motivation

Today, once a worker writes `result.json` the session is killed after a 30-second grace period. There is no way for a worker to say "I'm stuck and need external input" while preserving its conversation context. Killing and restarting loses the full session history. This feature lets workers pause and resume in-place.

## Design Decisions

- **Keep session alive** (not kill-and-restart): preserves the worker's full conversation context.
- **`waiting` is a built-in outcome** like `done` and `failed`: available to any worker without opt-in from the workflow author.
- **Approach 3 (thin engine awareness)**: engine records waiting/resumed events for audit logging; all lifecycle management lives in the orchestrator.
- **Signal via result.json**: reuses the existing communication channel. No MCP dependency from worker to orca.
- **Unblock message is required**: the caller must provide context about what changed. No generic fallback.
- **No blocked timeout**: waits forever. Operator must explicitly unblock or stop the run.
- **Multiple cycles**: a worker can block and unblock repeatedly in a single session.

## Engine Changes

### New Event Types

In `engine/types.py`:

```python
@dataclass(frozen=True)
class WorkerWaitingEvent:
    issue_id: str
    timestamp: str

@dataclass(frozen=True)
class WorkerResumedEvent:
    issue_id: str
    message: str
    timestamp: str
```

The `Event` union adds both types:

```python
Event = CreateEvent | AdvanceEvent | WorkerResultEvent | WorkerFailedEvent | WorkerWaitingEvent | WorkerResumedEvent
```

### Reducer Handlers

In `engine/reducer.py`:

**`_handle_worker_waiting`**: validates issue exists, `worker_active == True`, not terminal. Appends `event_log` entry `{"type": "worker_waiting"}`. Returns unchanged state, no effects.

**`_handle_worker_resumed`**: same validation. Appends `event_log` entry `{"type": "worker_resumed", "data": {"message": ...}}`. Returns unchanged state, no effects.

Error cases (produce `ErrorEffect`): non-existent issue, `worker_active=False`, terminal state.

No new fields on `Issue`. `worker_active` stays `True` throughout the blocked cycle.

### Built-in Outcome Interception

`waiting` is intercepted by the orchestrator *before* validation against `state_def.on`. Workflow authors do not declare it in `result_format.outcome.values`. The orchestrator checks for `outcome == "waiting"` right after parsing `result.json`, before checking if the outcome is in the state's valid outcomes.

## Orchestrator Changes

### Polling Loop (`worker.py`)

New behavior in `CliAgentWorker.execute()` polling loop:

1. After parsing `result.json` as valid JSON, check `outcome == "waiting"` **before** calling `validate_result()`. If waiting:
   - Delete `result.json` (so the worker can write a new one after unblocking)
   - Stop incrementing `elapsed` (pause inactivity timer)
   - Enter a **blocked polling sub-loop**

2. Blocked sub-loop checks:
   - `pty_session.alive` — if session dies while blocked, return `WorkerFailure`
   - `unblock_event.is_set()` — if set, push message via `pty_session.send_keys()`, clear event, delete `result.json`, resume normal polling with timer

3. After unblock, normal polling resumes. If the worker writes `waiting` again, the same logic repeats.

The worker receives an `asyncio.Event` and a `list[str]` message container:
- `unblock_event: asyncio.Event` — set by the orchestrator when unblock is called
- `unblock_message: list[str]` — single-element list used as a message box

### Orchestrator Registry (`orchestrator.py`)

New field:

```python
_waiting_workers: dict[str, tuple[asyncio.Event, list[str]]]
```

Maps `issue_id` to its unblock event and message container. Populated when the polling loop detects `waiting`, removed when the worker finishes.

New method:

```python
def unblock_worker(self, issue_id: str, message: str) -> bool:
    """Unblock a waiting worker. Returns False if issue not waiting."""
    entry = self._waiting_workers.get(issue_id)
    if entry is None:
        return False
    event, msg_box = entry
    msg_box.clear()
    msg_box.append(message)
    event.set()
    return True
```

### Event Emission

When the orchestrator detects `waiting`, it emits `WorkerWaitingEvent` to the reducer. When unblock fires, it emits `WorkerResumedEvent`. Both are for logging only — the reducer returns unchanged state.

## MCP, HTTP API, and CLI

### MCP Tool (`daemon/mcp_tools.py`)

```python
async def orca_unblock_worker(root: str, run_id: str, issue_id: str, message: str) -> str:
    """Unblock a waiting worker by sending it a message.

    Args:
        root: Absolute path to the target project's repo root.
        run_id: The run identifier.
        issue_id: The issue identifier of the waiting worker.
        message: Message to send to the worker explaining what changed.
    """
```

### HTTP API Route (`daemon/http_api.py`)

```
POST /api/runs/{run_id}/unblock/{issue_id}
Body: {"message": "PR #42 merged, you can continue"}
```

Returns `{"status": "ok"}` or `{"error": "issue is not waiting"}` (400).

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

**Stop while waiting**: `stop_run` cancels all in-flight tasks including waiting ones. Tmux session is killed. On `resume_run`, the issue re-dispatches as a fresh worker. Waiting state is lost. Matches current stop/resume semantics.

**Worker dies while waiting**: Waiting sub-loop checks `pty_session.alive`. If dead, return `WorkerFailure`. Normal retry semantics apply.

**Unblock called for non-waiting worker**: `unblock_worker()` returns `False`, HTTP returns 400.

**Unblock called for wrong run/issue**: Manager/HTTP layer returns 404.

**Worker writes `waiting` but session already exited**: Polling loop checks session liveness before entering waiting state. If session is dead and result says `waiting`, treat as `WorkerFailure`.

**`waiting` not in result_format validation**: Intercepted before validation. Workflow authors don't declare it.

**Result.json schema for waiting**: Minimal — `{"outcome": "waiting"}`. No additional fields required. Workers can optionally include a `"reason"` for logging but it is not validated.

## Testing Strategy

**Engine tests** (unit, pure):
- `WorkerWaitingEvent` handler: validates preconditions, appends log entry, returns unchanged state + no effects.
- `WorkerResumedEvent` handler: same validation, appends log entry with message.
- Error cases: non-existent issue, `worker_active=False`, terminal state.

**Worker polling tests** (unit, with mock `PtySession`):
- Worker writes `{"outcome": "waiting"}` — loop pauses timer, deletes `result.json`, enters waiting sub-loop.
- Unblock event fires — `send_keys` called with message, `result.json` deleted, normal polling resumes.
- Multiple block/unblock cycles in one session.
- Session dies while waiting — `WorkerFailure`.
- Elapsed time during waiting period does not count toward inactivity timeout.

**Orchestrator integration tests**:
- `unblock_worker()` on waiting issue returns `True`, worker receives message.
- `unblock_worker()` on non-waiting issue returns `False`.
- Stop while waiting kills session cleanly.

**MCP/HTTP/CLI**: thin wrappers over the manager, tested at the HTTP layer with a mock manager.
