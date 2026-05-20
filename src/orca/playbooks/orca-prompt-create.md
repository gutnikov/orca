# Playbook: Create a State Prompt

Write or update a single `.orca/prompts/{state}.md` template — the instructions a worker reads when running a specific state of the workflow. Each **active** state in `.orca/{flow}.yml` has exactly one prompt file. This playbook is a pure procedure: given a state specification, produce a prompt that conforms to orca conventions and won't surprise the worker at runtime. It enforces structural correctness (variables resolve, sections in the right place, no obvious pitfalls) but does not iterate, does not run tests, and does not judge whether the prompt is *good* — that lives in [`reference/assertions-design.md`](reference/assertions-design.md) under a Chinese-wall isolation. If a quality concern surfaces while you're here, finish writing the structurally-correct file and hand the concern back to the caller.

> **Why this playbook is deliberately walled off from assertions.** By design, the prompt-creator does not see `assertions.md`, test reports, or grading rubrics — see the Three-Agent Principle in [`reference/assertions-design.md`](reference/assertions-design.md). If you find yourself wishing for that information, you're being asked to do the assertion-creator's job; push back and ask for a sharper spec instead.

> **Passive states have no prompt.** A passive state is one with no `worker:` block — it waits for a manual `AdvanceEvent` (CLI / TUI / API). If the state you're writing for has no worker, you don't need this playbook; see the *Gate State* pattern in [`orca-workflow-patterns.md`](reference/orca-workflow-patterns.md).

> **Inline vs file prompts.** The `worker.prompt` field also accepts inline Jinja directly in the YAML — `prompt: { text: "..." }` — for very short single-state flows where a separate file is overhead. The structure and pitfalls in this playbook still apply; the prompt source just lives in the YAML instead of in `.orca/prompts/{state}.md`. Default to a file: it's easier to review, diff, and reuse. Use inline only when the prompt is small enough to skim without scrolling.

## Required reading (you, the agent — not the user)

- [`reference/orca-config-reference.md`](reference/orca-config-reference.md) — template variables, Jinja conventions, `result_format` schema.

## When to use this

- During **[orca-workflow-create.md](orca-workflow-create.md)** step 5 (writing prompt templates), invoked with a state specification that already includes `result_format`.
- When adding a new state to an existing workflow, after the state's `result_format` is in the YAML.
- When given an explicit instruction to modify an existing prompt (add a constraint, rephrase a step, swap a template variable).

## Modes

This playbook runs in one of two modes. The caller indicates which.

### Create mode (default)

The state has no prompt file yet — `.orca/prompts/{state}.md` does not exist (or exists but is the skeleton). The caller hands over a fresh state spec. Run Steps 1–5 end to end and write the file.

### Update mode

The state's prompt file already exists and the caller wants a targeted change (a new constraint, a rephrased step, a swapped template variable). Read the existing file first, apply only the instructed delta, and re-run Step 4 (pitfall checks) on the result before writing. Do not regenerate from scratch — Update mode preserves prior tuning that the file has accumulated, including hand-edited prose the original spec didn't anticipate.

A correct Update-mode invocation looks like: "in `.orca/prompts/implementing.md`, after Step 2 add a constraint that the worker must not introduce new dependencies." Anything vaguer is a Create-mode rewrite in disguise — push back and ask for the specific delta.

## Prerequisites

- `.orca/{flow}.yml` exists and the target state is defined in it, **with `result_format` already specified**.
- You have a state specification:
  - **State name** (e.g., `implementing`, `reviewing`, `scoping`)
  - **One-sentence job** describing what the state does
  - **`result_format`** — already in the workflow YAML
  - **Inputs** — which `issue.fields.*` the worker reads
  - **Constraints** — branch behaviour, scope boundaries, no-touch rules
  - **Verification** — concrete project commands ("pytest tests/", "cargo test", etc.)

If any of these are missing from the spec, stop and request them. Do not invent.

## Step 1 — Confirm the state specification

Restate the spec in plain language as a sanity check that nothing is missing:

- State name and one-sentence job
- Required `issue.fields.*` (cross-checked against the workflow's `issue.fields` block)
- `result_format` shape (read from the YAML)
- Constraints (scope, branch behaviour, off-limits actions)
- Verification commands

If a field referenced by the spec isn't declared in `.orca/{flow}.yml`'s `issue.fields` block — and isn't emitted by an upstream state's `result_format` — stop. The spec is inconsistent with the workflow.

## Step 2 — Pick the right template variables

The full set of variables exposed to a prompt template:

| Variable | Type | Description | When you need it |
|---|---|---|---|
| `{{ issue.fields.* }}` | varies | User-declared issue fields (title, description, scope_boundary, etc.) plus auto-populated `failure_context` if declared in the schema. | Always — every prompt reads at least `title`/`description` |
| `{{ issue.base_branch }}` | string | Auto-populated at dispatch from the workflow's `base_branch` setting. **Top-level on `issue`, not under `fields`.** | If the worker needs to know the merge target |
| `{{ issue.depends_on }}` | list of issue ids | IDs of sibling issues this child waits on. Empty list for root issues. | If this state can only run after a predecessor |
| `{{ issue.decomposed_from }}` | string \| null | Parent issue id if this is a decomposed child; null otherwise. | When a child task needs parent context |
| `{{ issue.children }}` | list of dicts | Decomposed child issues. Each entry has keys `issue_id` (str), `fields` (dict), `state` (str), `event_log` (list). **No `id`, `title`, or `depends_on` at the child level** — access title via `child.fields.title`. | If this state operates over sub-issues |
| `{{ issue.event_log }}` | list of dicts | Event history. Each entry has `timestamp` (ISO 8601), `type` (str), `data` (dict). | Retry-aware prompts that need past failures |
| `{{ result_format }}` | dict | Schema Orca validates against | Advanced prompts that explain allowed outcomes |
| `{{ result_example }}` | dict | Concrete result JSON the worker can copy and fill in | **Always** — embed via `tojson(indent=2)` |
| `{{ result_path }}` | string | Path to write result.json | **Always — and inside the `## Result` section, not only at the top of the prompt.** See pitfall P3. |
| `{{ run.branch }}` | string | Git branch name | Prompts that orchestrate their own filesystem |
| `{{ run.workflow }}` | string | Workflow name | Same as above (rare) |
| `{{ run.run_dir }}` | string | `.orca-state/runs/<branch>/<workflow>` | Same as above (rare) |
| `{{ run.sessions }}` | list | Previous session summaries | Retry / continuation-aware prompts |
| `{{ run.summary }}` | dict | Run statistics (states visited, outcomes, failures) | Retry / continuation-aware prompts |

> Two auto-populated values have *different access paths* — the table above gets this right; it's worth restating because the schema doc treats them as siblings:
> - `{{ issue.base_branch }}` — top-level on the issue dict.
> - `{{ issue.fields.failure_context }}` — **inside `fields`** (only present if the workflow declared `failure_context` in its issue schema, per the *Failure-Context Propagation* pattern).

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

The framework auto-appends an end-of-prompt warning with the literal path, so a forgotten `{{ result_path }}` is no longer fatal — but it makes the worker seek back to the last line of a long prompt at the moment it's about to write. Put the path next to the schema instead.

**Bad:**
```markdown
## Result

Writing the result file is the FINAL action. Commit every change first.
```

**Good:**
```markdown
## Result

Write the result JSON (schema above) to `{{ result_path }}`. Writing the result file is the FINAL action. Commit every change first — orca terminates the session ~30 s after detecting a valid result.
```

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

## Step 5 — Verify the prompt renders, then write the file

Before writing:

1. **File path matches the YAML.** Confirm `.orca/prompts/{state}.md` matches the `worker.prompt` path in `.orca/{flow}.yml`. The filename and the YAML reference must agree exactly.
2. **All field references exist.** Every `{{ issue.fields.X }}` in the prompt must be declared in the workflow's `issue.fields` block (or set by an upstream state's `result_format`). Grep the prompt for `issue.fields.` and cross-check.
3. **`{% if %}` guards on optional sections.** Anything that depends on optional data (`depends_on`, `children`, etc.) must be guarded — otherwise the rendered prompt has dangling empty headers.
4. **JSON template renders cleanly.** Mentally render the bottom block with the actual `result_format` and check that the JSON is what you want the worker to produce.
5. **`{{ result_path }}` appears inside the `## Result` section** — not only at the top of the prompt. Pull the section body and check for the variable:

   ```bash
   awk '/^## Result/{flag=1; next} /^## /{flag=0} flag' .orca/prompts/{state}.md | grep -q '{{ result_path }}'
   ```

   `awk` keeps reading until the next `##` heading, so this matches the path anywhere in the Result section regardless of whitespace, prose preamble, or how many lines the schema block takes. The framework also interpolates the path into the auto-appended end-of-prompt warning, so a forgotten `{{ result_path }}` is no longer fatal — but the Result section is the logical home for it. Treat this as defense-in-depth, not a single point of failure.

If your editor supports it, render the Jinja template with a sample issue and read the output — many bugs only show up post-render (orphan headers, missing fields, wrong indentation in the JSON block).

Once the checks pass, write the file to `.orca/prompts/{state}.md`. Done — return control to the caller.

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
- Single-responsibility sentence (from the spec)
- Whether all variables resolve against the current issue schema
- Next step (caller's decision — this playbook does not run tests or iterate)
