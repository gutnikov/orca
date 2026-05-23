# Playbook: Create an Orca Workflow (Interactive)

Build a correct, unambiguous orca workflow — `.orca/{flow}.yml` plus its prompt templates — through an interactive, multi-step dialogue with the user. The final artifact must validate against the orca config schema and pass the audit checklist.

This playbook is **conversational**. Walk the user through each step. Do not silently make decisions that change the shape of the state machine — if something is ambiguous, ask.

## Prerequisites

- Orca CLI installed ([orca-install.md](orca-install.md)).
- Working directory is a git repo.
- `.orca/` exists, or you're about to create it (`mkdir -p .orca/prompts`).

## Required reading (you, the agent — not the user)

Before you ask the user anything, read these:

- [`orca-glossary.md`](reference/orca-glossary.md) — definitions for terms used below (outcome vs target, `failed` ambiguity, bounds and timers)
- [`orca-config-reference.md`](reference/orca-config-reference.md) — full schema, validation rules, recommended defaults
- [`orca-workflow-patterns.md`](reference/orca-workflow-patterns.md) — single-type vs multi-type, decomposition, parallel fan-out, HITL
- [`orca-prompt-create.md`](orca-prompt-create.md) — prompt template structure, Jinja conventions, output contracts
- [`orca-workflow-review.md`](orca-workflow-review.md) — what to verify at the end

For a complete worked example to mirror, fetch `examples/project/orca.yml` and `examples/project/prompts/` from the orca repo (https://github.com/gutnikov/orca/tree/main/examples/project). If you can't fetch, the patterns reference doc has compositional snippets covering every shape used in that example.

If you're tempted to skip these: don't. Workflow bugs are expensive to debug once a run is in flight, and most come from skipping the reference docs.

## Interactive process

Run the steps in order. After each step, **show your work to the user and get confirmation before moving on.** This is the whole point of the playbook — silent decisions produce ambiguous workflows.

### Step 1 — Understand the goal

Ask the user, in plain language:

1. What does the workflow do? (one sentence — e.g. "implement a feature from a task description", "review a PR", "triage incoming bugs")
2. What's the target project? (language, framework, test runner — affects worker prompts)
3. What does "done" look like? (a merged PR, a written report, a deployed change, a closed issue, …)
4. What's the input? (a task file with fields, a PR number, an issue id, a free-form description)

Echo your understanding back in 2–3 sentences and ask the user to confirm or correct.

### Step 2 — Sketch the state machine

Propose a state machine *before* writing YAML. Use a small text diagram, e.g.:

```
initial ──► planning ──► implementing ──► reviewing ──► done
                              │              │
                              └─► blocked    └─► implementing  (on revision_requested)
```

For each proposed state, name:
- **What the worker does** (one sentence)
- **What it outputs** (the `result_format` outcomes, in plain language)
- **Where each outcome routes**
- **Failure-safe outcomes** (a routable non-success outcome such as `blocked`, `conflict`, or `needs_rework`; `waiting` is only for live human input)

Decision points to make explicit with the user:

| Decision | Question to ask |
|---|---|
| Single-type vs multi-type | Does this workflow decompose one big task into many smaller ones (epic → tasks)? If yes → multi-type. Otherwise single-type. |
| Where to decompose | Early decomposition = more parallelism but less control. Late = vice versa. |
| `max_workers` per state | Merge/apply/deploy states should be `1`. Independent work states can omit it (unbounded). |
| `max_hops`, `max_worker_retries` | These are launch-time limits, not workflow YAML fields in the current engine. `orca run` defaults to 10 / 3; use `--max-hops` / `--max-retries` only if the user has a reason. |
| Branch strategy | The run branch/run label is chosen at `orca run` time (current git branch by default, or set via `-b/--branch`). In the current daemon-backed run path, `base_branch` / `--base` should not be relied on to create a new root branch. Child issue worktrees are based on their parent/root branch, so a custom `-b` should name an existing branch/ref when the workflow decomposes into children. There is no per-state "branch prefix" knob; check with the user whether child issues should land on separate branches (typical) or the root issue should do all work in the current checkout. |
| Human-in-the-loop | Will any state need the `waiting` outcome (i.e., pause for human input)? Where? |

Get the user to sign off on the diagram. **Do not write a single line of YAML until they do.**

### Step 3 — Define the issue schema(s)

Ask: what fields does an issue carry through the workflow?

For typed configs, define fields separately for each issue type. A field emitted by a `task` state does not automatically exist on `epic`, and vice versa. For each field:
- Name (snake_case)
- Type — only `string` and `enum` are supported for issue fields (see [`orca-config-reference.md`](reference/orca-config-reference.md)). For collections of child issues, use `sub_issues` with `items: "$issue"` — that's part of `result_format`, not the issue schema.
- Required at start, or filled in by an earlier state?
- One-line description (this shows up in the worker's prompt)

Common fields when relevant: `title`, `description`, `acceptance_criteria`, `scope_boundary`, `summary`. Don't add `branch` — orca tracks git branches at the run level (`run.branch`) and auto-injects `issue.base_branch` for workers; user-defined fields shouldn't duplicate that. Don't invent fields the workflow doesn't actually use.

Show the user the field list grouped by type and confirm.

### Step 4 — Draft `.orca/{flow}.yml`

Write the YAML. Use the snippets in [`orca-workflow-patterns.md`](reference/orca-workflow-patterns.md) as building blocks. Validate against every rule in [`orca-config-reference.md`](reference/orca-config-reference.md) as you write:

- `initial` state exists in `states:`
- Every `on:` target is either a real state in `states:` or a built-in target (`done`, `failed`). Note: `waiting` is a built-in *outcome*, not a transition target — it has no `on:` rule.
- Every key in an `on:` map is present in that state's `result_format.outcome.values`, and every non-`waiting` outcome the worker may emit has an `on:` route. `on:` keys are outcome values; the `decompose` action is what runs for that outcome — not a separate routing concept.
- Every active state has `worker.prompt` pointing at a file under `prompts/`, or a deliberately tiny inline prompt.
- Field references in prompts (`{{ issue.fields.X }}`) match the field schema for that state's issue type. If an upstream state emits `X` and a later prompt reads `{{ issue.fields.X }}`, `X` must also be declared in that later issue type's `fields:` block; the reducer only carries result keys that are declared fields.

Filename: `.orca/{flow}.yml` (snake_case or hyphen-case; commonly `develop.yml`, `review.yml`, `triage.yml`).

Show the file to the user and ask: *"Does this match what you described?"* Don't move on until they confirm.

### Step 5 — Write prompt templates

For each active state, create the prompt file referenced by that state's `worker.prompt` via [`orca-prompt-create.md`](orca-prompt-create.md). The common path is `.orca/prompts/{state}.md`, but typed workflows may need distinct filenames such as `.orca/prompts/task_implementing.md` when different types reuse the same state name. That playbook is a **pure procedure** — it consumes a state specification and emits a prompt. It does not interact with the user; the user-interaction layer is here in workflow-create.

For each active state, assemble a spec from what you already have:

- **Issue type and state name** (already in the YAML from Step 4)
- **One-sentence job** (derive from the state's purpose in Step 2)
- **`result_format`** (already in the YAML from Step 4 — the prompt-creator reads it directly)
- **Inputs** — which `issue.fields.*` and which upstream-state result fields the worker reads
- **Constraints** — branch behaviour, scope boundaries, no-touch rules
- **Verification** — concrete commands from the project's conventions (pytest / cargo test / npm test / etc.)

Pass that spec to `orca-prompt-create`. After it returns, show the prompt to the user and ask: *"Does this capture what `<state>` should do?"* If the user wants changes, re-invoke `orca-prompt-create` in Update mode with the specific instruction — do **not** edit the prompt directly here.

For multi-state workflows, each prompt's spec should reference what the previous state produced (e.g., a `plan` field set by a planning state). If the later prompt reads that value via `issue.fields.plan`, declare `plan` in the relevant type's `fields:` block as a carried field.

### Step 6 — Validate

Run through the three-layer audit from [`orca-workflow-review.md`](orca-workflow-review.md):

1. **Structural** — no broken transitions, no unreachable states, all outcomes routed, every active state has an escape hatch.
2. **Efficiency** — `max_workers` correct on merge/apply states, no unnecessary serialization, decomposition placed sensibly.
3. **Prompt quality** — each prompt has a clear role, clear scope, concrete steps, verification, and output contract. Field references resolve.

Report findings as **Critical / Important / Minor**. Fix critical and important issues before proceeding. Confirm minor issues with the user — they may be intentional.

### Step 7 — Offer an end-to-end smoke run

Once the workflow validates:

> "Workflow is ready. Want me to write a small `task.md` and kick off an end-to-end smoke run?"

This is an *optional* live run: a tiny task scoped to surface workflow bugs (not production work). The user may decline — but you must ask, and record their answer in the final report. If they accept, follow [orca-workflow-run.md](orca-workflow-run.md). If the run surfaces issues, loop back to step 4 or 5 — fix the config/prompts and rerun.

### Step 8 — Offer a convenience wrapper skill (optional)

A wrapper skill is a thin SKILL.md scaffolded into the user's project so teammates can invoke this workflow with natural language — "fix this bug", "ship a feature" — without knowing Orca exists. The wrapper composes `task.md` from the user's ask and starts the run via `orca_start_run`. It is **fire-and-forget**: it kicks the run off and exits. Supervision stays in [`orca-workflow-run.md`](orca-workflow-run.md).

Ask the user once, skippably:

> "I can also create a convenience wrapper skill so anyone on the team can invoke this workflow by saying something like *'<example trigger phrase>'* — without knowing Orca exists. Want one? (skippable)"

Pick the example phrase from Step 1's "what does it do" answer.

If the user says **yes**, follow [`reference/wrapper-skill-template.md`](reference/wrapper-skill-template.md) end-to-end. The shape:

1. **Confirm two names.**
   - **Wrapper name** — the SKILL.md directory name. Default = the workflow's filename without `.yml`. The user may override.
   - **Workflow file stem** — the workflow's YAML filename without `.yml`, set in Step 4 (e.g. `develop` for `.orca/develop.yml`). The user does *not* override this; it's whatever Step 4 produced. The template's `orca_start_run(...workflow="<workflow-file-stem>")` call binds to this, not to the wrapper name. They usually match — but if the user renamed the wrapper, they don't, and the wrapper would otherwise point at a non-existent workflow.
2. **Author the `description:` line.** This is the most important step — it's the *only* thing the host CLI uses to decide whether to route to the wrapper. Generate a description per the rules in the template doc (lead with `"Use when..."`, enumerate ≥3 concrete trigger phrases, name the action, ≤80 words, don't mention Orca). Show to the user and iterate until they confirm the phrasing matches how the team actually talks.
3. **Fill the template** with wrapper name, workflow file stem, issue-schema fields (from Step 3), and the confirmed description.
4. **Write both files** with identical content:
   - `.claude/skills/<wrapper-name>/SKILL.md` (Claude Code)
   - `.agents/skills/<wrapper-name>/SKILL.md` (Codex)
5. **Check `.gitignore`.** If `.claude/skills/` or `.agents/skills/` is ignored wholesale, surface it and offer to add parent-directory plus wrapper-directory exceptions (for example `.claude/`, `!.claude/skills/`, `!.claude/skills/<wrapper-name>/`, `!.claude/skills/<wrapper-name>/SKILL.md`). Don't silently un-ignore.
6. **Report.** Print both paths plus: *"Wrapper ready. Next session, anyone in either CLI can say `<example phrase>` to kick off a run. To supervise an in-flight run, ask me to babysit it."*

If the user says **no**, note it in the final report and move on.

## Anti-patterns to refuse (or push back on)

- **Closing out the workflow without acting on Step 7.** The end-to-end smoke run is an *ask*: the user may decline, but they must be asked, and their answer recorded.
- **No escape hatch.** Every active state needs a routable non-success outcome such as `blocked`, `conflict`, or `needs_rework` in addition to success outcomes. `waiting` is available for live human input, but it has no `on:` route and should not be the only way a state reports failure or defers work.
- **Result format / prompt drift.** If you change `result_format`, update the prompt's output contract in the same edit. Never commit one without the other.
- **Hidden fan-out on a merge state.** A merge/apply state must have `max_workers: 1`. Surface this explicitly to the user.
- **Mystery field references.** If a prompt references `{{ issue.fields.X }}`, `X` must be declared in that issue type's `fields:` block. If an upstream state's `result_format` emits `X`, declare `X` as a carried field too; otherwise the reducer drops it instead of making it available to later prompts.
- **Free-form outcomes.** Every value in `result_format.outcome.values` must appear in `on:` (or it's an unhandled terminal — confirm with the user).
- **Generating a wrapper skill with a generic description.** Skill routing is description-driven; the offer in Step 8 is wasted if the trigger phrases don't match how the team actually speaks. Walk the description-authoring step from [`reference/wrapper-skill-template.md`](reference/wrapper-skill-template.md) — don't shortcut it.

## Done

Report to the user:
- File paths written (`.orca/{flow}.yml`, `.orca/prompts/*.md`)
- The final state-machine diagram
- Whether an end-to-end smoke run was performed and its outcome (Step 7) — or "user declined" with the recorded reason
- **Wrapper skill** (Step 8): wrapper name plus both written paths (`.claude/skills/<name>/SKILL.md`, `.agents/skills/<name>/SKILL.md`), **or** "user declined"
- What to do next: either run a real task ([orca-workflow-run.md](orca-workflow-run.md)) or commit the workflow files
