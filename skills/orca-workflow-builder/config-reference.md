# Orca Config Reference

Full `orca.{flow-name}.yml` schema. Use as lookup when creating or validating workflows.

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
integrations:
  slack:
    bot_token_env: SLACK_BOT_TOKEN
    app_token_env: SLACK_APP_TOKEN
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

| Field | Type | Required | Description |
|---|---|---|---|
| `root_type` | string | yes (typed) | Must match a key in `types:` |
| `max_hops` | positive int | no | Max state transitions per issue. Prevents infinite loops |
| `max_worker_retries` | positive int | no | Max worker failures per issue in same state before giving up |
| `base_branch` | string | no | Default git branch for merging. Available as `{{ issue.base_branch }}` |
| `integrations` | object | no | Slack config for `needs_feedback` |

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

| Type | Description | Extra Fields |
|---|---|---|
| `string` | Arbitrary text | `description` |
| `enum` | Predefined values | `values`, `description` |

### Auto-Populated Fields

These are set by the orchestrator, not the user. Define them in `fields:` if your prompts need them:

| Field | Set When | Contains |
|---|---|---|
| `feedback_questions` | Worker returns `needs_feedback` | Questions the worker asked |
| `feedback_context` | User answers via Slack | User's answers |
| `failure_context` | Worker fails | Error message from last failure |
| `base_branch` | Run starts | Git branch for merging |

## State Definition

```yaml
states:
  implementing:
    max_workers: 1          # Optional. Concurrent worker limit for this (type, state) pair
    worker:                  # Optional. If absent, state is passive (manual advance only)
      kind: claude-code      # Required. "claude-code" or "opencode"
      prompt: prompts/impl.md  # Required. Jinja2 template path (relative to repo root)
      timeout: 1200          # Optional. Hard kill after N seconds
      inactivity_timeout: 300  # Optional. Kill if no result file for N seconds. Default: 300
      model: claude-3-5-sonnet  # Optional. Override worker model
      args: ["--max-turns", "100"]  # Optional. Extra CLI args
      progress: true         # Optional. Enable PROGRESS: <pct> | <status> reporting
      result_format:         # Required if worker present
        outcome:             # Required. Must be enum type
          type: enum
          values: [done, blocked, needs_feedback]
          description: "Result"
          values_description:
            done: "Complete"
            blocked: "Cannot proceed"
            needs_feedback: "Need user input"
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
      # needs_feedback — reserved, no rule needed
```

### State Types

| Type | Has worker? | Has on:? | Behavior |
|---|---|---|---|
| Active | yes | yes | Worker runs, outcome routes to next state |
| Passive | no | no | Issue waits for manual `AdvanceEvent` |

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

## Built-in States

Always available. Never define them in `states:`.

| State | Behavior |
|---|---|
| `done` | Terminal. Issue stays here permanently. Triggers cascading unblock of parents/dependents. |
| `failed` | Not actually visited. Using `on: { outcome: failed }` triggers worker failure/retry semantics. |

## Reserved Outcomes

| Outcome | Behavior |
|---|---|
| `needs_feedback` | No `on:` rule needed. Orchestrator spawns Slack feedback agent, re-dispatches worker with `feedback_context` after user answers. Increments `failure_count`. |

## Multi-Flow Convention

A project can have many workflows: `orca.{flow-name}.yml`

Examples: `orca.develop.yml`, `orca.prd.yml`, `orca.qa-spec.yml`, `orca.investigate.yml`

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
