# Engine Improvements Design

Three improvements to the state machine engine: event log, hop limits, and ASCII visualization.

## 1. Event Log (replaces result_history)

### Goal

Replace `result_history` with a comprehensive `event_log` that records everything that happens to an issue. One log, one source of truth.

### Changes to Issue State

Remove `result_history: list[ResultHistoryEntry]`. Add `event_log: list[EventLogEntry]`.

```python
@dataclass
class EventLogEntry:
    timestamp: str  # ISO 8601
    type: str
    data: dict[str, Any]
```

### Changes to Reducer Signature

```python
def reduce(
    config: StateMachineConfig,
    state: State,
    event: Event,
    generate_id: Callable[[], str],
    now: Callable[[], str],  # returns ISO timestamp
) -> tuple[State, list[Effect]]
```

`now()` is called **once** at the start of each `reduce()` invocation. The resulting timestamp is reused for all log entries within that call. This gives snapshot semantics — all entries from a single reduce call share a timestamp. In tests, use a deterministic clock.

### Event Types Added to Events

All event dataclasses get a `timestamp: str` field:

```python
@dataclass(frozen=True)
class CreateEvent:
    issue_id: str
    fields: dict[str, Any]
    timestamp: str

@dataclass(frozen=True)
class AdvanceEvent:
    issue_id: str
    target_state: str
    timestamp: str

@dataclass(frozen=True)
class WorkerResultEvent:
    issue_id: str
    result: dict[str, Any]
    timestamp: str

@dataclass(frozen=True)
class WorkerFailedEvent:
    issue_id: str
    error: str
    timestamp: str
```

### Log Entries

The reducer appends entries to `event_log` at these points:

| When | type | data |
|------|------|------|
| Issue created (Create event or decompose sub-issue creation) | `created` | `{}` |
| Advance event | `advanced` | `{"from": "<state>", "to": "<state>"}` |
| Worker dispatched (DispatchWorker emitted) | `worker_dispatched` | `{"state": "<state>"}` |
| WorkerResult received | `worker_result` | `{"state": "<state>", "result": {<full result>}}` |
| WorkerFailed received | `worker_failed` | `{"state": "<state>", "error": "<msg>"}` |
| State transition (from WorkerResult routing) | `transitioned` | `{"from": "<state>", "to": "<state>"}` |
| Decomposition block | `decomposition_blocked` | `{"children": ["<id>", ...]}` |
| Dependency block | `dependency_blocked` | `{"depends_on": ["<id>", ...]}` |
| Unblocked | `unblocked` | `{"reason": "decomposition" or "dependency"}` |

**Timestamp sources:** log entries use the event's `timestamp` field when available. For reducer-initiated entries (e.g., `worker_dispatched`, `transitioned`, sub-issue `created`), use the `now()` snapshot captured at the start of the `reduce()` call.

**Sub-issue creation:** when the reducer creates sub-issues via `action: decompose`, each child gets a `created` log entry. This ensures `format_issues` can compute elapsed time for all issues, not just externally created ones.

**WorkerFailed flow:** the handler appends a `worker_failed` log entry, then emits the retry `DispatchWorkerEffect` which also appends a `worker_dispatched` entry. Both appear in the log.

**Advance vs transitioned:** an `Advance` event produces only an `advanced` entry (not `transitioned`). The `transitioned` entry is reserved for transitions caused by `WorkerResult` routing. This makes the log unambiguous about what triggered each state change.

### DispatchWorkerEffect

The `issue` context includes `event_log` instead of `result_history`. Workers that need prior results filter for `type == "worker_result"` entries.

### Serialization

`EventLogEntry` follows the same `to_dict()`/`from_dict()` pattern. The `ResultHistoryEntry` class is removed.

---

## 2. Hop Limits

### Goal

Prevent issues from looping infinitely between states. Two mechanisms: per-state `max_visits` and global `max_hops`.

### Changes to Issue State

Add two fields:

- `visit_counts: dict[str, int]` — how many times the issue has entered each state
- `hop_count: int` — total number of transitions

### Changes to orca.yml Config

Optional `max_visits` on state definitions:

```yaml
implementing:
  max_visits: 5
  worker: ...
```

Optional `max_hops` at top level:

```yaml
max_hops: 50

states:
  ...
```

### Changes to StateMachineConfig

Add `max_hops: int | None = None` to `StateMachineConfig`.
Add `max_visits: int | None = None` to `StateDef`.

### Counting Rules

| Event | hop_count | visit_counts |
|-------|-----------|-------------|
| Create (initial placement) | unchanged | +1 for initial state |
| Advance | +1 | +1 for target state |
| WorkerResult → simple transition | +1 | +1 for target state |
| WorkerResult → decompose | +1 | unchanged (stays in same state, but the decompose-unblock-re-run cycle counts as a hop) |
| Unblock re-dispatch | unchanged | unchanged (already in the state) |

**Why decompose increments hop_count:** without this, a worker that decomposes with a single child that immediately completes could loop infinitely: decompose → child done → parent unblocked → re-run → decompose again. The global `max_hops` safety net catches this.

### Limit Check

Before applying a transition (in WorkerResult or Advance), the reducer checks:

1. If target state has `max_visits` and `visit_counts[target] + 1 > max_visits` → emit `Error` effect, do not transition
2. If config has `max_hops` and `hop_count + 1 > max_hops` → emit `Error` effect, do not transition

For decompose, the `max_hops` check is performed before creating sub-issues.

On limit hit:
- Issue stays in current state
- `worker_active` set to `false` (slot freed)
- Slot backfill triggered for the current state if it has `max_workers`
- `Error` effect emitted with descriptive message
- Log entry added: `{"type": "limit_reached", "data": {"limit": "max_visits" or "max_hops", "state": "...", "count": N}}`

**Dead end:** an issue that hits a limit is parked — no mechanism will move it automatically. This is intentional. The orchestrator must handle it (alert an operator, move to an error state, etc.). A future `ResetLimits` event could be added if automated recovery is needed.

### Implementation Note: Effect Type Widening

The current `_apply_transition` and dispatch helpers accept `list[DispatchWorkerEffect]`. With hop limits, they need to emit `ErrorEffect` as well. The effects parameter in these internal functions must be widened to `list[Effect]` (the union type). This is a refactor of internal function signatures, not a public API change.

### Validation

- `max_visits` if present must be a positive integer
- `max_hops` if present must be a positive integer

### Issue State Initialization

On `Create`: `hop_count = 0`, `visit_counts = {config.initial: 1}`.

On deserialization of existing state without these fields: default to `hop_count = 0`, `visit_counts = {}`.

---

## 3. ASCII Visualization

### Goal

Utility function to display the current state of all issues as a formatted ASCII string.

### Function

```python
def format_issues(state: State, config: StateMachineConfig, now: str) -> str
```

Located in `src/orca/engine/formatting.py`.

### Output Format

```
ISSUE-1 [scoping] ... 2h 15m
├── ISSUE-4 [done] 20m
├── ISSUE-2 [done] 45m
└── ISSUE-3 [implementing] ... 1h 30m
    └── depends on: ISSUE-4

Queued in 'apply': ISSUE-5, ISSUE-6
```

### Rules

- Root issues (no `decomposed_from`) are top-level entries
- Children indented under their decomposition parent with `├──` / `└──` connectors
- Sort order: roots and children sorted by issue ID (lexicographic). Deterministic across serialization round-trips.
- `depends_on` shown as annotation line under the dependent issue, indented with same tree connector style
- Non-terminal states show `...` after the state name
- Terminal states show just the elapsed time, no marker
- Elapsed time computed from the `created` entry in `event_log` to the `now` parameter, formatted as `Xd Yh Zm` (dropping zero leading units, minimum shows `0m`)
- Worker queues listed at the bottom: `Queued in '<state>': ID-1, ID-2` — shows contents of `worker_queues[state]` for each non-empty queue
- Issues without a `created` event in their log show `?` for elapsed time

### No Config Changes

Read-only utility on existing state. No changes to the reducer or config.

---

## Migration

This is a breaking change to the reducer signature, state format, and worker-facing API.

### State format changes

- `result_history` field removed from `Issue`, replaced with `event_log`
- `ResultHistoryEntry` class removed, replaced with `EventLogEntry`
- New fields added to `Issue`: `visit_counts: dict[str, int]`, `hop_count: int`
- `Issue.from_dict()` must handle missing `visit_counts`/`hop_count` with defaults (`{}` and `0`)

### Reducer signature change

- `reduce(config, state, event, gen)` → `reduce(config, state, event, gen, now)`

### Event changes

- All event dataclasses gain a `timestamp: str` field

### Worker-facing API change

- `DispatchWorkerEffect.issue` context includes `event_log` instead of `result_history`
- Workers that previously read `result_history` must be updated to filter `event_log` for `type == "worker_result"` entries

### Config changes

- `StateMachineConfig` gains `max_hops: int | None`
- `StateDef` gains `max_visits: int | None`
- `parse_config` updated to parse these fields
- Validation rules added for positive integer checks

### Test updates

- All `result_history=[]` → `event_log=[]`
- All `ResultHistoryEntry(...)` → removed
- All `reduce(config, state, event, gen)` → `reduce(config, state, event, gen, now)`
- All event constructors need `timestamp` argument
- Tests asserting on `result_history` → assert on `event_log` entries filtered by type
- New fields `visit_counts={}` and `hop_count=0` added to `Issue` constructors in tests

### Original spec update

The original engine spec (`docs/superpowers/specs/2026-03-22-state-machine-engine-design.md`) must be updated to reflect all changes. This should be done as part of the implementation, not as a separate task.

## Future Considerations

- Event log compaction — for long-running issues, the log could grow large. A future improvement could archive old entries.
- Event log querying — helper functions like `get_worker_results(event_log)` for common filters.
- `ResetLimits` event — for automated recovery of issues that hit hop/visit limits.
- Cross-group dependencies in `format_issues` — if non-sibling `depends_on` is added later, the display may need adjustment.
