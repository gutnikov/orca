# State Machine Engine Design

## Goal

A pure reducer function that drives issue lifecycle through a user-defined state machine. The state machine is configured via `orca.yml`. The reducer takes the current state and an event, returns the next state plus a list of side effects.

## Signature

```python
def reduce(
    config: StateMachineConfig,
    state: State,
    event: Event,
    generate_id: Callable[[], str],
) -> tuple[State, list[Effect]]
```

- `config` — parsed `orca.yml`, immutable
- `state` — full serializable system state (all issues + their relationships)
- `event` — something that happened
- `generate_id` — injected function for assigning IDs to sub-issues during decomposition. The one impurity in the interface; in tests, use a deterministic generator.
- Returns new state + effects for the orchestrator to execute

The reducer is **pure** — no I/O, no side effects. Effects are data objects the orchestrator interprets.

## orca.yml Format

### Top-Level Structure

```yaml
issue:
  fields:
    <field_name>:
      type: string
      description: "..."

initial: <state_name>

states:
  <state_name>:
    max_workers: <int>              # optional, default unlimited
    worker:
      result_format:
        outcome:
          type: enum
          values: [...]
          description: "..."
          values_description:
            <value>: "..."
        <extra_field>:
          type: string | list
          description: "..."
          required_when: <outcome_value>  # optional, supports single value or list
          items: $issue                   # for type: list referencing issue schema
    on:
      <outcome_value>: <target_state>           # simple transition
      <outcome_value>:                           # transition with directive
        action: decompose

  <terminal_state_name>:
    terminal: true
```

### Sections

#### `issue`

Defines the user-facing fields of an issue.

```yaml
issue:
  fields:
    title:
      type: string
      description: "Short title of the issue"
    text:
      type: string
      description: "Detailed description"
```

Supported field types: `string`. More types can be added later.

#### `initial`

The state an issue enters when created.

```yaml
initial: todo
```

Must reference a state defined in `states`.

#### `states`

Each state is one of:

- **Passive** — no `worker`, no `on`, no `terminal`. A waiting state (e.g., `todo`). Issues sit here until an `Advance` event moves them to a specified target state.
- **Active** — has `worker` and `on`. A worker processes the issue and the result determines the next transition.
- **Terminal** — has `terminal: true`. The issue lifecycle is complete.

##### Active State Fields

**`max_workers`** — optional integer. Limits how many issues can have workers dispatched concurrently in this state. When the limit is reached, additional issues entering this state are queued and dispatched as slots free up. Default: unlimited (omitted). The reducer tracks active worker counts per state; when emitting `DispatchWorker`, it checks capacity and queues excess issues instead.

**`worker`** — defines the interface for the worker that processes issues in this state.

**`worker.result_format`** — schema for the worker's output. Must contain an `outcome` field of type `enum`. The `on` routing rules bind to `outcome.values`. Additional fields provide context to downstream workers.

Field types in `result_format`:
- `enum` — one of a set of values. Has `values`, `description`, `values_description`.
- `string` — free text. Has `description`.
- `list` — a list of items. Has `description`, `items`. When `items: $issue`, each item follows the `issue.fields` schema.

Optional field modifiers:
- `required_when` — field is required when outcome matches. Supports a single value (`required_when: decompose`) or a list (`required_when: [decompose, split]`).

**`on`** — routing rules keyed by `outcome` values. Two forms:

Simple transition (string):
```yaml
on:
  ready: implementing
```

Directive transition (object):
```yaml
on:
  decompose:
    action: decompose
```

The `action: decompose` directive tells the reducer to:
1. Create sub-issues from the `sub_issues` field in the worker result
2. Mark the parent issue as `blocked`
3. Keep the parent in its current state
4. When all sub-issues reach a terminal state, the parent is automatically unblocked and the worker re-runs

Note: the decompose behavior is triggered by the `action: decompose` directive in the routing rule, **not** by the outcome value name. An outcome named `"split"` routing to `action: decompose` works identically.

### Validation Rules

At config load time, the orchestrator validates:

1. `initial` references an existing state
2. Every `on` target references an existing state
3. Every `on` key matches a value in `outcome.values`
4. Every active state has `outcome` of type `enum` in `result_format`
5. Terminal states have no `worker` or `on`
6. At least one terminal state exists
7. `action: decompose` requires a `sub_issues` field with `items: $issue` in `result_format`
8. Every non-initial, non-passive state is reachable (is a target of at least one `on` rule or is the `initial` state). Passive states are exempt as they are reached via `Advance` events.
9. `max_workers` if present must be a positive integer

## Reducer State

The full system state, fully serializable as JSON:

```json
{
  "issues": {
    "ISSUE-1": {
      "fields": {
        "title": "Build auth",
        "text": "Implement full auth system"
      },
      "state": "scoping",
      "blocked": true,
      "worker_active": false,
      "parent": null,
      "children": ["ISSUE-2", "ISSUE-3"],
      "result_history": [
        {
          "state": "scoping",
          "result": {
            "outcome": "decompose",
            "sub_issues": [...]
          }
        }
      ]
    },
    "ISSUE-2": {
      "fields": {
        "title": "Add login endpoint",
        "text": "..."
      },
      "state": "done",
      "blocked": false,
      "worker_active": false,
      "parent": "ISSUE-1",
      "children": [],
      "result_history": [
        {
          "state": "implementing",
          "result": {"outcome": "done", "summary": "Implemented login"}
        },
        {
          "state": "ready-for-test",
          "result": {"outcome": "passed", "report": "All tests pass"}
        }
      ]
    }
  },
  "worker_queues": {}
}
```

### Issue Fields

User-defined (from `issue.fields` in config):
- Stored under `fields` key
- Shape matches the `issue.fields` schema

System-managed:
- `state` — current state name in the machine
- `blocked` — `true` when waiting on sub-issues, `false` otherwise
- `worker_active` — `true` when a worker has been dispatched and hasn't returned yet, `false` otherwise
- `parent` — ID of the parent issue, or `null`
- `children` — list of child issue IDs
- `result_history` — ordered list of worker results. Each entry records the `state` and the worker's `result`. Appended on every `WorkerResult` event. Workers can use this to see prior outcomes (e.g., a scoping worker re-running after unblock can see its previous decompose result and the children's results via their own histories).

### Dispatch Protocol

All `DispatchWorker` emission goes through a single protocol. Every place in the spec that says "dispatch the issue" follows these rules:

1. Check if the issue's state has `max_workers` set
2. If yes, count issues in that state with `worker_active: true`
3. If count < `max_workers` (or `max_workers` is not set): set `worker_active: true` on the issue, emit `DispatchWorker` effect
4. If count >= `max_workers`: leave `worker_active: false`, do not emit `DispatchWorker`. The issue is queued.

**Freeing slots:** when a `WorkerResult` or `WorkerFailed` is processed, the reducer sets `worker_active: false` on the issue (freeing a slot), then checks for queued issues in the same state (`worker_active: false`, not blocked) and dispatches the next one.

**FIFO ordering:** to survive JSON serialization round-trips, the reducer state includes a `worker_queues` dict at the top level. When an issue is queued (step 4 above), its ID is appended to `worker_queues[state_name]`. When a slot frees up, the first ID is popped from the queue. When an issue transitions out of a state, it is removed from that state's queue if present.

```json
{
  "issues": { "..." },
  "worker_queues": {
    "apply": ["ISSUE-3", "ISSUE-4"]
  }
}
```

**`WorkerFailed` and slots:** when a worker fails, the slot is NOT freed. `worker_active` stays `true`, and the retry `DispatchWorker` is emitted unconditionally. This ensures the failed issue retains its slot and isn't starved by queued issues.

## Events

Four event types:

### `Create`

A new issue enters the system.

```json
{
  "type": "create",
  "issue_id": "ISSUE-1",
  "fields": {
    "title": "Build auth",
    "text": "..."
  }
}
```

**Reducer behavior:** adds the issue to state with `state` set to `initial`, `blocked: false`, `worker_active: false`, `parent: null`, `children: []`, `result_history: []`.

**Effects:** if the initial state is active, dispatch the issue (see Dispatch Protocol).

### `Advance`

Moves an issue from a passive state to a specified target state. This is how issues leave states that have no worker (e.g., `todo` → `scoping`).

```json
{
  "type": "advance",
  "issue_id": "ISSUE-1",
  "target_state": "scoping"
}
```

**Reducer behavior:**
1. Validate the issue is in a passive state
2. Validate the issue is not blocked
3. Validate `target_state` exists in the config
4. Move issue to `target_state`

**Effects:** if target state is active, dispatch the issue (see Dispatch Protocol).

Note: `Advance` intentionally allows transition to any defined state (active or passive). Passive states exist outside the `on`-rule graph — the orchestrator or external caller decides when and where to advance them. This is by design: passive states are human/scheduler-controlled entry points, not automated transitions.

### `WorkerResult`

A worker completed processing an issue.

```json
{
  "type": "worker_result",
  "issue_id": "ISSUE-1",
  "result": {
    "outcome": "decompose",
    "sub_issues": [
      {"title": "Add login", "text": "..."},
      {"title": "Add signup", "text": "..."}
    ]
  }
}
```

**Reducer behavior:**
1. Validate result against `result_format` of the current state
2. Set `worker_active: false` on the issue (frees a slot — see Dispatch Protocol)
3. Append `{state, result}` to issue's `result_history`
4. Look up `on[outcome]` routing rule
5. If simple transition: move issue to target state, remove from old state's worker queue if present
6. If `action: decompose`: create child issues at `initial` state, set parent `blocked: true`, link `parent`/`children`

**Cascading unblock check:** after any transition to a terminal state, the reducer checks whether the issue has a parent, and if so, whether all siblings (all children of the parent) are now terminal. If yes, the parent is unblocked (`blocked: false`) and dispatched (see Dispatch Protocol). This check is recursive — unblocking a parent may cause it to complete and unblock its own parent.

**Slot backfill:** after step 2, if the old state has `max_workers` and there are queued issues, dispatch the next queued issue (see Dispatch Protocol).

**Effects:**
- Simple transition to active state → dispatch the issue (see Dispatch Protocol)
- Simple transition to terminal state → check and cascade unblock (see above)
- `action: decompose` → dispatch each child whose initial state is active (see Dispatch Protocol)

**Error cases:**
- Issue is blocked → reject event, return state unchanged, emit `Error` effect
- Issue is in a terminal state → reject event, return state unchanged, emit `Error` effect
- Issue has `worker_active: false` → reject event, return state unchanged, emit `Error` effect
- Result fails validation → reject event, return state unchanged, emit `Error` effect

### `WorkerFailed`

A worker crashed, timed out, or returned an unparseable response.

```json
{
  "type": "worker_failed",
  "issue_id": "ISSUE-1",
  "error": "Worker timed out after 300s"
}
```

**Reducer behavior:** issue remains in its current state, `worker_active` stays `true` (slot is retained).

**Effects:** emit `DispatchWorker` unconditionally for the same issue (retry). The slot is not freed — the failed issue retains its position and is not displaced by queued issues. The orchestrator is responsible for retry limits and backoff — the reducer always retries. When the orchestrator decides to stop retrying, it stops sending events; the reducer does not track retry counts.

## Effects

Effects are data objects returned by the reducer. The orchestrator executes them, which eventually produce new events.

### `DispatchWorker`

```json
{
  "type": "dispatch_worker",
  "issue_id": "ISSUE-1",
  "state": "implementing",
  "result_format": { "..." },
  "issue": {
    "fields": { "..." },
    "result_history": [ "..." ],
    "parent": null,
    "children": [
      {
        "issue_id": "ISSUE-2",
        "fields": { "..." },
        "state": "done",
        "result_history": [ "..." ]
      }
    ]
  }
}
```

Tells the orchestrator to assign the issue to a worker for the given state. Includes:
- `result_format` — the output schema the worker must follow
- `issue` — full issue context including `fields`, `result_history`, and `parent`
- `issue.children` — resolved child issue data (not just IDs), including each child's `fields`, `state`, and `result_history`. This allows workers re-running after unblock to inspect child outcomes without needing access to the full system state.

### `Error`

```json
{
  "type": "error",
  "issue_id": "ISSUE-1",
  "message": "Cannot process WorkerResult: issue is blocked"
}
```

Signals an invalid event. The orchestrator decides how to handle (log, alert, discard).

## Decomposition: Multi-Level

Sub-issues can themselves decompose. The unblock mechanism works transitively:

1. ISSUE-1 decomposes into ISSUE-2 and ISSUE-3 → ISSUE-1 is blocked
2. ISSUE-2 decomposes into ISSUE-4 and ISSUE-5 → ISSUE-2 is blocked
3. ISSUE-4 and ISSUE-5 reach terminal → ISSUE-2 is unblocked, worker re-runs
4. ISSUE-2 reaches terminal → all children of ISSUE-1 are terminal → ISSUE-1 is unblocked

Each level only checks its direct children. Transitivity emerges naturally: a blocked child is not terminal, so the parent stays blocked until the child is unblocked, re-runs, and eventually reaches terminal itself.

## Sub-Issue Creation Path

Sub-issues created via `action: decompose` are added directly to the reducer state (not via a `Create` event). This is intentional — the reducer handles the full decomposition atomically in a single step. The sub-issues enter at the `initial` state with `parent` set.

## ID Generation

The caller provides issue IDs in `Create` events. For sub-issues created via decomposition, the reducer uses the `generate_id` function from its signature. See the Signature section above.

## Full orca.yml Example

```yaml
issue:
  fields:
    title:
      type: string
      description: "Short title of the issue"
    text:
      type: string
      description: "Detailed description"

initial: todo

states:
  todo: {}

  scoping:
    worker:
      result_format:
        outcome:
          type: enum
          values: [ready, decompose]
          description: "Whether the issue is ready or needs decomposition"
          values_description:
            ready: "Issue is well-scoped and ready for implementation"
            decompose: "Issue is too complex, split into sub-issues"
        sub_issues:
          type: list
          required_when: decompose
          items: $issue
          description: "Sub-issues to create when decomposing"
    on:
      ready: implementing
      decompose:
        action: decompose

  implementing:
    worker:
      result_format:
        outcome:
          type: enum
          values: [done]
          description: "The result of the implementation"
          values_description:
            done: "Implementation is complete"
        summary:
          type: string
          description: "Brief summary of what was done"
    on:
      done: ready-for-test

  ready-for-test:
    worker:
      result_format:
        outcome:
          type: enum
          values: [passed, failed]
          description: "The result of testing"
          values_description:
            passed: "All tests pass"
            failed: "Tests failed"
        report:
          type: string
          description: "Test report details"
    on:
      passed: done
      failed: implementing

  done:
    terminal: true
```

## Example: Development Pipeline with Merge Serialization

A common pattern where multiple issues implement features in parallel but must merge to main one at a time. The `apply` state uses `max_workers: 1` to serialize merges, avoiding cascade conflicts.

```yaml
issue:
  fields:
    title:
      type: string
      description: "Short title of the issue"
    text:
      type: string
      description: "Detailed description"

initial: todo

states:
  todo: {}

  implementing:
    worker:
      result_format:
        outcome:
          type: enum
          values: [done]
          description: "Implementation result"
          values_description:
            done: "Implementation is complete"
        summary:
          type: string
          description: "What was implemented"
    on:
      done: qa

  qa:
    worker:
      result_format:
        outcome:
          type: enum
          values: [passed, failed]
          description: "QA result"
          values_description:
            passed: "All tests pass, code meets requirements"
            failed: "Tests failed or requirements not met"
        report:
          type: string
          description: "Test report"
    on:
      passed: apply
      failed: implementing

  apply:
    max_workers: 1
    worker:
      result_format:
        outcome:
          type: enum
          values: [merged, rebase_conflict]
          description: "Merge result"
          values_description:
            merged: "Rebased onto latest main and merged"
            rebase_conflict: "Rebase conflicts require implementation changes"
    on:
      merged: done
      rebase_conflict: implementing

  done:
    terminal: true
```

**How it avoids the cascade problem:**

Without `max_workers: 1`, if 4 issues reach `apply` simultaneously, one merges and the other 3 conflict — sending them all back through `implementing → qa → apply`, causing 10 full cycles worst case.

With `max_workers: 1` on `apply`, issues are serialized:
1. Issue A enters `apply`: rebase onto main (trivial) → merge → done
2. Issue B enters `apply`: rebase onto main (includes A) → merge → done
3. Issue C enters `apply`: rebase onto main (includes A+B) → merge → done
4. Issue D enters `apply`: rebase onto main (includes A+B+C) → merge → done

Each `apply` worker rebases onto the latest main before merging. Since only one issue merges at a time, the rebase is always against the current main — no conflicts between in-flight merges. Only genuine conflicts (overlapping file changes that can't auto-resolve) send an issue back to `implementing`.

## Future Considerations

- **Worker type/command** — `worker` currently only defines `result_format`. Eventually it will need to specify which CLI agent to invoke. Out of scope for the reducer.
- **Additional field types** — `integer`, `boolean`, `object` in `result_format` and `issue.fields`.
- **Conditional transitions** — routing based on multiple fields, not just `outcome`.
