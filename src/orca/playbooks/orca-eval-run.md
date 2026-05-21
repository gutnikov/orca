# Playbook: Run an Orca Eval, End-to-End

Drive a full iteration cycle on an existing orca eval:

1. **Setup** — pick the eval, see what its flow does, optionally tweak
   `input.md` or the state branch.
2. **Run** — execute the eval and wait for it to finish.
3. **Review & act** — open a polished web form with the assertion results,
   the worktree diff, and a multi-select picker. Apply whichever actions
   the user chose (update prompts, update assertions, commit), then ask
   whether to iterate again.

Audience: a smart non-engineer who is iterating on prompts and wants to
keep a tight feedback loop. The playbook does most things conversationally;
two moments are richer web UI surfaces (an explanation page, a review
form). Everything else is plain chat.

## Required reading (you, the agent — not the user)

- [`orca-eval-create.md`](orca-eval-create.md) — how evals are scaffolded;
  what `input.md`, `assertions.md`, the `state branch`, and the worktree at
  `.orca-state/eval-states/<eval>/` are.
- [`orca-workflow-explain.md`](orca-workflow-explain.md) — the explanation
  step in Phase 1 delegates to this playbook.
- [`reference/orca-config-reference.md`](reference/orca-config-reference.md)
  — workflow YAML, `waiting` outcome, form schemas.

## When to use this

- The user asks: "run an eval", "iterate on the X eval", "let's improve
  X", "test my prompts with the X eval", "запусти тест X и давай разберём".
- The user invokes this playbook by name.

## Inputs

- **`eval`** (optional) — the eval directory name. If missing, the playbook
  asks; if there are no evals at all, it stops and points at
  [`orca-eval-create.md`](orca-eval-create.md).
- **`lang`** (optional, default `en`) — ISO 639-1 code used for the
  explanation page in Phase 1.

The agent should track these and any other state mutations across the
conversation (which files were touched, which prompts were edited, etc.) —
the commit step in Phase 3 needs that context.

---

## Phase 1 — Setup

### Step 1.1 — Confirm the eval

If the user named an eval, validate that `.orca/evals/<eval>/` exists. If
not, list available evals (`ls .orca/evals/`) and ask. If the directory is
empty, stop with a clear message and point them at `orca-eval-create.md`.

### Step 1.2 — Confirm the language

If the user mentioned a language (English, Russian, "по-русски", etc.),
record it. Otherwise default to `en` and tell them they can override.

### Step 1.3 — Generate the explanation

Invoke the `orca-workflow-explain` skill with `flow=<eval>` and
`lang=<lang>`. The eval's `eval-flow.yml` IS the workflow it explains
(not the production flow). The skill writes the JSON to
`.orca-state/explanations/<eval>.<lang>.json` and the page becomes
available at `http://localhost:7891/explain/<eval>?lang=<lang>`.

### Step 1.4 — Open the explanation page

Print the URL clearly and open it in the user's browser:

- macOS: `open http://localhost:7891/explain/<eval>?lang=<lang>`
- Linux: `xdg-open http://localhost:7891/explain/<eval>?lang=<lang>`
- Windows: `start http://localhost:7891/explain/<eval>?lang=<lang>`

### Step 1.5 — Ask about input modifications

Conversationally:

> "Do you want to modify the input before we run? You can tweak the
> scenario in `input.md` or the bytes in the state branch
> (`.orca-state/eval-states/<eval>/`)."

If **no**, skip to Phase 2.

### Step 1.6 — Discuss + edit (if modifying)

Hold a free-form conversation with the user about what to change. Use your
`Edit` / `Read` / shell tools to:

- Modify `.orca/evals/<eval>/input.md` for scenario text or frontmatter
  changes (`state_ref:` etc.).
- For state-branch bytes, walk the user through committing into the
  persistent worktree at `.orca-state/eval-states/<eval>/` per
  [`orca-eval-create.md`](orca-eval-create.md) Step 6 (these commits live
  on the orphan `orca-eval-state/<eval>` branch and travel with the eval).

**Track every file you touched** — you'll need the list at commit time
(Phase 3, Step 3.5).

When the user signals "done modifying", continue to Phase 2.

---

## Phase 2 — Run

### Step 2.1 — Confirm

Conversationally:

> "Ready to run the eval?"

If no, stop politely.

### Step 2.2 — Run the eval

```
orca eval <eval-name>
```

(Verified via `orca eval --help`: positional arg is the eval directory
name under `.orca/evals/`.) Wait for the worker to finish. Surface any
runtime errors to the user; do NOT auto-retry.

### Step 2.3 — Locate the run output

The eval worker writes to
`.orca-state/eval-states/<eval>/<run_id>/`. Find the most recent `<run_id>`
(the orca CLI prints it; or `ls -t .orca-state/eval-states/<eval>/` then
take the first entry). Confirm `report.md` exists.

---

## Phase 3 — Review & Act

### Step 3.1 — Start the review one-shot

Launch the `eval-review` workflow (defined in `.orca/eval-review.yml`),
passing the `eval` and `run_id` fields:

```
orca run --inline-fields eval=<eval-name>,run_id=<run-id> -w eval-review
```

(Use whatever the actual CLI form is — check `orca run --help` if unsure.
The intent: start a one-issue run of the `eval-review` flow with these
two fields populated.)

The `review` state's worker reads `report.md` + computes the worktree
diff, then emits a `waiting` outcome carrying the form. The daemon prints
the form URL to its run-log.

### Step 3.2 — Open the form URL

Open it in the user's browser:
`http://localhost:7891/forms/<run_id>/<issue_id>`. Tell the user to
review the assertions, leave comments on the diff, tick any of the three
action checkboxes, and submit.

### Step 3.3 — Read the submitted values

When the user submits, the daemon unblocks the worker. The worker writes
the final outcome containing:

```json
{
  "outcome": "done",
  "cancelled": <bool>,
  "diff_review": [{ "file": "...", "line": <n>, "side": "old"|"new", "body": "..." }, ...],
  "update_prompts": <bool>,
  "update_assertions": <bool>,
  "commit": <bool>
}
```

If `cancelled` is true, jump straight to Step 3.6 (restart prompt) — no
actions to apply.

### Step 3.4 — Apply chosen actions (in order)

For each ticked action, run the corresponding sub-flow.

#### `update_prompts`

Surface to the user, in chat:

1. The list of **failed** criteria from `report.md` with their `name`,
   `summary`, and `detail`.
2. The relevant `diff_review` comments anchored to lines.

Discuss: which prompt under `.orca/prompts/<state>.md` should change, and
how. Apply edits with the `Edit` tool. Track which prompt files you
modified.

#### `update_assertions`

Surface the `diff_review` comments. Together with the user, edit
`.orca/evals/<eval>/assertions.md` to add / refine / remove criteria
based on the review.

#### `commit`

See Step 3.5.

### Step 3.5 — Commit (only if `commit` was ticked)

The commit step is **explicit and defensive**. The eval worker's output
lives at `.orca-state/eval-states/<eval>/<run_id>/` (gitignored), so the
worker's worktree files cannot reach the user's main tree. The playbook
nonetheless allow-lists exactly which files to stage.

1. Run `git status --porcelain` from the user's repo root.
2. Build the **allow-list** — only paths matching one of:
   - `.orca/evals/<eval>/input.md`
   - `.orca/evals/<eval>/assertions.md`
   - `.orca/evals/<eval>/eval-flow.yml`
   - `.orca/prompts/*.md`
   - Any other path the user explicitly mentioned editing during the
     discussion (from your tracked state).
3. **Hard exclude** any path matching `.orca-state/**` (defensive).
4. Show a markdown summary to the user:

   ```
   I'm going to commit these files:
     - .orca/evals/<eval>/input.md
     - .orca/prompts/implementing.md

   Commit message: `iterate <eval> eval after run`

   Proceed?
   ```

5. **Final yes/no confirmation in chat.**
6. On yes: `git add <listed-paths>` with **specific paths only** (never
   `-A`, never `.`). Then `git commit -m "<the proposed message>"`. If
   only prompts were updated, propose a more specific message like
   `tighten implementing prompt for <eval>`.
7. On no: skip the commit; the changes stay in the working tree.

### Step 3.6 — Restart?

Conversationally:

> "Want to run another iteration?"

If yes: loop back to Phase 1 with the same eval pre-filled (and re-ask
about language if you want).

If no: print a polite summary of what changed in this session and stop.

---

## Pitfall checks

- **Never use `git add -A` or `git add .`** in the commit step. Specific
  paths only.
- **Identifiers stay in English**: eval directory names, state names,
  field names, criterion names. Only conversational prose is localized.
- **Track edits**: every file you touch during the discussions in Phase 1
  step 1.6 and Phase 3 step 3.4 needs to be remembered for the commit
  step's allow-list.
- **Worktree files belong to the eval, not the user**: when the user asks
  "should we commit these too?" referring to the diff shown in the
  review form, the answer is **no** — those files live in
  `.orca-state/...` and aren't in the main tree.
- **Cancel ≠ no actions chosen**: if the user clicks Cancel on the review
  form, treat it as "stop the review, ask about restart". Don't apply any
  actions, don't commit.
- **First run won't have prior assertions to update meaningfully**: if
  this is the eval's first run, the failed-criteria list shapes the
  first prompt iteration. That's fine — the playbook still works.
