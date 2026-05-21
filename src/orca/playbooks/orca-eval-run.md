# Playbook: Run an Orca Eval, End-to-End

Drive a full iteration cycle on an existing orca eval using the implemented
CLI/daemon surfaces:

1. **Setup** - pick the eval, understand the slice, optionally tweak
   `input.md` or the state branch.
2. **Run** - execute `orca eval <name>` and supervise the resulting run.
3. **Review & act** - read `report.md`, inspect the eval run worktree, apply
   chosen prompt/assertion/scenario edits, optionally commit, then ask whether
   to iterate again.

Audience: a smart non-engineer who is iterating on prompts and wants a tight
feedback loop. Keep decisions conversational; do not invent a web review flow
unless the repo actually defines one.

## Required reading (you, the agent - not the user)

- [`orca-eval-create.md`](orca-eval-create.md) - how evals are scaffolded;
  what `input.md`, `assertions.md`, the `state branch`, and the author
  worktree at `.orca-state/eval-states/<eval>/` are.
- [`orca-workflow-explain.md`](orca-workflow-explain.md) - optional
  explanation-page generation for the eval workflow.
- [`reference/orca-config-reference.md`](reference/orca-config-reference.md) -
  workflow YAML, `waiting` outcome, run context variables.

## When to use this

- The user asks: "run an eval", "iterate on the X eval", "let's improve
  X", "test my prompts with the X eval", "запусти тест X и давай разберём".
- The user invokes this playbook by name.

## Inputs

- **`eval`** (optional) - the eval directory name. If missing, ask; if there
  are no evals at all, stop and point at [`orca-eval-create.md`](orca-eval-create.md).
- **`lang`** (optional, default `en`) - ISO 639-1 code used only if you
  generate the optional explanation page.

Track every file or branch you mutate. The commit step needs this context.

---

## Phase 1 - Setup

### Step 1.1 - Confirm the eval

If the user named an eval, validate that `.orca/evals/<eval>/` exists and
contains `eval-flow.yml`, `input.md`, and `assertions.md`. If not, list
available evals (`ls .orca/evals/`) and ask. If there are no evals, stop and
point them at `orca-eval-create.md`.

### Step 1.2 - Read the eval shape

Read:

- `.orca/evals/<eval>/eval-flow.yml`
- `.orca/evals/<eval>/input.md`
- `.orca/evals/<eval>/assertions.md`

Identify the body state(s), the `assert` state, and the `state_ref:` value in
`input.md` frontmatter. If `state_ref:` is missing or still `TODO_STATE_REF`,
stop: `orca eval <eval>` will refuse to start.

### Step 1.3 - Optional explanation page

If the user wants a visual/plain-language explanation, invoke
[`orca-workflow-explain.md`](orca-workflow-explain.md) with the eval name. The
eval's `.orca/evals/<eval>/eval-flow.yml` is the workflow being explained, not
the production flow.

### Step 1.4 - Ask about input modifications

Conversationally:

> "Do you want to modify the input before we run? You can tweak the scenario
> in `.orca/evals/<eval>/input.md` or the fixture bytes on the state branch
> via `.orca-state/eval-states/<eval>/`."

If **no**, skip to Phase 2.

### Step 1.5 - Discuss + edit (if modifying)

Hold a free-form conversation with the user about what to change. Use your
file-editing tools to:

- Modify `.orca/evals/<eval>/input.md` for scenario text or frontmatter
  changes (`state_ref:` etc.).
- Modify `.orca/evals/<eval>/assertions.md` if the expected behavior changed.
- For state-branch bytes, walk the user through committing into the persistent
  author worktree at `.orca-state/eval-states/<eval>/` per
  [`orca-eval-create.md`](orca-eval-create.md) Step 6.

Track every file you touched and whether the state branch gained commits.
When the user signals "done modifying", continue to Phase 2.

---

## Phase 2 - Run

### Step 2.1 - Confirm

Conversationally:

> "Ready to run the eval?"

If no, stop.

### Step 2.2 - Run the eval

```
orca eval <eval-name>
```

The positional argument is the eval directory name under `.orca/evals/`. The
command submits a daemon run with eval-fast bounds (`max_hops=10`,
`max_retries=2`) and prints the run id. It is fire-and-forget; it does not
wait for completion.

Expected default run id:

```
orca-eval-run-<eval-name>:eval-flow
```

Capture the printed `run_id`. If start fails, surface the daemon error; do not
auto-retry.

### Step 2.3 - Supervise to completion

Poll the run using the daemon/MCP tools when available:

```
orca_get_run(root="<repo>", run_id="<run_id>", compact=true)
orca_get_worker_log(root="<repo>", run_id="<run_id>", issue_id="<issue>", tail=80)
```

Shell fallback:

```
orca runs
orca logs <run_id> [issue_id] --tail 80
```

Treat `waiting` as a human handoff, not a failure. Surface the worker's request
and unblock only after the user replies. Treat `failed` as a run failure and
show the report/log context; do not auto-retry evals unless the user asks.

### Step 2.4 - Locate the run output

For the default eval submission, run output lives at:

```
.orca-state/runs/orca-eval-run-<eval-name>/eval-flow/
```

Confirm `report.md` exists there after the `assert` state completes:

```
.orca-state/runs/orca-eval-run-<eval-name>/eval-flow/report.md
```

If the user passed a custom run id/branch through a lower-level API, derive the
path from the run summary's `branch` and `workflow` fields, or inspect
`.orca-state/runs/`.

---

## Phase 3 - Review & Act

### Step 3.1 - Read the report

Read `report.md` and summarize:

- overall result (`passed`, `failed`, or `inconclusive`)
- each failed or inconclusive criterion id
- the evidence/detail the assert worker gave

Do not edit yet. First agree on the attribution.

### Step 3.2 - Inspect the eval run worktree

The eval run worktree normally lives at:

```
.orca-state/worktrees/orca-eval-run-<eval-name>/
```

Inspect it only for evidence:

```
git -C .orca-state/worktrees/orca-eval-run-<eval-name> status --short
git -C .orca-state/worktrees/orca-eval-run-<eval-name> log --oneline --decorate --max-count=20
```

Those files are run artifacts. Do not stage or commit `.orca-state/**` into the
main repo.

### Step 3.3 - Attribute failures before editing

Use this taxonomy:

| Failure mode | Symptom | Fix |
|---|---|---|
| Prompt | Assertion is clear; scenario is valid; worker output missed it. | Update the production prompt through `orca-prompt-create` Update mode. |
| Assertion | Criterion is ambiguous, subjective, or references unavailable evidence. | Edit `.orca/evals/<eval>/assertions.md`. |
| Scenario | `input.md` or the state branch does not actually exercise the behavior. | Edit `input.md` or commit new fixture bytes on `orca-eval-state/<eval>`. |
| `result_format` | The criterion needs evidence the body state never emits. | Coordinate a production workflow `result_format` change plus prompt update. |
| Flow | The eval slice entry expects fields not seeded by `input.md`. | Add the fields to `input.md` frontmatter or fix the upstream production state. |

Ask the user which fixes they want to apply if the choice is not mechanical.

### Step 3.4 - Apply chosen actions

Apply only the chosen edits:

- **Update prompts:** edit `.orca/prompts/<state>.md` via
  [`orca-prompt-create.md`](orca-prompt-create.md) Update mode. Track paths.
- **Update assertions:** edit `.orca/evals/<eval>/assertions.md`. Track path.
- **Update input:** edit `.orca/evals/<eval>/input.md`. Track path.
- **Update state branch:** edit and commit inside
  `.orca-state/eval-states/<eval>/`; track the branch commit separately.
- **Update workflow/result_format:** route through
  [`orca-workflow-review.md`](orca-workflow-review.md) or
  [`orca-workflow-create.md`](orca-workflow-create.md), because schema and
  prompt contract must change together.

Never edit the eval run worktree under `.orca-state/worktrees/...` as the fix;
it will be discarded on the next eval run.

### Step 3.5 - Commit (only if requested)

The commit step is explicit and defensive.

1. Run `git status --porcelain` from the repo root.
2. Build the allow-list - only paths matching one of:
   - `.orca/evals/<eval>/input.md`
   - `.orca/evals/<eval>/assertions.md`
   - `.orca/evals/<eval>/eval-flow.yml`
   - `.orca/prompts/*.md`
   - production workflow YAML files explicitly edited in this session
   - any other path the user explicitly mentioned editing during discussion
3. Hard exclude `.orca-state/**`.
4. Show the exact files and proposed commit message.
5. Get final yes/no confirmation.
6. On yes: `git add <listed-paths>` with specific paths only, then
   `git commit -m "<message>"`.

If the state branch changed, it already has its own commit in
`orca-eval-state/<eval>`; mention that it must be pushed alongside the main
repo commit when sharing the eval.

### Step 3.6 - Restart?

Conversationally:

> "Want to run another iteration?"

If yes, loop back to Phase 1 with the same eval pre-filled. If no, summarize
the run outcome, edits applied, commits made or skipped, and remaining risks.

---

## Pitfall checks

- **Do not use `git add -A` or `git add .`** in the commit step. Specific
  paths only.
- **Do not commit `.orca-state/**`** from the main repo. It contains runtime
  state, run worktrees, logs, and cached reports.
- **Do not rely on `.orca-state/eval-states/<eval>/<run_id>/`** for run
  output. `.orca-state/eval-states/<eval>/` is the persistent author worktree
  for the fixture branch; run output lives under `.orca-state/runs/...`.
- **Identifiers stay in English:** eval directory names, state names, field
  names, criterion names. Only conversational prose is localized.
- **Track edits:** every file or state-branch commit you create must be
  remembered for commit/push reporting.
- **Cancel/no action means stop:** if the user does not want changes after the
  report, do not apply fixes.
- **First run may fail because the scaffold is not runnable:** structural smoke
  evals created by workflow setup may still have stub `input.md` and an empty
  state branch. Fill the scenario and fixture before treating failures as prompt
  regressions.
