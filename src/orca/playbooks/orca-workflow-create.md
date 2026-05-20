# Playbook: Create an Orca Workflow (Interactive)

Build a correct, unambiguous orca workflow — `.orca/{flow}.yml` plus its prompt templates — through an interactive, multi-step dialogue with the user. The final artifact must validate against the orca config schema and pass the audit checklist.

This playbook is **conversational**. Walk the user through each step. Do not silently make decisions that change the shape of the state machine — if something is ambiguous, ask.

## Prerequisites

- Orca CLI installed ([orca-install.md](orca-install.md)).
- Working directory is a git repo.
- `.orca/` exists, or you're about to create it (`mkdir -p .orca/prompts`).

## Required reading (you, the agent — not the user)

Before you ask the user anything, read these:

- [`reference/prompt-design.md`](reference/prompt-design.md) — the assertions-first paradigm; the foundational discipline for every prompt this workflow will contain
- [`orca-glossary.md`](reference/orca-glossary.md) — definitions for terms used below (outcome vs target, `failed` ambiguity, bounds and timers)
- [`orca-config-reference.md`](reference/orca-config-reference.md) — full schema, validation rules, recommended defaults
- [`orca-workflow-patterns.md`](reference/orca-workflow-patterns.md) — single-type vs multi-type, decomposition, parallel fan-out, HITL
- [`orca-prompt-create.md`](orca-prompt-create.md) — prompt template structure, Jinja conventions, output contracts
- [`orca-test-create.md`](orca-test-create.md) — the per-state test scaffold you'll run in Step 8
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
- **Failure-safe outcomes** (`blocked` / `waiting` — every active state needs at least one escape hatch beyond success)

Decision points to make explicit with the user:

| Decision | Question to ask |
|---|---|
| Single-type vs multi-type | Does this workflow decompose one big task into many smaller ones (epic → tasks)? If yes → multi-type. Otherwise single-type. |
| Where to decompose | Early decomposition = more parallelism but less control. Late = vice versa. |
| `max_workers` per state | Merge/apply/deploy states should be `1`. Independent work states can omit it (unbounded). |
| `max_hops`, `max_worker_retries` | Use the recommended defaults in [`orca-config-reference.md`](reference/orca-config-reference.md) (typically `max_hops: 10–20`, `max_worker_retries: 3–5`); raise only if the user has a reason. |
| Branch strategy | Does each issue get its own feature branch (`branch_prefix`), or does everything happen on one branch? |
| Human-in-the-loop | Will any state need the `waiting` outcome (i.e., pause for human input)? Where? |

Get the user to sign off on the diagram. **Do not write a single line of YAML until they do.**

### Step 3 — Define the issue schema

Ask: what fields does an issue carry through the workflow?

For each field:
- Name (snake_case)
- Type — only `string` and `enum` are supported for issue fields (see [`orca-config-reference.md`](reference/orca-config-reference.md)). For collections of child issues, use `sub_issues` with `items: "$issue"` — that's part of `result_format`, not the issue schema.
- Required at start, or filled in by an earlier state?
- One-line description (this shows up in the worker's prompt)

Common fields: `title`, `description`, `acceptance_criteria`, `scope_boundary`, `summary`. Don't add `branch` — orca tracks git branches at the run level (`run.branch`) and auto-injects `issue.base_branch` for workers; user-defined fields shouldn't duplicate that. Don't invent fields the workflow doesn't actually use.

Show the user the field list and confirm.

### Step 4 — Draft `.orca/{flow}.yml`

Write the YAML. Use the snippets in [`orca-workflow-patterns.md`](reference/orca-workflow-patterns.md) as building blocks. Validate against every rule in [`orca-config-reference.md`](reference/orca-config-reference.md) as you write:

- `initial` state exists in `states:`
- Every `on:` target is either a real state in `states:` or a built-in target (`done`, `failed`). Note: `waiting` is a built-in *outcome*, not a transition target — it has no `on:` rule.
- Every state's `result_format.outcome.values` covers every key in its `on:` map (and vice versa). `on:` keys are outcome values; the `decompose` action is what runs for that outcome — not a separate routing concept.
- Every active state has `worker.prompt` pointing at a file under `prompts/`
- Field references in prompts (`{{ issue.fields.X }}`) match the issue schema

Filename: `.orca/{flow}.yml` (snake_case or hyphen-case; commonly `develop.yml`, `review.yml`, `triage.yml`).

Show the file to the user and ask: *"Does this match what you described?"* Don't move on until they confirm.

### Step 5 — Write prompt templates

For each active state, create `.orca/prompts/{state}.md`. Follow [`orca-prompt-create.md`](orca-prompt-create.md) exactly:

- Lead with role and task context (`{{ issue.fields.title }}`, `{{ issue.fields.description }}`, etc.)
- Spell out scope boundaries — what the worker is **not** allowed to do
- List concrete steps (numbered)
- Include verification (run tests, type-check, lint — match the project's actual conventions)
- Output contract at the bottom:
  ````
  Write your result to `{{ result_path }}`:

  ```json
  {{ result_example | tojson(indent=2) }}
  ```
  ````

For multi-state workflows, prompts should reference what the previous state produced (e.g., a `plan` field set by a planning state).

Show each prompt to the user. Adjust per their feedback before writing the next one.

### Step 6 — Validate

Run through the three-layer audit from [`orca-workflow-review.md`](orca-workflow-review.md):

1. **Structural** — no broken transitions, no unreachable states, all outcomes routed, every active state has an escape hatch.
2. **Efficiency** — `max_workers` correct on merge/apply states, no unnecessary serialization, decomposition placed sensibly.
3. **Prompt quality** — each prompt has a clear role, clear scope, concrete steps, verification, and output contract. Field references resolve.

Report findings as **Critical / Important / Minor**. Fix critical and important issues before proceeding. Confirm minor issues with the user — they may be intentional.

### Step 7 — Offer a test run

Once the workflow validates:

> "Workflow is ready. Want me to write a small `task.md` and run it as a smoke test?"

If yes, follow [orca-workflow-run.md](orca-workflow-run.md) with a tiny test task scoped to surface workflow bugs (not production work). If the test surfaces issues, loop back to step 4 or 5 — fix the config/prompts and rerun.

### Step 8 — Create per-state tests (required ask)

Before declaring the workflow done, you **must** ask the user about creating tests for each active state. This ask is non-skippable — even if the user later declines, the question must be put in front of them. Ask verbatim:

> "I'll create one orca test per active state, following the assertions-first paradigm in [`reference/prompt-design.md`](reference/prompt-design.md). Each test is a single-state slice that grades the prompt against 3–5 objective criteria, so future prompt edits have something to validate against. Should I create them now?"

If the user says **yes**:

1. **Pick the scope.** Ask which states to cover. Default: every active state. For large workflows (5+ states), suggest starting with the highest-risk 1–2 (typically planning and implementing equivalents); the user can add more later.
2. **Per state, follow [`orca-test-create.md`](orca-test-create.md) end-to-end.** Each test is a `setup -> {state} -> assert` single-state slice. The scenario, `assertions.md`, and `result_format` should already have been drafted as part of Step 5 (per [`orca-prompt-create.md`](orca-prompt-create.md) Step 1) — re-use those artefacts rather than re-drafting from scratch.
3. **Run each test once after scaffolding.** Read the report. Iterate per [`reference/prompt-design.md`](reference/prompt-design.md) §4 — walk the failure-attribution taxonomy and apply the minimal edit. Continue until criteria pass, or the user accepts the remaining gaps.
4. **Commit each test directory** under `.orca/tests/<scenario>/` only after the first run completes (passing or with user-accepted failures).

If the user says **no**:

- Note the decision in the final report. The workflow ships without a regression-catching surface; surface this risk plainly. Quote the user's reason if they gave one, so the next agent (or future-you) knows whether to re-ask later.
- Optionally, offer the lighter alternative: a single end-to-end smoke test (`setup -> [every state] -> assert`) instead of per-state tests. Re-ask once.

A workflow without tests rots silently — the first prompt edit may break things invisibly, and there's no signal to catch it. This is why the *ask* is non-skippable, even though the *answer* can be "skip".

### Step 9 — Offer a convenience wrapper skill (optional)

A wrapper skill is a thin SKILL.md scaffolded into the user's project so teammates can invoke this workflow with natural language — "fix this bug", "ship a feature" — without knowing Orca exists. The wrapper composes `task.md` from the user's ask and starts the run via `orca_start_run`. It is **fire-and-forget**: it kicks the run off and exits. Supervision stays in [`orca-workflow-run.md`](orca-workflow-run.md).

Ask the user once, skippably:

> "I can also create a convenience wrapper skill so anyone on the team can invoke this workflow by saying something like *'<example trigger phrase>'* — without knowing Orca exists. Want one? (skippable)"

Pick the example phrase from Step 1's "what does it do" answer.

If the user says **yes**, follow [`reference/wrapper-skill-template.md`](reference/wrapper-skill-template.md) end-to-end. The shape:

1. **Confirm the name.** Default = the workflow's filename without `.yml`. The user may override.
2. **Author the `description:` line.** This is the most important step — it's the *only* thing the host CLI uses to decide whether to route to the wrapper. Generate a description per the rules in the template doc (lead with `"Use when..."`, enumerate ≥3 concrete trigger phrases, name the action, ≤80 words, don't mention Orca). Show to the user and iterate until they confirm the phrasing matches how the team actually talks.
3. **Fill the template** with workflow name, issue-schema fields (from Step 3), and the confirmed description.
4. **Write both files** with identical content:
   - `.claude/skills/<name>/SKILL.md` (Claude Code)
   - `.agents/skills/<name>/SKILL.md` (Codex)
5. **Check `.gitignore`.** If `.claude/skills/` or `.agents/skills/` is ignored wholesale, surface it and offer to add an exception (`!.claude/skills/`). Don't silently un-ignore.
6. **Report.** Print both paths plus: *"Wrapper ready. Next session, anyone in either CLI can say `<example phrase>` to kick off a run. To supervise an in-flight run, ask me to babysit it."*

If the user says **no**, note it in the final report and move on.

## Anti-patterns to refuse (or push back on)

- **Declaring the workflow done without asking about tests.** Step 8's ask is non-skippable. The user may answer "no" — but they must be asked, and the answer recorded.
- **No escape hatch.** Every active state needs `blocked` or `waiting` in addition to success outcomes. Refuse to write a state that can only succeed.
- **Result format / prompt drift.** If you change `result_format`, update the prompt's output contract in the same edit. Never commit one without the other.
- **Hidden fan-out on a merge state.** A merge/apply state must have `max_workers: 1`. Surface this explicitly to the user.
- **Mystery field references.** If a prompt references `{{ issue.fields.X }}`, `X` must be in the issue schema (either declared at start or set by an upstream state's `result_format`).
- **Free-form outcomes.** Every value in `result_format.outcome.values` must appear in `on:` (or it's an unhandled terminal — confirm with the user).
- **Generating a wrapper skill with a generic description.** Skill routing is description-driven; the offer in Step 9 is wasted if the trigger phrases don't match how the team actually speaks. Walk the description-authoring step from [`reference/wrapper-skill-template.md`](reference/wrapper-skill-template.md) — don't shortcut it.

## Done

Report to the user:
- File paths written (`.orca/{flow}.yml`, `.orca/prompts/*.md`)
- The final state-machine diagram
- Whether a smoke run was performed and its outcome (Step 7)
- **Per-state tests** (Step 8): list of tests created with paths and pass/fail status, **or** "user declined" with the recorded reason
- **Wrapper skill** (Step 9): wrapper name plus both written paths (`.claude/skills/<name>/SKILL.md`, `.agents/skills/<name>/SKILL.md`), **or** "user declined"
- What to do next: either run a real task ([orca-workflow-run.md](orca-workflow-run.md)) or commit the workflow + test files
