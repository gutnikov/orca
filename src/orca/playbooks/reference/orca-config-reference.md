# Orca Config Reference

Full `.orca/{flow-name}.yml` schema. Lookup document, not a procedure — read the section relevant to the field you're touching.

For procedure-style playbooks, see:
- [`../orca-create-workflow.md`](../orca-create-workflow.md) — author a new workflow end-to-end
- [`../orca-review-workflow.md`](../orca-review-workflow.md) — audit an existing workflow
- [`orca-workflow-patterns.md`](orca-workflow-patterns.md) — reusable building blocks (sibling reference doc)
- [`orca-glossary.md`](orca-glossary.md) — one-line definitions for terms used below

## Top-Level Structure

Two formats supported:

**Typed (recommended):**
```yaml
root_type: feature
max_hops: 10
max_worker_retries: 5
base_branch: origin/main
types:
  feature:
    fields: { ... }
    initial: planning
    states: { ... }
  task:
    fields: { ... }
    initial: implementing
    states: { ... }
```

**Legacy (single-type, auto-wrapped as type "default"):**
```yaml
issue:
  fields: { ... }
initial: planning
states: { ... }
max_hops: 10
```

## Global Fields

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `root_type` | string | yes (typed) | — | Must match a key in `types:` |
| `max_hops` | positive int | no | unset (unbounded) | Max state transitions per issue. Prevents infinite loops. **Recommended: 10–20.** |
| `max_worker_retries` | positive int | no | unset (unbounded) | Max worker failures per issue in the same state before giving up. **Recommended: 3–5.** |
| `base_branch` | string | no | — | Default git branch new feature branches are cut from and merge back into. At runtime, orca injects this value into every issue context as `{{ issue.base_branch }}` (see *Auto-Populated Fields* below). |

## Type Definition

Each type has its own independent state machine.

```yaml
types:
  feature:
    fields:
      title:
        type: string
        description: "Feature title"
      scope_boundary:
        type: string
        description: "Files this feature owns"
      priority:
        type: enum
        values: [high, medium, low]
        description: "Priority level"
    initial: planning      # Required. Must be a key in states:
    states:
      planning: { ... }
      implementing: { ... }
```

### Field Types

Only two types are supported for top-level issue fields:

| Type | Description | Extra fields |
|---|---|---|
| `string` | Arbitrary text | `description` |
| `enum` | Predefined values | `values` (list), `description` |

Collections of child issues use the special `sub_issues` form in `result_format`, not the issue schema — see the *State Definition* section below.

### Auto-Populated Fields

These are set by the orchestrator at runtime, not by the user. Declare them in `fields:` only if your prompts need to reference them via Jinja:

| Field | Set When | Contains |
|---|---|---|
| `failure_context` | Worker fails or transitions to the built-in `failed` target | Error message from the last failure (use in retry prompts) |
| `base_branch` | Worker dispatched | The global `base_branch` value, injected into the issue context as `{{ issue.base_branch }}` |

## State Definition

```yaml
states:
  implementing:
    max_workers: 1          # Optional. Concurrent worker limit for this (type, state) pair
    worker:                  # Optional. If absent, state is passive (manual advance only)
      kind: claude-code      # Required. See supported kinds below
      prompt: prompts/impl.md  # Required. Jinja2 template path (relative to .orca/ directory)
      timeout: 1200          # Optional. Hard kill after N seconds of total wall-clock
      inactivity_timeout: 300  # Optional. Kill if no progress for N seconds. Default: 300.
                               # Paused while the worker's last outcome is `waiting`.
      model: claude-sonnet-4-6  # Optional. Override worker model
      args: ["--max-turns", "100"]  # Optional. Extra CLI args
      progress: true         # Optional. Enable PROGRESS: <pct> | <status> reporting
      result_format:         # Required if worker present
        outcome:             # Required. Must be enum type
          type: enum
          values: [done, blocked]
          description: "Result"
          values_description:
            done: "Complete"
            blocked: "Cannot proceed"
        summary:
          type: string
          description: "Brief summary"
          required_when: [blocked]  # Only required when outcome matches
        sub_issues:
          type: list
          items: "$issue"    # Special: each item is a full issue for decomposition
          required_when: [decompose]
    on:                      # Optional. Routing rules based on outcome
      done: testing          # Transition: outcome → target state
      blocked: planning      # Can loop back
```

### State Types

| Type | Has worker? | Has on:? | Behavior |
|---|---|---|---|
| Active | yes | yes | Worker runs, outcome routes to next state |
| Passive | no | no | Issue waits for manual `AdvanceEvent` |

### Worker Field Reference

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `kind` | `claude-code` \| `opencode` | yes | — | Which agent CLI orca spawns the worker as. |
| `prompt` | string (path) | yes | — | Jinja2 template path, relative to `.orca/`. Rendered with the issue context before dispatch. |
| `timeout` | positive int (seconds) | no | none | Hard wall-clock kill. Use for worst-case bounding; the worker is terminated regardless of activity. |
| `inactivity_timeout` | positive int (seconds) | no | 300 | Kill the worker if no progress for this many seconds. **Paused while the worker's last outcome is `waiting`** (so HITL doesn't trip the timer). |
| `model` | string | no | inherits from the agent CLI | Passed to the worker CLI as `-m <model>`. Accepted values are whatever the CLI supports — for `claude-code`, a Claude model id like `claude-sonnet-4-6`; for `opencode`, its provider/model scheme. |
| `args` | list of strings | no | — | Extra CLI args appended to the worker invocation. Use sparingly — most knobs have dedicated fields. |
| `progress` | bool | no | `false` | When `true`, the orchestrator injects a "Progress Reporting" preamble into the rendered prompt asking the worker to emit `PROGRESS: <pct> \| <status>` lines as it works. The orchestrator parses these lines and surfaces them in the TUI and session manifest. Cheap to enable; useful when a state's wall-clock is long. |
| `result_format` | dict | yes (if worker present) | — | Output schema; see *Result Format* below. |

## On: Rules

### Transition Rule

```yaml
on:
  done: testing            # outcome "done" → move to state "testing"
  blocked: planning        # outcome "blocked" → move to state "planning"
```

Target must be a state name or built-in state (`done`, `failed`).

### Decompose Rule

```yaml
on:
  decompose:
    action: decompose      # Required
    child_type: task       # Optional. Type for child issues. Defaults to root_type
    then: done             # Optional. Parent transitions here after creating children
                           # If omitted, parent blocks until all children reach "done"
```

Requires `sub_issues` with `items: "$issue"` in `result_format`.

## Built-in Transition Targets

Always-valid targets in any `on:` rule. Never define them under `states:` — the parser will reject it.

| Target | Behavior |
|---|---|
| `done` | Terminal. The issue stays here permanently and triggers a cascading unblock of parents/dependents. |
| `failed` | Not a destination state — using `failed` as the target of an `on:` rule (e.g. `on: { irrecoverable: failed }`) triggers worker-failure/retry semantics for that outcome. The issue's `failure_count` increments and orca either retries (if under `max_worker_retries`) or surfaces a stuck issue. |

Note: an *outcome value* named `failed` is **not** the same thing as the built-in `failed` target. You may use `failed` as an outcome value (e.g. `values: [applied, failed]`) and route it to any state — what matters is the right-hand side of the `on:` rule, not the outcome name.

## Built-in Outcomes

Always available. Workers can emit these even when they aren't declared in `result_format.outcome.values`.

| Outcome | Behavior |
|---|---|
| `waiting` | No `on:` rule needed; do not declare in `values:`. The orchestrator pauses the inactivity timer and keeps the tmux session alive. The worker resumes when unblocked via `orca unblock <run_id> <issue_id> -m "<message>"` (the message is delivered via `tmux send-keys`). A worker may enter `waiting` multiple times in a single session. |

## Multi-Flow Convention

A project can have many workflows under `.orca/`: `.orca/{flow-name}.yml`

Examples: `.orca/develop.yml`, `.orca/prd.yml`, `.orca/qa-spec.yml`, `.orca/investigate.yml`

Select with `-w`: `orca run task.md -w develop` loads `.orca/develop.yml`. Default (no `-w`) loads `.orca/default.yml`.

## Validation Rules

The config parser enforces all of these. A workflow that violates any rule will fail to load.

| Rule | Constraint |
|---|---|
| Root type exists | `root_type` must be a key in `types:` |
| Initial state exists | `initial` must be a key in `states:` |
| On targets exist | Every transition target must be in `states:` or built-in states |
| Outcomes match | Every `on:` key must be a value in `result_format.outcome.values` |
| Active state routing | States with worker + on: must have `outcome` enum in result_format |
| At least one routable outcome | State must have ≥1 non-reserved outcome with an `on:` rule |
| Valid worker kind | Must be `claude-code` or `opencode` |
| Non-empty prompt | `worker.prompt` required if worker defined |
| Positive timeouts | `timeout`, `inactivity_timeout` must be positive integers |
| Positive max_workers | `max_workers` must be positive integer |
| Positive max_hops | `max_hops` must be positive integer |
| Decompose requires sub_issues | If `on:` has decompose action, result_format needs `sub_issues` with `items: "$issue"` |
| Decompose child_type exists | `child_type` must be a key in `types:` (if specified) |
| Decompose then target exists | `then` target must be in states or built-in states |
| Reserved names protected | Cannot define states named `done` or `failed` |
| No unreachable states | Non-initial, non-passive states must be reachable from initial via on: rules |
