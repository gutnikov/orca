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
1. Validate `sub_issues` is not empty
2. Create sub-issues from the `sub_issues` field in the worker result, setting `decomposed_from` to the parent issue ID
3. Resolve `key`/`depends_on` references between siblings to real issue IDs
4. Keep the parent in its current state — it is now decomposition-blocked (has non-terminal children)
5. When all children reach a terminal state, the parent is automatically unblocked and the worker re-runs

Each sub-issue in the result may include:
- `key` — temporary identifier for sibling references (not stored in state)
- `depends_on` — list of sibling `key` values this sub-issue depends on (resolved to real IDs)

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
      "worker_active": false,
      "decomposed_from": null,
      "depends_on": [],
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
      "worker_active": false,
      "decomposed_from": "ISSUE-1",
      "depends_on": [],
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
    },
    "ISSUE-3": {
      "fields": {
        "title": "Add order endpoint",
        "text": "..."
      },
      "state": "implementing",
      "worker_active": true,
      "decomposed_from": "ISSUE-1",
      "depends_on": ["ISSUE-4"],
      "result_history": []
    },
    "ISSUE-4": {
      "fields": {
        "title": "Set up database",
        "text": "..."
      },
      "state": "done",
      "worker_active": false,
      "decomposed_from": "ISSUE-1",
      "depends_on": [],
      "result_history": [
        {
          "state": "implementing",
          "result": {"outcome": "done", "summary": "DB setup complete"}
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
- `worker_active` — `true` when a worker has been dispatched and hasn't returned yet, `false` otherwise
- `decomposed_from` — ID of the issue this was decomposed from, or `null`. Replaces the old `parent` field. An issue's "children" are computed: all issues where `decomposed_from == this_issue_id`.
- `depends_on` — list of issue IDs that must reach a terminal state before this issue can be dispatched to a worker. Supports diamond dependencies (multiple issues depending on the same issue).
- `result_history` — ordered list of worker results. Each entry records the `state` and the worker's `result`. Appended on every `WorkerResult` event.

### Blocking

The old `blocked` boolean is replaced by **computed blocking** from two sources:

1. **Decomposition block:** an issue has children (issues with `decomposed_from == this_id`) that are not all in a terminal state. When blocked this way, the issue re-runs its worker once all children reach terminal (the "synthesize" pattern).

2. **Dependency block:** an issue has entries in `depends_on` that are not all in a terminal state. When blocked this way, the issue simply waits — once all dependencies are terminal, the issue proceeds normally (dispatched for the first time or continues from where it was).

An issue is considered **blocked** if either condition is true. The Dispatch Protocol checks both before dispatching.

### Dispatch Protocol

All `DispatchWorker` emission goes through a single protocol. Every place in the spec that says "dispatch the issue" follows these rules:

1. Check if the issue is blocked (has non-terminal children OR has non-terminal dependencies). If blocked, do not dispatch.
2. Check if the issue's state has `max_workers` set
3. If yes, count issues in that state with `worker_active: true`
4. If count < `max_workers` (or `max_workers` is not set): set `worker_active: true` on the issue, emit `DispatchWorker` effect
5. If count >= `max_workers`: leave `worker_active: false`, do not emit `DispatchWorker`. The issue is queued.

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

**Reducer behavior:** adds the issue to state with `state` set to `initial`, `worker_active: false`, `decomposed_from: null`, `depends_on: []`, `result_history: []`.

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
2. Validate the issue is not blocked (no non-terminal children, no non-terminal dependencies)
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
      {"key": "db", "title": "Set up database", "text": "..."},
      {"key": "users", "title": "Add user endpoint", "text": "...", "depends_on": ["db"]},
      {"key": "orders", "title": "Add order endpoint", "text": "...", "depends_on": ["db"]}
    ]
  }
}
```

Sub-issues in the decompose result support:
- `key` — a temporary identifier used to reference siblings within the same decompose result. Not stored in state — resolved to real IDs by the reducer.
- `depends_on` — list of `key` values referencing other sub-issues in the same result. The reducer resolves these to real issue IDs and sets `depends_on` on the created issues. This enables diamond dependencies: both "users" and "orders" depend on "db."

**Reducer behavior:**
1. Validate result against `result_format` of the current state
2. Set `worker_active: false` on the issue (frees a slot — see Dispatch Protocol)
3. Append `{state, result}` to issue's `result_history`
4. Look up `on[outcome]` routing rule
5. If simple transition: move issue to target state, remove from old state's worker queue if present
6. If `action: decompose`:
   a. Validate `sub_issues` is not empty — empty decompose is an error
   b. Generate IDs for each sub-issue, build a `key → real_id` mapping
   c. Create child issues at `initial` state with `decomposed_from` set to the parent issue ID
   d. Resolve `depends_on` keys to real IDs for each child
   e. The parent is now decomposition-blocked (it has non-terminal children)

**Cascading unblock check:** after any transition to a terminal state, the reducer checks:
1. **Decomposition unblock:** find all issues where `decomposed_from == this_issue's decomposed_from` (siblings). If all siblings are terminal, the parent (the issue they were decomposed from) is no longer decomposition-blocked. If the parent was waiting (decomposition-blocked), dispatch it (see Dispatch Protocol) — the worker re-runs.
2. **Dependency unblock:** find all issues that have this issue in their `depends_on`. For each, check if all their dependencies are now terminal. If yes and the issue is in an active state, dispatch it (see Dispatch Protocol).

Both checks are recursive — unblocking a parent may cause it to complete and trigger further unblocks up the chain.

**Slot backfill:** after step 2, if the old state has `max_workers` and there are queued issues, dispatch the next queued issue (see Dispatch Protocol).

**Effects:**
- Simple transition to active state → dispatch the issue (see Dispatch Protocol)
- Simple transition to terminal state → check and cascade unblock (see above)
- `action: decompose` → dispatch each child that is not dependency-blocked and whose initial state is active (see Dispatch Protocol)

**Error cases:**
- Issue is blocked → reject event, return state unchanged, emit `Error` effect
- Issue is in a terminal state → reject event, return state unchanged, emit `Error` effect
- Issue has `worker_active: false` → reject event, return state unchanged, emit `Error` effect
- Result fails validation → reject event, return state unchanged, emit `Error` effect
- `action: decompose` with empty `sub_issues` → reject event, return state unchanged, emit `Error` effect
- `depends_on` references a `key` that doesn't exist in the same decompose result → reject, emit `Error` effect

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
  "state": "scoping",
  "result_format": { "..." },
  "issue": {
    "fields": { "..." },
    "result_history": [ "..." ],
    "decomposed_from": null,
    "depends_on": [],
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
- `issue` — full issue context including `fields`, `result_history`, `decomposed_from`, and `depends_on`
- `issue.children` — resolved child issue data (computed from all issues where `decomposed_from == this_issue_id`), including each child's `fields`, `state`, and `result_history`. This allows workers re-running after decomposition unblock to inspect child outcomes.

### `Error`

```json
{
  "type": "error",
  "issue_id": "ISSUE-1",
  "message": "Cannot process WorkerResult: issue is blocked"
}
```

Signals an invalid event. The orchestrator decides how to handle (log, alert, discard).

## Dependency Graph (DAG)

Issues form a directed acyclic graph through two edge types:

### Decomposition edges (`decomposed_from`)

Express "I was created by splitting this parent issue." When all children reach terminal, the parent re-runs its worker to synthesize results.

**Multi-level decomposition** works transitively:
1. ISSUE-1 decomposes into ISSUE-2 and ISSUE-3 → ISSUE-1 is decomposition-blocked
2. ISSUE-2 decomposes into ISSUE-4 and ISSUE-5 → ISSUE-2 is decomposition-blocked
3. ISSUE-4 and ISSUE-5 reach terminal → ISSUE-2 unblocks, worker re-runs
4. ISSUE-2 reaches terminal → all children of ISSUE-1 are terminal → ISSUE-1 unblocks

### Dependency edges (`depends_on`)

Express "I need these issues done before I can start." When all dependencies reach terminal, the issue proceeds normally.

**Diamond dependencies** are supported:
```
A decomposes into:
  db (no dependencies)
  users (depends_on: [db])
  orders (depends_on: [db])
```

Both `users` and `orders` wait for `db`. This is not possible in a tree model where each issue has a single parent.

### Cycle prevention

The reducer validates that `depends_on` references only exist between siblings (issues in the same decompose result). This prevents cycles by construction — you can't depend on an issue outside your decompose group, and you can't depend on yourself.

### Blocking summary

An issue is **blocked** if:
- It has children (`decomposed_from == this_id`) that are not all terminal, OR
- It has `depends_on` entries that are not all terminal

Both are computed — there is no `blocked` boolean in the state.

## Sub-Issue Creation Path

Sub-issues created via `action: decompose` are added directly to the reducer state (not via a `Create` event). This is intentional — the reducer handles the full decomposition atomically in a single step. The sub-issues enter at the `initial` state with `decomposed_from` set. Dependencies between siblings are resolved from `key` references to real IDs during creation.

## Empty Decompose

Returning `action: decompose` with an empty `sub_issues` list is an **error**. The reducer rejects the event, returns state unchanged, and emits an `Error` effect. Rationale: empty decompose would cause immediate vacuous unblock (zero children are trivially "all terminal"), leading to infinite loops if the worker keeps returning decompose with no children.

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
          description: "Sub-issues to create. Each item may include 'key' (sibling ref) and 'depends_on' (list of sibling keys)."
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
- **Cross-group dependencies** — currently `depends_on` only supports siblings within the same decompose result. A future `AddDependency` event could link any two existing issues, enabling cross-group dependency graphs.
- **Dependency cycle detection** — currently prevented by construction (sibling-only). If cross-group dependencies are added, explicit cycle detection will be needed.
