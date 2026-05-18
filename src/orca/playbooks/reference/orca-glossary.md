# Orca Glossary

One-line definitions for terms that recur across the playbooks. Use this as a tiebreaker when one playbook's wording disagrees with another's — the definition here is authoritative.

## Workflow shape

- **Workflow.** A single `.orca/{flow}.yml` file plus its referenced prompt templates. A project may have many workflows under `.orca/`. Selected at run time with `orca run task.md -w <flow>`; `default.yml` is the default.
- **Type.** One self-contained state machine inside a workflow (e.g. `epic`, `task`). In legacy single-type configs, the parser auto-wraps everything as type `default`. Each type has its own `fields`, `initial`, and `states`. The top-level `root_type` names which type root issues start as.
- **State.** A named position in a type's state machine. Has a `worker` (active) or doesn't (passive).
- **Active state.** Has a `worker:` block. The worker runs, produces a result, and the result's outcome routes via `on:`.
- **Passive state.** Has no `worker:` and no `on:`. Issue parks here until a manual `AdvanceEvent` (CLI / TUI / API). Used for human gates.
- **Issue.** A single unit of work flowing through the state machine. Has fields, a current state, an event log, and (optionally) children. The starting issue of a run is the *root issue*.

## Outcomes vs transitions vs targets

These three terms are routinely conflated. They are distinct:

- **Outcome.** A value the worker writes into its result file under `outcome:`. Outcomes are enum values declared in the state's `result_format.outcome.values`, plus the always-available built-in `waiting`.
- **Transition rule.** An `on:` entry. The *key* is an outcome value; the *value* is a transition target.
- **Transition target.** Where the rule routes the issue. Must be either (a) a state name in `states:`, or (b) a built-in target (`done`, `failed`).

### Built-in targets vs built-in outcomes

| Name | Kind | What it does |
|---|---|---|
| `done` | built-in target | Terminal. Issue stays here permanently and triggers cascading unblock of parents/dependents. |
| `failed` | built-in target | Not a destination state. Used as a target (`on: { irrecoverable: failed }`) to trigger worker-failure / retry semantics for that outcome. Increments `failure_count`; orca retries up to `max_worker_retries` then surfaces as stuck. |
| `waiting` | built-in outcome | Emitted by the worker (`{"outcome": "waiting", "reason": "..."}`) to pause for human input. No `on:` rule needed; do not declare in `values:`. Pauses the inactivity timer; resumes when unblocked via `orca unblock`. |

**`failed` as an outcome value is not the same thing as the built-in `failed` target.** You may declare `values: [applied, failed]` and route `failed: implementing` — that's a regular user-defined outcome. What matters is the right-hand side of the `on:` rule.

## Bounds and timers

| Name | Scope | Counts | Recommended | Why it exists |
|---|---|---|---|---|
| `max_hops` | global | *Every* state transition per issue | 10–20 | Bounds long pipelines and `blocked` self-loops. |
| `max_worker_retries` | global | Worker *failures* (crashes, timeouts, `failed` target) per issue in the same state | 3–5 | Bounds retry loops from a state crashing the worker. Does not count `blocked` results. |
| `max_workers` | per (type, state) | Concurrent workers running in this state | `1` on merge/apply/deploy; omit for parallel-safe work | Serializes shared-resource writes. |
| `timeout` | per worker | Wall-clock seconds | bound to worst case | Hard kill regardless of activity. |
| `inactivity_timeout` | per worker | Seconds without progress | 300 default | Kills wedged workers. **Paused while the worker's outcome is `waiting`.** |

## Decomposition

- **Decompose action.** An `on:` rule with `{ action: decompose, ... }`. Spawns child issues from the `sub_issues` list the worker emits.
- **Child type.** Optional `child_type:` on the decompose rule names the type for spawned children; defaults to `root_type`.
- **`then:`.** Optional. Where the parent transitions after creating children. If omitted, parent blocks until every child reaches `done` (cascading unblock).
- **`depends_on`.** A list of issue ids on a child's record. The child waits to start until each named predecessor reaches `done`. Sibling children without dependencies run in parallel up to `max_workers`.

## Auto-populated fields

The orchestrator sets these on the issue at runtime. Declare them in `fields:` only so prompts can reference them via Jinja:

- **`base_branch`.** The global `base_branch` config value, injected as `{{ issue.base_branch }}`.
- **`failure_context`.** Error message from the last worker failure (or the message attached to a `failed` target transition). Read in retry prompts so the next attempt sees what broke.

## Run lifecycle states

A run (the active execution of one root issue's workflow) has a status:

| Status | Meaning |
|---|---|
| `RUNNING` | At least one worker is active or about to be. |
| `COMPLETED` | The root issue reached `done`. |
| `FAILED` | A worker exceeded `max_worker_retries`, or another unrecoverable error. `orca resume` may pick it back up. |
| `INTERRUPTED` | Daemon was stopped/restarted mid-run. `orca resume` continues. |
| `STOPPED` | User stopped the run via `orca stop`. Resume or drop. |

Worker activity is reported separately: `worker_active: bool` indicates whether a worker tmux session is currently alive for any issue in the run.

## Common abbreviations / Jinja conventions

- **`{{ issue.fields.X }}`** — user-defined or auto-populated field `X` on the current issue.
- **`{{ result_format | tojson(indent=2) }}`** — pretty-prints the state's validation schema. Use this only when explaining the schema; it is not a valid result file.
- **`{{ result_example | tojson(indent=2) }}`** — pretty-prints a concrete example result for the current state. Use this in the output contract so the worker copies a valid shape.
- **`{{ result_path }}`** — absolute path where the worker writes its result file. The orchestrator polls for this file and terminates the session ~30 seconds after it appears. Don't perform work *after* the result write.
- **`{{ issue.event_log }}`** — chronological list of events on this issue. Useful in retry prompts to see what the previous attempt did.
- **`{{ run.* }}`** — see [`orca-prompt-create.md`](../orca-prompt-create.md) Step 2 for the full table.

## Where things live

- `.orca/{flow}.yml` — workflow config.
- `.orca/prompts/{state}.md` — one prompt template per active state.
- `.orca/playbooks/` — bundled playbooks (created by `orca init`; this file lives here in user projects).
- `.orca-state/` — runtime data, worker logs, worktrees. Gitignored.
