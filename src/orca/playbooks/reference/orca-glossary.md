# Orca Glossary

One-line definitions for terms that recur across the playbooks. Use this as a tiebreaker when one playbook's wording disagrees with another's — the definition here is authoritative.

## Workflow shape

- **Workflow.** A `.orca/{flow}.yml` file plus its prompt templates. Selected via `orca run -w <flow>`; `default.yml` is the default.
- **Type.** One self-contained state machine inside a workflow (e.g. `epic`, `task`). Each type has its own `fields`, `initial`, and `states`; the top-level `root_type` names which type root issues start as. Legacy single-type configs are auto-wrapped as type `default`.
- **State.** A named position in a type's state machine. Has a `worker` (active) or doesn't (passive).
- **Active state.** Has a `worker:` block. The worker runs, produces a result, and the result's outcome routes via `on:`.
- **Passive state.** Has no `worker:` and no `on:`. Issue parks here until a manual `AdvanceEvent` from the TUI/API surface. Used for human gates.
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
| `failed` | built-in target (control directive) | Not a final resting state. Routing `on: { irrecoverable: failed }` increments `failure_count` and the engine retries the same state up to `max_worker_retries` or surfaces a stuck issue. The issue does not move into `failed` — it stays where it is with a bumped counter. |
| `waiting` | built-in outcome | Emitted by the worker (`{"outcome": "waiting", "reason": "..."}`) to pause for human input. No `on:` rule needed; do not declare in `values:`. Pauses the inactivity timer; resumes when unblocked via `orca unblock`. |

**`failed` as an outcome value is not the same thing as the built-in `failed` target.** You may declare `values: [applied, failed]` and route `failed: implementing` — that's a regular user-defined outcome. What matters is the right-hand side of the `on:` rule.

## Bounds and timers

| Name | Scope | Counts | Recommended | Why it exists |
|---|---|---|---|---|
| `max_hops` | run limit | *Every* state transition per issue | 10–20 | Bounds long pipelines and `blocked` self-loops. Current workflow YAML does not set this; `orca run` defaults to 10 and `--max-hops` overrides it. |
| `max_worker_retries` | run limit | Worker *failures* (crashes, timeouts, `failed` target) per issue in the same state | 3–5 | Bounds retry loops from a state crashing the worker. Does not count `blocked` results. Current workflow YAML does not set this; `orca run` defaults to 3 and `--max-retries` overrides it. |
| `max_workers` | per (type, state) | Concurrent workers running in this state | `1` on merge/apply/deploy; omit for parallel-safe work | Serializes shared-resource writes. |
| `timeout` | per worker | Seconds without progress when `inactivity_timeout` is absent | bound to worst case | Compatibility fallback for `inactivity_timeout`; not currently a hard wall-clock cap. |
| `inactivity_timeout` | per worker | Seconds without progress | 300 default | Kills wedged workers. **Paused while the worker's outcome is `waiting`.** |

## Decomposition

- **Decompose action.** An `on:` rule with `{ action: decompose, ... }`. Spawns child issues from the `sub_issues` list the worker emits.
- **Child type.** `child_type:` on the decompose rule names the type for spawned children. Typed configs should set it unless every emitted child supplies its own `type`; legacy single-type configs default to `default`.
- **`then:`.** Optional. Where the parent transitions after creating children. If omitted, parent blocks until every child reaches `done` (cascading unblock). Use `then:` only for deliberate fire-and-forget decomposition; if the root issue reaches `done`, the run loop terminates.
- **`depends_on`.** In a decomposer's `sub_issues` output, a list of sibling child `key` values. The engine resolves those keys to real issue ids. In rendered prompts for already-created issues, `{{ issue.depends_on }}` contains the resolved issue ids.

## Runtime-provided values

The orchestrator adds these to prompt context at runtime:

- **`base_branch`.** The live branch a worker should treat as its base: the run branch/run label for root issues, or the parent issue's branch for child issues. Access it as `{{ issue.base_branch }}`. The top-level config `base_branch` records branch intent, but the current daemon-backed `orca run` path does not use it to cut a root run branch.
- **`failure_context`.** Error message from the last worker failure (or the message attached to a `failed` target transition). Access it as `{{ issue.fields.failure_context }}`. Declare it in the issue type's `fields:` block so the reducer can store it and retry prompts can read it.

## Run lifecycle states

A run (the active execution of one root issue's workflow) has a status:

| Status | Meaning |
|---|---|
| `running` | At least one worker is active or about to be. |
| `completed` | The root issue reached `done`. |
| `failed` | A worker exceeded `max_worker_retries`, or another unrecoverable error. `orca resume` may pick it back up. |
| `interrupted` | Daemon was stopped/restarted mid-run. `orca resume` continues. |
| `stopped` | User stopped the run via `orca stop`. Resume or drop. |

Worker activity is reported separately on each issue:

- **`worker_active: bool`** — a worker tmux session is alive for this issue. **Does NOT mean "currently making progress"** — a worker that has emitted `outcome: waiting` and is parked awaiting HITL input still has `worker_active: true` (the session is open, just blocked). Treat this as "a session exists," not "work is happening." (gh#16)

To disambiguate "working" vs "waiting" vs "idle," combine signals:

| `worker_active` | `pending_form` | Last `worker_*` event | Meaning |
|---|---|---|---|
| `true` | `null` | `worker_dispatched` / `worker_progress` | **Working** — actively executing. |
| `true` | non-null | `worker_waiting` | **Waiting (form)** — HITL form pending at `/forms/<runId>/<issueId>`. |
| `true` | `null` | `worker_waiting` not yet followed by `worker_resumed` | **Waiting (text)** — `reason` carries the blocker; resume via `orca unblock`. |
| `false` | `null` | any | **Idle / between states** — either between dispatches, or the run reached a terminal state. |

For programmatic polling: `runs[*].waiting_issues` in the `/api/runs` payload aggregates the waiting cases above so a caller doesn't need to walk event logs themselves. `orca runs --waiting` filters the listing to just runs with at least one waiting issue.

## Common abbreviations / Jinja conventions

- **`{{ issue.fields.X }}`** — schema-declared field `X` on the current issue. Worker result keys are only carried forward into `issue.fields` when `X` is declared in that issue type's `fields:` block.
- **`{{ result_format | tojson(indent=2) }}`** — pretty-prints the state's validation schema. Use this only when explaining the schema; it is not a valid result file.
- **`{{ result_example | tojson(indent=2) }}`** — pretty-prints a concrete example result for the current state. Use this in the output contract so the worker copies a valid shape.
- **`{{ result_path }}`** — absolute path where the worker writes its result file. The orchestrator polls for this file and terminates the session ~30 seconds after it appears. Don't perform work *after* the result write.
- **`{{ issue.event_log }}`** — chronological list of events on this issue. Useful in retry prompts to see what the previous attempt did.
- **`{{ run.* }}`** — see [`orca-prompt-create.md`](../orca-prompt-create.md) Step 2 for the full table.

## Where things live

- `.orca/{flow}.yml` — workflow config.
- `.orca/prompts/{state}.md` — common prompt-template path for active states. The source of truth is each state's `worker.prompt`; typed workflows may use more specific filenames when state names repeat across types.
- `.orca-state/` — runtime data, worker logs, and run worktrees. Gitignored.
- Playbooks (the doc you're reading) ship inside the installed orca package and are served on demand via the `orca_get_playbook` / `orca_list_playbooks` MCP tools — there is no per-project `.orca/playbooks/` directory.
