# Playbook: Create a State Prompt

Write or update a single `.orca/prompts/{state}.md` template — the instructions a worker reads when running a specific state of the workflow. Each **active** state in `.orca/{flow}.yml` has exactly one prompt file. This playbook walks you through producing one that conforms to orca conventions and won't surprise the worker at runtime.

> **Passive states have no prompt.** A passive state is one with no `worker:` block — it waits for a manual `AdvanceEvent` (CLI / TUI / API). If the state you're writing for has no worker, you don't need this playbook; see the *Gate State* pattern in [`orca-workflow-patterns.md`](reference/orca-workflow-patterns.md).

## When to use this

- During **[orca-create-workflow.md](orca-create-workflow.md)** step 5 (writing prompt templates).
- When adding a new state to an existing workflow.
- When **[orca-review-workflow.md](orca-review-workflow.md)** flags a prompt-quality issue you need to rewrite.
- When a worker keeps producing wrong-shape output or ignoring scope — usually a prompt bug.

## Prerequisites

- `.orca/{flow}.yml` exists and the target state is defined in it.
- You know which state you're writing the prompt for (e.g., `implementing`, `reviewing`, `scoping`).
- You've read the `result_format` for this state from the YAML — the prompt must produce that exact shape.

## Step 1 — Pin down the state's contract

Before writing prose, extract these from `.orca/{flow}.yml`:

1. **Single responsibility.** What is this state's *one* job? Write it as one sentence. If you can't, the state needs to be split — go back to [orca-create-workflow.md](orca-create-workflow.md) and split it before writing this prompt.
2. **Inputs.** Which `issue.fields.*` does the worker need? (Usually `title`, `description`, plus state-specific fields like `scope_boundary`, `plan`, `acceptance_criteria`.)
3. **Outputs.** Read the state's `result_format`. List every key, its type, and (for enum outcomes) every legal value. Cross-reference every value against the state's `on:` map — they must match.
4. **Branch behaviour.** Does this state expect to be on a feature branch? Does it commit? Does it merge? Note this — the constraints section will need to reflect it.
5. **Verification.** What does "done correctly" mean in this project? (Tests pass? Lint clean? Types check? Specific command? Match the project's actual conventions, not a generic list.)

Write these five answers down before drafting the prompt. If anything is unclear, ask the user.

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
| `{{ result_path }}` | string | Path to write result.json | **Always** — tell the worker where to write |
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

Run through every item below against your draft. These are the most common failure modes; each has bitten real workflows. The first group is prompt-level — fix in the `.md` file you're writing. The second group is workflow-level — fix in `.orca/{flow}.yml`. If you encounter a workflow-level issue while editing a prompt, hand it back to [`orca-create-workflow.md`](orca-create-workflow.md) rather than papering over it in the prompt.

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

#### P3. Writing the result file before committing

**Bad:** Write result → commit → session killed before commit finishes.

**Good:** Commit all work → write result file as FINAL action. The orchestrator terminates the session ~30 seconds after detecting a valid result file.

#### P4. Hardcoding values instead of template variables

**Bad:** `Edit files in src/auth/` — breaks if scope changes.

**Good:** `Edit files in {{ issue.fields.scope_boundary }}`

#### P5. Missing scope boundary enforcement

**Bad:** Prompt doesn't mention scope — worker edits random files.

**Good:**
```markdown
## Constraints
- ONLY modify files under: {{ issue.fields.scope_boundary }}
- Do NOT modify files outside this boundary
```

#### P6. No verification steps (or generic ones)

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

If your editor supports it, render the Jinja template with a sample issue and read the output — many bugs only show up post-render (orphan headers, missing fields, wrong indentation in the JSON block).

## Step 6 — Show the user, then write the file

For any non-trivial prompt:
1. Print the draft.
2. Ask: "Does this match what you want this state to do?"
3. Adjust based on feedback.
4. Write to `.orca/prompts/{state}.md`.

Skipping the show-and-confirm step is the most common way to produce a prompt the user later has to rewrite.

## Step 7 — Trigger a re-audit

If you're editing an existing workflow, run **[orca-review-workflow.md](orca-review-workflow.md)** afterwards to confirm the change didn't break structural or efficiency rules. A single prompt edit can ripple — e.g., adding a new `{{ issue.fields.X }}` reference requires that field to exist in the schema.

If you're inside the larger [orca-create-workflow.md](orca-create-workflow.md) flow, the audit is already part of step 6 there; don't double-run it.

## Anti-patterns to refuse

- **Two-job prompts.** "First plan, then implement" in one prompt — refuse, ask to split states.
- **Prose dump of "everything the worker should know".** Workers follow numbered steps; long paragraphs are skimmed.
- **Generic verification.** "Run tests" without naming the test runner. Workers will pick the wrong one or skip it.
- **Constraints buried in the introduction.** Workers forget early constraints. They belong near the end.
- **Embedding `{{ result_format | tojson(indent=2) }}` as the result file.** That is the validation schema, not a valid worker result. Use `{{ result_example | tojson(indent=2) }}` or a concrete hand-written result example.
- **Mentioning what to do *after* writing the result file.** The orchestrator kills the session ~30s after detecting a valid result. Anything after the result write won't run.

## Done

Report:
- File written or updated: `.orca/prompts/{state}.md`
- Single-responsibility sentence (the one you wrote in Step 1)
- Whether all variables resolve against the current issue schema
- Whether a re-audit was run and its result
- Next step (test run, commit, or continue with the next state's prompt)
