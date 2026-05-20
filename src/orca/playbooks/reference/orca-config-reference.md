# Orca Config Reference

Full `.orca/{flow-name}.yml` schema. Lookup document, not a procedure — read the section relevant to the field you're touching.

For procedure-style playbooks, see:
- [`../orca-workflow-create.md`](../orca-workflow-create.md) — author a new workflow end-to-end
- [`../orca-workflow-review.md`](../orca-workflow-review.md) — audit an existing workflow
- [`orca-workflow-patterns.md`](orca-workflow-patterns.md) — reusable building blocks (sibling reference doc)
- [`orca-glossary.md`](orca-glossary.md) — one-line definitions for terms used below

## Top-Level Structure

Two formats supported:

**Typed (recommended):**
```yaml
root_type: feature
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
```

## Global Fields

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `root_type` | string | yes (typed) | — | Must match a key in `types:` |
| `base_branch` | string | no | `origin/main` | Default git branch new run branches are cut from. Prompt templates receive a live `{{ issue.base_branch }}` value, but that value is resolved from the run/parent branch rather than copied directly from this setting. |

### Runtime Bounds

`max_hops` and `max_worker_retries` are effective run limits, but they are **not part of the workflow YAML schema in the current engine**. The parser ignores top-level YAML keys with those names. Set them at launch:

- CLI: `orca run <task> --max-hops 15 --max-retries 3`
- CLI defaults: `orca run` applies `--max-hops 10 --max-retries 3` unless overridden.
- MCP / daemon submissions only apply these limits if the caller passes `max_hops` / `max_retries` through the daemon API. The public `orca_start_run` MCP tool currently does not expose those knobs.

Recommended launch values: `--max-hops 10–20`, `--max-retries 3–5` for production; evals should usually fail faster.

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

These are set by the orchestrator at runtime, not by the user.

| Name | Set When | Access path in prompts | Schema requirement |
|---|---|---|---|
| `failure_context` | Worker fails or transitions to the built-in `failed` target | `{{ issue.fields.failure_context }}` — **inside `fields`** | Must be declared in the type's `fields:` block (as `type: string`) for the orchestrator to set it. If not declared, the failure context is silently dropped. |
| `base_branch` | Worker dispatched | `{{ issue.base_branch }}` — **top-level on `issue`, not under `fields`** | No declaration needed. For a root issue this is the run branch; for a child issue it is the parent issue's branch. The top-level config `base_branch` is used when creating a new run branch, not as the value injected into every prompt. |

The two access paths differ because `failure_context` is layered into the user-defined field schema (you opt in by declaring it), while `base_branch` is a runtime-only injection that doesn't live in the schema. The prompt-create playbook restates this where it bites — see [`../orca-prompt-create.md`](../orca-prompt-create.md) Step 2.

## State Definition

```yaml
states:
  implementing:
    max_workers: 1          # Optional. Concurrent worker limit for this (type, state) pair
    worker:                  # Optional. If absent, state is passive (manual advance only)
      kind: claude-code      # Required. See supported kinds below
      prompt: prompts/impl.md  # Required. Jinja2 template path (relative to .orca/ directory)
                               # — or { path: prompts/impl.md } for explicit path
                               # — or { text: "Inline Jinja {{ issue.fields.title }}..." } for inline source
      timeout: 1200          # Optional. Used as the inactivity timeout when inactivity_timeout is absent
      inactivity_timeout: 300  # Optional. Kill if no progress for N seconds. Default: 300.
                               # Paused while the worker is in the `waiting` outcome
                               # (see *Built-in Outcomes* below).
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
| Passive | no | no | Issue waits for a manual `AdvanceEvent` from the TUI/API surface |

### Worker Field Reference

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `kind` | `claude-code` \| `codex` \| `opencode` | yes | — | Which agent CLI orca spawns the worker as. |
| `prompt` | string \| mapping | yes | — | Jinja2 prompt source. Accepts three shapes: (1) bare string — path to a template file, relative to `.orca/`; (2) `{ path: <str> }` — same, but explicit; (3) `{ text: <str> }` — inline Jinja source rendered directly. Rendered with the issue context before dispatch. |
| `timeout` | positive int (seconds) | no | none | Compatibility fallback for `inactivity_timeout`. In the current worker loop this is **not** a hard wall-clock cap; if `inactivity_timeout` is absent, `timeout` becomes the no-progress timeout. |
| `inactivity_timeout` | positive int (seconds) | no | 300 | Kill the worker if no progress for this many seconds. **Paused while the worker's last outcome is `waiting`** (so HITL doesn't trip the timer). |
| `model` | string | no | inherits from the agent CLI | Passed to the worker CLI as `-m <model>`. Accepted values are whatever the CLI supports — for `claude-code`, a Claude model id like `claude-sonnet-4-6`; for `codex`, an OpenAI model id like `gpt-5.4`; for `opencode`, its provider/model scheme. |
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
    child_type: task       # Required for typed configs unless every sub_issue supplies `type`.
                           # Legacy single-type configs default this to "default".
    # then: done           # Optional. If set, parent transitions here immediately
                           # after creating children. If omitted, parent blocks
                           # until all children reach "done".
```

Requires `sub_issues` with `items: "$issue"` in `result_format`.

Each emitted `sub_issues` entry should include a stable `key` string. Sibling `depends_on` lists reference these keys; the engine resolves them to real issue ids when it creates the children.

## Built-in Transition Targets

Both targets are always-valid in any `on:` rule. Neither may be defined explicitly under `states:` — the parser will reject it.

| Target | Behavior |
|---|---|
| `done` | A terminal sink. The issue parks here permanently and triggers cascading unblock of parents/dependents. Routing an outcome to `done` ends the issue cleanly. |
| `failed` | A *control directive*, not a destination state. Routing an outcome to `failed` (e.g. `on: { irrecoverable: failed }`) tells the engine to treat that outcome as a worker failure: it increments `failure_count`, and the engine either retries the same state (if under `max_worker_retries`) or surfaces a stuck issue. The issue does not "live" in `failed` — it stays in its current state, just with a bumped failure counter. |

The naming asymmetry is on purpose: `done` is where issues *end up*, `failed` is what happens *to them*. In the engine code both are members of a `BUILTIN_STATES` set (because both are valid right-hand sides of an `on:` rule), but only `done` is an actual final resting state.

**Outcome value named `failed` ≠ built-in `failed` target.** You may declare `values: [applied, failed]` and route `failed: implementing` — that is a user-defined outcome going to a user-defined state, no special semantics. Only the right-hand side of the `on:` rule matters for triggering failure handling.

## Built-in Outcomes

Always available. Workers can emit these even when they aren't declared in `result_format.outcome.values`.

| Outcome | Behavior |
|---|---|
| `waiting` | No `on:` rule needed; do not declare in `values:`. The orchestrator pauses the inactivity timer and keeps the tmux session alive. The worker resumes when unblocked via `orca unblock <run_id> <issue_id> -m "<message>"` (the message is delivered via `tmux send-keys`). A worker may enter `waiting` multiple times in a single session. |

## Multi-Flow Convention

A project can have many workflows under `.orca/`: `.orca/{flow-name}.yml`

Examples: `.orca/develop.yml`, `.orca/prd.yml`, `.orca/qa-spec.yml`, `.orca/investigate.yml`

Select with `-w`: `orca run task.md -w develop` loads `.orca/develop.yml`. Default (no `-w`) loads `.orca/default.yml`.

## Evals

Orca recognizes `.orca/evals/<name>/eval-flow.yml` as an eval workflow.

```
.orca/
  develop.yml                # production workflow
  prompts/
    scoping.md
  evals/
    scoping-decomposes-large-spec/
      eval-flow.yml          # bookended workflow: <body slice> -> assert
      input.md               # scenario + YAML frontmatter (seeds issue.fields, declares state_ref)
      assertions.md          # pass/fail checklist
```

Plus, outside `.orca/`:

```
orca-eval-state/<name>            # orphan git branch holding the worktree fixture bytes
.orca-state/eval-states/<name>/   # persistent author worktree checked out to that branch
```

Recognized conventions:

- The directory `<name>` is kebab-case and descriptive of the scenario.
- The workflow file is named `eval-flow.yml` (not `orca.yml`) so it's grep-distinguishable from production workflows.
- The directory must also contain `input.md` (issue data + scenario + `state_ref` marker) and `assertions.md` (pass/fail checklist).
- The workflow follows a bookended shape: `<body slice> -> assert`. There is no `setup` state — the daemon checks the branch named by `input.md`'s `state_ref` frontmatter out into the run worktree before any body state runs. Body states are copied from the production workflow with eval-harness rewrites: `prompt:` paths use `../../prompts/<name>.md`, internal transitions stay inside the slice, and outgoing transitions to states outside the slice route to `assert`.
- When the engine loads a config file at this path, it sets `run.eval_name = <name>` and `run.repo_root = <absolute repo root>` in the Jinja template context. The `assert` inline prompt uses these to locate `.orca/evals/<name>/assertions.md` on the iteration branch.
- `input.md` supports YAML frontmatter at the top. The engine parses it and seeds `issue.fields.*` before the slice's entry state runs. The frontmatter must include a `state_ref:` line naming the git branch to check out into the worktree (typically `orca-eval-state/<name>`).
- The `assert` state writes `report.md` into `{{ run.run_dir }}/report.md`. The source directory stays clean; reports live with the run.
- The fixture bytes the slice will read live on the state-ref branch, not in a `fixtures/` directory and not under `.orca/evals/<name>/`. Author them by `cd`'ing into the persistent worktree at `.orca-state/eval-states/<name>/` and committing with plain git. (A `fixtures/` directory under an eval is a leftover from the pre-state-branch model — flag it via `orca-eval-review.md`.)

See [`../orca-eval-create.md`](../orca-eval-create.md) for the authoring procedure and [`../orca-eval-review.md`](../orca-eval-review.md) for the audit checklist.

### Result Format Validation Scope

`result_format` is the worker-facing output contract and the source for `{{ result_example }}`. Runtime validation is intentionally shallow today:

- `outcome` is required and must be one of `result_format.outcome.values`.
- Fields with `required_when` must be present and non-empty when the outcome matches.
- Nested `items` shapes, scalar subtypes such as `integer`, and object field details are not deeply validated by the engine. Use assertions/evals to grade those details.

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
| Valid worker kind | Must be `claude-code`, `codex`, or `opencode` |
| Non-empty prompt | `worker.prompt` required if worker defined. If given as a mapping, exactly one of `path` or `text` must be set. |
| Positive timeout | `timeout` must be a positive integer when present |
| Positive max_workers | `max_workers` must be positive integer |
| Decompose requires sub_issues | If `on:` has decompose action, result_format needs `sub_issues` with `items: "$issue"` |
| Decompose child_type exists | `child_type` must be a key in `types:` (if specified) |
| Decompose then target exists | `then` target must be in states or built-in states |
| Reserved names protected | Cannot define states named `done` or `failed` |
| No unreachable states | Non-initial, non-passive states must be reachable from initial via on: rules |

The parser does not require every enum value to have an `on:` route, but the reducer errors if a worker emits an unrouted outcome. In practice, route every non-`waiting` outcome the prompt allows the worker to emit.
