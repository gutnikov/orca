# Playbook: Create a State Prompt

Write or update a single `.orca/prompts/{state}.md` template — the instructions a worker reads when running a specific state of the workflow. Each **active** state in `.orca/{flow}.yml` has exactly one prompt file. This playbook walks you through producing one that conforms to orca conventions and won't surprise the worker at runtime.

> **Passive states have no prompt.** A passive state is one with no `worker:` block — it waits for a manual `AdvanceEvent` (CLI / TUI / API). If the state you're writing for has no worker, you don't need this playbook; see the *Gate State* pattern in [`orca-workflow-patterns.md`](reference/orca-workflow-patterns.md).

> **Inline vs file prompts.** The `worker.prompt` field also accepts inline Jinja directly in the YAML — `prompt: { text: "..." }` — for very short single-state flows where a separate file is overhead. The structure and pitfalls in this playbook still apply; the prompt source just lives in the YAML instead of in `.orca/prompts/{state}.md`. Default to a file: it's easier to review, diff, and reuse. Use inline only when the prompt is small enough to skim without scrolling.

## Required reading (you, the agent — not the user)

- [`reference/assertions-design.md`](reference/assertions-design.md) — the assertions-first paradigm and the methodology that anchors every prompt this playbook produces. Read this *first*; prompts are downstream of user-curated assertions.
- [`reference/prompt-design.md`](reference/prompt-design.md) — the prompt-side conventions (structured fields, explicit constraints, minimal-edit discipline) used in this playbook.

## When to use this

- During **[orca-workflow-create.md](orca-workflow-create.md)** step 5 (writing prompt templates).
- When adding a new state to an existing workflow.
- When **[orca-workflow-review.md](orca-workflow-review.md)** flags a prompt-quality issue you need to rewrite.
- When a worker keeps producing wrong-shape output or ignoring scope — *sometimes* a prompt bug, but walk the failure-attribution taxonomy in [`reference/assertions-design.md`](reference/assertions-design.md) §5 before editing. Five of the six failure modes are not prompt bugs.

## Prerequisites

- `.orca/{flow}.yml` exists and the target state is defined in it.
- You know which state you're writing the prompt for (e.g., `implementing`, `reviewing`, `scoping`).
- You've read [`reference/assertions-design.md`](reference/assertions-design.md). Under the assertions-first paradigm, `assertions.md` and `result_format` are drafted in Step 1 below — *before* any prompt prose. If a `result_format` already exists in the YAML, you'll reconcile against it in Step 1; if not, you'll design it.

## Step 1 — Pin down the state's contract

The contract is `assertions.md` + `result_format`. Both are drafted before any prompt prose — that is the assertions-first paradigm. See [`reference/assertions-design.md`](reference/assertions-design.md) §3 for the link to `result_format` and §5 for the bootstrap question set.

Settle these six points before drafting the prompt:

1. **Draft `assertions.md` first.** Run the 3-question bootstrap (one-sentence success / obvious failure / shape of result). Write 3–5 objective, gradable criteria. Save them under `.orca/tests/<scenario>/assertions.md` per [`orca-test-create.md`](orca-test-create.md). If a scenario directory already exists, edit in place.
2. **Sketch `result_format` from the criteria.** Every field a criterion references must be emitted. If the state already has a `result_format` in `.orca/{flow}.yml`, reconcile against it (add missing fields, flag judgment-heavy criteria that depend on prose-shape evidence). If not, design one and add it to the YAML. Cross-reference every enum value against the state's `on:` map — they must match.
3. **Single responsibility.** What is this state's *one* job? Write it as one sentence. If you can't, the state needs to be split — go back to [orca-workflow-create.md](orca-workflow-create.md) and split it before writing this prompt.
4. **Inputs.** Which `issue.fields.*` does the worker need? (Usually `title`, `description`, plus state-specific fields like `scope_boundary`, `plan`, `acceptance_criteria`.)
5. **Branch behaviour.** Does this state expect to be on a feature branch? Does it commit? Does it merge? Note this — the constraints section will need to reflect it.
6. **Verification.** What does "done correctly" mean in this project? (Tests pass? Lint clean? Types check? Specific command? Match the project's actual conventions, not a generic list.)

Write these six answers down before drafting the prompt. If anything is unclear, ask the user. The prompt you draft in Step 3 has one job: make the worker emit a result that passes the criteria in (1) and matches the schema in (2).

## Step 2 — Pick the right template variables

The full set of variables exposed to a prompt template:

| Variable | Type | Description | When you need it |
|---|---|---|---|
| `{{ issue.fields.* }}` | varies | Issue data defined in config fields | Always — title, description, state-specific fields |
| `{{ issue.depends_on }}` | list | IDs of issues this one depends on | If this state can only run after a predecessor |
| `{{ issue.children }}` | list | Child issues (after decomposition) | If this state operates over sub-issues |
| `{{ issue.event_log }}` | list | Event history (timestamps, types, data) | Retry-aware prompts that need past failures |
| `{{ issue.base_branch }}` | string | Git branch for merging | If the worker needs to know the merge target |
| `{{ issue.decomposed_from }}` | string | Parent issue ID (if child) | When a child task needs parent context |
| `{{ result_format }}` | dict | Schema Orca validates against | Advanced prompts that explain allowed outcomes |
| `{{ result_example }}` | dict | Concrete result JSON the worker can copy and fill in | **Always** — embed via `tojson(indent=2)` |
| `{{ result_path }}` | string | Path to write result.json | **Always — and inside the `## Result` section, not only at the top of the prompt.** See pitfall P3. |
| `{{ run.branch }}` | string | Git branch name | Prompts that orchestrate their own filesystem |
| `{{ run.workflow }}` | string | Workflow name | Same as above (rare) |
| `{{ run.run_dir }}` | string | `.orca-state/runs/BRANCH/WORKFLOW` | Same as above (rare) |
| `{{ run.sessions }}` | list | Previous session summaries | Retry / continuation-aware prompts |
| `{{ run.summary }}` | dict | Run statistics (states visited, outcomes, failures) | Retry / continuation-aware prompts |

Anything optional (`depends_on`, `children`, `event_log`) must be wrapped in `{% if %}` — otherwise the rendered prompt has empty headers that confuse the worker.

### Jinja2 reference

Filters you'll commonly use inside a prompt template:

- `{{ x | tojson(indent=2) }}` — serialize to pretty-printed JSON. **Always use this for `result_example`** in the output contract. `result_format` is the validation schema; do not ask the worker to copy it as the result file.
- `{{ x | length }}` — string/list length
- `{{ items | join(", ") }}` — join list with separator
- `{{ x | upper }}`, `{{ x | lower }}` — case conversion
- `{{ x | replace(old, new) }}` — string replacement

When accessing dict keys that may shadow Python methods, use bracket syntax. For example, use
`{{ result_format['outcome']['values'] | tojson }}` instead of `{{ result_format.outcome.values | tojson }}`.

Conditionals (always use these to avoid empty sections):

```jinja2
{% if issue.depends_on %}
## Dependencies
{% for dep in issue.depends_on %}
- {{ dep }}
{% endfor %}
{% endif %}
```

Loops over decomposed children:

```jinja2
{% for child in issue.children %}
- {{ child.fields.title }}: {{ child.fields.scope_boundary }}
{% endfor %}
```

## Step 3 — Draft the prompt with the canonical structure

Use this skeleton — keep the section order; readers and workers both expect it.

```markdown
# Role & Mission

You are a [ROLE] agent. Your job is to [SINGLE RESPONSIBILITY — one sentence].

## Context

**Title:** {{ issue.fields.title }}
**Description:** {{ issue.fields.description }}
**Scope Boundary:** {{ issue.fields.scope_boundary }}

{% if issue.depends_on %}
## Dependencies
{% for dep in issue.depends_on %}
- {{ dep }}
{% endfor %}
{% endif %}

## Instructions

### Step 1: Understand the task
[What the worker should read / explore before acting.]

### Step 2: Do the work
[The actual transformation this state performs. Numbered sub-steps if non-trivial.]

### Step 3: Verify
[Concrete commands — match this project's conventions:
- `pytest tests/ -v`
- `ruff check .`
- `mypy src/`
Replace these with what the project actually uses.]

### Step 4: Commit (if this state modifies files)
If this state changes files in the worktree, stage and commit them with a descriptive message before writing the result. **Skip this step for states that only produce a decision (e.g. scoping, reviewing).**

### Step 5: When to pause for human input
If you cannot proceed without a human decision — an ambiguous spec, a destructive action that needs confirmation, an external dependency to land — emit the built-in `waiting` outcome instead of `done` or `blocked`. Write:

```json
{"outcome": "waiting", "reason": "<one-line ask, plus relevant context the human needs>"}
```

The orchestrator pauses the inactivity timer; a human will reply via `orca unblock`. Use `waiting` sparingly — most decisions belong in the next state, not mid-state.

## Constraints

- ONLY modify files under: {{ issue.fields.scope_boundary }}
- Do NOT modify [list specific things off-limits for this state]
- [Add any state-specific constraint — e.g., "Do not introduce new dependencies", "Do not rename existing public functions"]

## Result

Write your result to `{{ result_path }}`:

```json
{{ result_example | tojson(indent=2) }}
```

IMPORTANT: Writing the result file is the FINAL action. Complete ALL work and commits first.
```

Why this structure:
- **Role & mission first** anchors the worker's identity.
- **Context next** loads the relevant variables before they're referenced.
- **Instructions as numbered steps** — workers follow ordered lists more reliably than prose paragraphs.
- **Constraints near the end** so they're fresh in the worker's attention when it acts.
- **Result block last** because output writing is the worker's final action.

## Step 4 — Cross-check against the pitfalls

Run through every item below against your draft. These are the most common failure modes; each has bitten real workflows. The first group is prompt-level — fix in the `.md` file you're writing. The second group is workflow-level — fix in `.orca/{flow}.yml`. If you encounter a workflow-level issue while editing a prompt, hand it back to [`orca-workflow-create.md`](orca-workflow-create.md) rather than papering over it in the prompt.

### Prompt-level pitfalls

#### P1. Combining two jobs in one prompt

**Bad:** "Plan the feature, then implement it" — both done poorly.

**Good:** Split into a `planning` state and an `implementing` state. One job each.

#### P2. Not embedding a concrete result example

**Bad:** "Write the result as JSON" — worker guesses the shape.

**Good:**
````
Write your result to `{{ result_path }}`:

```json
{{ result_example | tojson(indent=2) }}
```
````

#### P3. Omitting `{{ result_path }}` in the `## Result` section

**Bad:**
```markdown
## Result

Writing the result file is the FINAL action. Commit every change first — orca terminates the session ~30 s after detecting a valid result.
```

The worker reads "the result file" and has no path in this section. Historically this caused real zombies — late in the run, the worker would start an unbounded sub-investigation to *find* the path (often reading `.orca-state/runs/.../state.json` or grepping the repo), burn through `--max-turns` or context budget, and the session would end without `result.json` ever being written. Orca then records `worker_failed: result file not found after session exited`.

The framework now interpolates the path into the auto-appended end-of-prompt warning, so the worker can still recover it from the very last line of the rendered prompt. That makes this pitfall a clarity issue rather than a fatal one — but workers don't always read prompts linearly, especially long ones, and an explicit path in the `## Result` section avoids the seek-back-to-the-bottom pattern entirely.

**Good:**
```markdown
## Result

Write the result JSON (schema above) to `{{ result_path }}`. Writing the result file is the FINAL action. Commit every change first — orca terminates the session ~30 s after detecting a valid result.
```

The literal path is right there at the moment the worker is about to act on it. No lookup, no guessing.

**Rule of thumb:** Mentioning `{{ result_path }}` once at the top of the prompt is not enough — long prompts (200+ lines) push the path out of the worker's attention window by the time it reaches the result-writing step. The path belongs in the section the worker is reading *when it writes*. If you also embed a schema block earlier with `Write your result to \`{{ result_path }}\`:` (P2), the `## Result` reminder can be a one-liner pointing back to it.

#### P4. Writing the result file before committing

**Bad:** Write result → commit → session killed before commit finishes.

**Good:** Commit all work → write result file as FINAL action. The orchestrator terminates the session ~30 seconds after detecting a valid result file.

#### P5. Hardcoding values instead of template variables

**Bad:** `Edit files in src/auth/` — breaks if scope changes.

**Good:** `Edit files in {{ issue.fields.scope_boundary }}`

#### P6. Missing scope boundary enforcement

**Bad:** Prompt doesn't mention scope — worker edits random files.

**Good:**
```markdown
## Constraints
- ONLY modify files under: {{ issue.fields.scope_boundary }}
- Do NOT modify files outside this boundary
```

#### P7. No verification steps (or generic ones)

**Bad:** "Implement the feature" — no mention of testing. Or: "Run tests" — worker picks the wrong runner.

**Good:** Name the project's actual tools:
```markdown
### Step 3: Verify
1. `pytest tests/ -v`
2. `ruff check .`
3. `mypy src/`
```

### Workflow-level pitfalls (flag and escalate)

#### W1. No fail-safe outcome on the state

**Bad:** `values: [done]` — worker reports "done" even when stuck.

**Good:** `values: [done, blocked]` — worker can escalate. The built-in `waiting` outcome is also available for human-in-the-loop without declaring it in `values`.

#### W2. Unreachable state

**Bad:** State exists in `states:` but no `on:` rule transitions to it.

**Good:** Every non-initial active state must be reachable via at least one `on:` rule. The config validator catches this — it's worth checking before you commit.

#### W3. Decompose action without `sub_issues` in `result_format`

**Bad:** `on: { decompose: { action: decompose } }` but no `sub_issues` field.

**Good:**
```yaml
result_format:
  outcome:
    type: enum
    values: [decompose, ready]
  sub_issues:
    type: list
    items: "$issue"
    required_when: [decompose]
```

#### W4. Unbounded transitions / retries

Two distinct bounds, both worth setting:

- **`max_hops`** (global) caps *total* state transitions per issue. Without it, a `blocked → planning → blocked → planning …` cycle (or any long pipeline) can run forever. Recommended: 10–20.
- **`max_worker_retries`** (global) caps worker *failures* in the same state. Without it, a crashing worker retries until your patience runs out. Recommended: 3–5.

```yaml
max_hops: 15
max_worker_retries: 3
```

A self-looping `blocked` outcome is bounded by `max_hops` (each loop = one transition), not by `max_worker_retries` (which counts crashes, not `blocked` results).

## Step 5 — Verify the prompt renders

Before committing:

1. **File path matches the YAML.** Confirm `.orca/prompts/{state}.md` matches the `worker.prompt` path in `.orca/{flow}.yml`. The filename and the YAML reference must agree exactly.
2. **All field references exist.** Every `{{ issue.fields.X }}` in the prompt must be declared in the workflow's `issue.fields` block (or set by an upstream state's `result_format`). Grep the prompt for `issue.fields.` and cross-check.
3. **`{% if %}` guards on optional sections.** Anything that depends on optional data (`depends_on`, `children`, etc.) must be guarded — otherwise the rendered prompt has dangling empty headers.
4. **JSON template renders cleanly.** Mentally render the bottom block with the actual `result_format` and check that the JSON is what you want the worker to produce.
5. **`{{ result_path }}` appears in the `## Result` section** — not only at the top of the prompt. Run `grep -A2 '^## Result' .orca/prompts/{state}.md | grep -q '{{ result_path }}'`. The framework also interpolates the path into the auto-appended end-of-prompt warning, so a forgotten `{{ result_path }}` is no longer fatal — but the `## Result` section is the logical home for it, and the worker is more likely to write the file correctly when the path sits next to the schema rather than at the very end of a 200+ line prompt. Treat this as defense-in-depth, not a single point of failure.

If your editor supports it, render the Jinja template with a sample issue and read the output — many bugs only show up post-render (orphan headers, missing fields, wrong indentation in the JSON block).

## Step 6 — Show the user the assertions, then write the file

For any non-trivial prompt:
1. Print the draft prompt *alongside* the `assertions.md` it is supposed to satisfy.
2. Ask the user to verify the **assertions** capture what they want — not whether the prompt prose reads well. The prompt is whatever passes the assertions; the assertions are the durable spec. See [`reference/assertions-design.md`](reference/assertions-design.md) §1.
3. Adjust assertions if needed; adjust the prompt only as a downstream consequence.
4. Write to `.orca/prompts/{state}.md`.

Skipping the show-the-assertions step is the most common way to produce a prompt the user later has to rewrite from scratch. The user reviewing the prompt directly is a fallback, not the default — at 200+ lines, prompts are not designed to be read.

## Step 7 — Trigger a re-audit

If you're editing an existing workflow, run **[orca-workflow-review.md](orca-workflow-review.md)** afterwards to confirm the change didn't break structural or efficiency rules. A single prompt edit can ripple — e.g., adding a new `{{ issue.fields.X }}` reference requires that field to exist in the schema.

If you're inside the larger [orca-workflow-create.md](orca-workflow-create.md) flow, the audit is already part of step 6 there; don't double-run it.

## Step 8 — Run the test and iterate

By Step 1 you drafted `assertions.md` and a matching `result_format`. By Steps 3–6 you wrote the prompt. Now run the test that exercises this prompt and iterate per the loop in [`reference/assertions-design.md`](reference/assertions-design.md) §5:

1. Run the test scaffolded under `.orca/tests/<scenario>/` (see [`orca-test-create.md`](orca-test-create.md) for `orca test` invocation). Read `report.md`.
2. For every failing criterion, walk the failure-attribution taxonomy **before** editing anything. The taxonomy distinguishes Prompt / Assertion / Scenario / `result_format` / Model / Flow failures; each gets a different fix.
3. Apply the **minimal** edit — one sentence in the prompt, one field in the schema, one rewrite of the criterion, depending on the attribution. Resist broad rewrites.
4. Re-run. Repeat until all criteria pass, or the user explicitly accepts the remaining gaps.

If a new kind of bad output surfaces later (drift), the first move is **not** editing the prompt. Write a criterion that catches the new output, confirm it fails, then attribute and apply the minimal edit. Never grow the prompt without a failing criterion that justifies it.

Skip this step only for genuinely trivial prompts (one-line decision states with no constraints worth grading).

## Anti-patterns to refuse

- **Drafting the prompt before drafting assertions and `result_format`.** The prompt has nothing to converge on. The paradigm requires Step 1 first — see [`reference/assertions-design.md`](reference/assertions-design.md). Refuse and bootstrap.
- **Adding prompt prose to fix drift without a failing assertion.** Drift = write a new criterion first, confirm it fails, then minimal-edit. "Just in case" prose is how prompts grow from 100 to 500 lines.
- **Two-job prompts.** "First plan, then implement" in one prompt — refuse, ask to split states.
- **Prose dump of "everything the worker should know".** Workers follow numbered steps; long paragraphs are skimmed.
- **Generic verification.** "Run tests" without naming the test runner. Workers will pick the wrong one or skip it.
- **Constraints buried in the introduction.** Workers forget early constraints. They belong near the end.
- **Embedding `{{ result_format | tojson(indent=2) }}` as the result file.** That is the validation schema, not a valid worker result. Use `{{ result_example | tojson(indent=2) }}` or a concrete hand-written result example.
- **Mentioning what to do *after* writing the result file.** The orchestrator kills the session ~30s after detecting a valid result. Anything after the result write won't run.

## Done

Report:
- File written or updated: `.orca/prompts/{state}.md`
- Assertions drafted and where: `.orca/tests/<scenario>/assertions.md` (criteria count)
- `result_format` design — added, reconciled, or unchanged
- Single-responsibility sentence (the one you wrote in Step 1)
- Whether all variables resolve against the current issue schema
- Whether a workflow re-audit was run and its result
- Whether the test was run and the criteria-pass count
- Next step (continue iterating, commit, or move to the next state's prompt)
