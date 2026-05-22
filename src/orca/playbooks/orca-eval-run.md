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

Treat the parsed `state_ref` as the source of truth for fixture bytes. The
default is `orca-eval-state/<eval>` with author worktree
`.orca-state/eval-states/<eval>/`, but evals may share or retarget state refs.
Do not assume the eval name and fixture branch name match.

### Step 1.3 - Optional explanation page

If the user wants a visual/plain-language explanation, invoke
[`orca-workflow-explain.md`](orca-workflow-explain.md) with the eval name. The
eval's `.orca/evals/<eval>/eval-flow.yml` is the workflow being explained, not
the production flow.

### Step 1.4 - Ask about input modifications

Conversationally:

> "Do you want to modify the input before we run? You can tweak the scenario
> in `.orca/evals/<eval>/input.md` or the fixture bytes on the state branch
> declared by `state_ref`."

If **no**, skip to Phase 2.

### Step 1.5 - Discuss + edit (if modifying)

Hold a free-form conversation with the user about what to change. Use your
file-editing tools to:

- Modify `.orca/evals/<eval>/input.md` for scenario text or frontmatter
  changes (`state_ref:` etc.).
- Modify `.orca/evals/<eval>/assertions.md` if the expected behavior changed.
- For state-branch bytes, walk the user through committing into the persistent
  author worktree for the parsed `state_ref` per
  [`orca-eval-create.md`](orca-eval-create.md) Step 6. If `state_ref` is
  `orca-eval-state/<eval>`, that is normally `.orca-state/eval-states/<eval>/`.
  If `state_ref` points elsewhere, locate or create the matching author
  worktree first; do not edit `.orca-state/eval-states/<eval>/` just because
  it exists.

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

The eval-flow's `review` state emits a HITL form when the eval finishes.
Phase 3 surfaces that form to the user and acts on their submission.

### Step 3.0 - Detect the review state (legacy fallback)

Inspect the run state JSON or `orca_get_run` output:

```
.orca-state/runs/orca-eval-run-<eval-name>/eval-flow/state.json
```

- If the run paused at `state: review` with `pending_form != null`, follow
  Steps 3.1 → 3.5 below (form-driven path).
- If the run transitioned straight from `assert` to `done` (no `review`
  state in the eval-flow.yml), the eval was scaffolded before this feature
  shipped. Skip to the **Legacy fallback** section at the bottom of Phase 3
  and walk through the conversational Q&A instead. Mention to the user
  that adding a `review` state to their `eval-flow.yml` gives them the
  web review UI on the next run (template lives in
  `src/orca/cli/eval_cmd.py:_SKELETON_EVAL_FLOW`).

### Step 3.1 - Surface the form URL

When the run pauses with `state: review` and `outcome: waiting`, the
form is reachable at:

```
http://localhost:<port>/forms/<run_id>/<issue_id>
```

`<port>` defaults to 7891 (or whatever the daemon picked — check the
daemon log). `<run_id>` and `<issue_id>` are visible in `orca_get_run`
output; the issue id for the root issue is typically the eval's slug.

Open the URL in the user's browser (`open <url>` on macOS) and tell them
the run is paused until they submit or skip the form. Do not poll
aggressively — the worker is suspended; nothing changes until submission.

### Step 3.2 - Wait for submission

Poll `orca_get_run` every ~30s. The run resumes automatically when the
user submits. The review state's result then lives at:

```
.orca-state/runs/orca-eval-run-<eval-name>/eval-flow/state-results/review.json
```

Shape:

```json
{
  "outcome": "reviewed",
  "comments": [
    "src/foo.ts:42 prefer renaming `x`",
    "src/foo.ts:91 this branch needs a unit test"
  ]
}
```

If `outcome` is `skipped` (no comments left, or the user clicked Skip),
end Phase 3 and report the eval result without applying any edits.

The form no longer has action checkboxes. The user's comments — both
WHAT they want changed and (often) WHERE — are the entire signal.

### Step 3.3 - Propose updates from comments, step-by-step

Phase 3 from this point is conversational, not form-driven. Your job is
to translate each comment into a concrete prompt or assertion edit and
propose it one at a time.

For each comment, decide which axis it points at:

| Comment subject | Likely fix |
|---|---|
| A line in a changed file (the worker's output) | A prompt edit in `.orca/prompts/<state>.md` — change the instruction the worker followed. |
| A criterion's assertion text (the spec) | An assertions edit in `.orca/evals/<eval>/assertions.md`. |
| An ambiguity in the report.md outcome | Usually an assertions tightening (same as above). |

Then walk one proposal at a time:

> "Comment on `src/foo.ts:42` — 'prefer renaming x'. I read this as a
> prompt-side fix on `.orca/prompts/<state>.md` — specifically: add a
> rule that variable names match the existing module style. Apply?"

On yes, run [`orca-prompt-create.md`](orca-prompt-create.md) Update
mode (for prompts) or edit `assertions.md` directly. On no, move to the
next comment. Track every file you edit so you can offer a commit at
the end.

Do **not** ask about `input.md` updates or about committing as a yes/no
gesture. Those used to be form checkboxes and were removed because:

- `input.md` changes are rare; if a comment really points at the
  scenario seed, raise it conversationally — it's a discussion, not a
  checkbox.
- Commits should be explicit, never bundled into a "yes I agreed with
  the changes" signal. Offer Step 3.4 only after the user has seen all
  the edits you applied.

### Step 3.4 - Commit (only if the user explicitly asks)

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

If the state branch changed, it already has its own commit on the parsed
`state_ref`; mention that it must be pushed alongside the main repo
commit when sharing the eval.

### Step 3.5 - Restart?

Conversationally:

> "Want to run another iteration?"

If yes, loop back to Phase 1 with the same eval pre-filled. If no,
summarize the run outcome, edits applied, commits made or skipped, and
remaining risks.

### Legacy fallback (for evals without a `review` state)

If Step 3.0 routed here, walk the user through the same review
conversationally:

1. Read `report.md` and summarize the outcome, the failed/inconclusive
   criteria, and the evidence the assert worker gave.
2. Inspect the eval worktree for evidence (read-only):

   ```
   git -C .orca-state/worktrees/orca-eval-run-<eval-name> status --short
   git -C .orca-state/worktrees/orca-eval-run-<eval-name> log --oneline --decorate --max-count=20
   ```

3. Use the same comment-driven proposal walk from Step 3.3 above —
   except the "comments" here come from the conversational summary in
   step 1, not from a submitted form.
4. Commit per Step 3.4 if the user asks.
5. Ask about restart per Step 3.5.

This fallback exists for backward compatibility with evals scaffolded
before the review state shipped. The form path is the default for any
freshly-scaffolded or migrated eval.

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
