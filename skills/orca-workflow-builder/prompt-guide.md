# Prompt Guide

How to write effective orca worker prompts. Each active state needs a Jinja2 prompt template at the path specified in `worker.prompt`.

## Prompt Anatomy

Every prompt should follow this structure:

```markdown
# Role & Mission
You are a [ROLE] agent. Your job is to [SINGLE RESPONSIBILITY].

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

{% if issue.feedback_context %}
## Previous Feedback
{{ issue.feedback_context }}
{% endif %}

## Instructions

### Step 1: [Understand the task]
...

### Step 2: [Do the work]
...

### Step 3: [Verify]
Run tests, lint, typecheck as appropriate.

### Step 4: [Commit]
Stage and commit all changes with a descriptive message.

## Constraints
- ONLY modify files in: {{ issue.fields.scope_boundary }}
- Do NOT modify shared config files
- [Additional constraints specific to this state]

## Result

Write your result to `{{ result_path }}`:

```json
{{ result_format | tojson(indent=2) }}
```

IMPORTANT: Writing the result file is the FINAL action. Complete ALL work and commits first.
```

**Key principles:**
- Single responsibility — one job per prompt
- Numbered steps — not prose paragraphs
- Constraints near the end — where they're fresh in the worker's context
- Result format always last — with explicit JSON schema
- Conditional sections — use `{% if %}` to avoid empty headers

## Template Variables

| Variable | Type | Description |
|---|---|---|
| `{{ issue.fields.* }}` | varies | Issue data defined in config fields |
| `{{ issue.depends_on }}` | list | IDs of issues this one depends on |
| `{{ issue.children }}` | list | Child issues (after decomposition) |
| `{{ issue.event_log }}` | list | Event history (timestamps, types, data) |
| `{{ issue.base_branch }}` | string | Git branch for merging |
| `{{ issue.feedback_context }}` | string | User's answers from feedback round |
| `{{ issue.feedback_questions }}` | string | Questions worker asked before |
| `{{ issue.decomposed_from }}` | string | Parent issue ID (if child) |
| `{{ result_format }}` | dict | Schema worker must produce |
| `{{ result_path }}` | string | Path to write result.json |
| `{{ run.branch }}` | string | Git branch name |
| `{{ run.workflow }}` | string | Workflow name |
| `{{ run.run_dir }}` | string | `.orca/runs/BRANCH/WORKFLOW` |
| `{{ run.sessions }}` | list | Previous session summaries |
| `{{ run.summary }}` | dict | Run statistics (states visited, outcomes, failures) |

## Jinja2 Usage

**Filters:**
- `{{ x | tojson(indent=2) }}` — serialize to formatted JSON
- `{{ x | length }}` — string/list length
- `{{ items | join(", ") }}` — join list with separator
- `{{ x | upper }}`, `{{ x | lower }}` — case conversion
- `{{ x | replace(old, new) }}` — string replacement

**Conditionals (avoid empty sections):**
```jinja2
{% if issue.feedback_context %}
## Previous Feedback
{{ issue.feedback_context }}
{% endif %}
```

**Loops:**
```jinja2
{% for child in issue.children %}
- {{ child.fields.title }}: {{ child.fields.scope_boundary }}
{% endfor %}
```

## The 10 Pitfalls

### 1. No fail-safe outcome

**Bad:** `values: [done]` — worker reports "done" even when stuck.

**Good:** `values: [done, blocked, needs_feedback]` — worker can escalate.

### 2. Combining two jobs in one prompt

**Bad:** "Plan the feature, then implement it" — both done poorly.

**Good:** Split into `planning` state and `implementing` state. One job each.

### 3. Not embedding result_format

**Bad:** "Write the result as JSON" — worker guesses the shape.

**Good:**
```jinja2
Write your result to `{{ result_path }}`:

```json
{{ result_format | tojson(indent=2) }}
```
```

### 4. Writing result file before committing

**Bad:** Write result → commit → session killed before commit finishes.

**Good:** Commit all work → write result file as FINAL action.

The orchestrator terminates the session ~30 seconds after detecting a valid result file.

### 5. Hardcoding values instead of template variables

**Bad:** `Edit files in src/auth/` — breaks if scope changes.

**Good:** `Edit files in {{ issue.fields.scope_boundary }}`

### 6. Missing scope boundary enforcement

**Bad:** Prompt doesn't mention scope — worker edits random files.

**Good:**
```markdown
## Constraints
- ONLY modify files under: {{ issue.fields.scope_boundary }}
- Do NOT modify files outside this boundary
```

### 7. No verification steps

**Bad:** "Implement the feature" — no mention of testing.

**Good:**
```markdown
### Step 3: Verify
1. Run unit tests: `pytest tests/ -v`
2. Run linter: `ruff check .`
3. Run type checker: `mypy src/`
```

### 8. Unreachable states

**Bad:** State exists in config but no `on:` rule transitions to it.

**Good:** Every non-initial state must be reachable via at least one `on:` rule. Config validator catches this.

### 9. Decompose without sub_issues in result_format

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

### 10. Infinite loops without max_hops

**Bad:** `blocked: planning` loops forever with no limit.

**Good:** Set `max_hops: 10` at the top level. Issue errors out after 10 transitions.
