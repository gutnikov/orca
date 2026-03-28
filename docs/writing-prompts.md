# Writing Worker Prompts

A worker prompt is a contract between the orchestrator and the agent. It tells the agent exactly what to do, what context it has, and what result to produce. A good prompt is unambiguous, scoped, and structured. A bad prompt produces unpredictable results, wasted retries, and confused agents.

This guide covers general principles for writing effective coding-agent prompts, followed by orca-specific mechanics.

## General Principles

These apply to any system that dispatches coding agents, not just orca.

### 1. Single Responsibility

One prompt, one job. A scoping agent scopes. A planning agent plans. An implementing agent implements. Don't combine planning and coding in the same prompt — the agent will rush through planning to start coding, or get lost switching between modes.

If you find yourself writing "then, do this completely different thing," split it into two states.

### 2. Explicit Scope Boundaries

Tell the agent exactly which files and directories it owns. When multiple agents run in parallel, unclear ownership causes conflicts — two agents editing the same file, overwriting each other's work.

```markdown
**Scope Boundary:** {{ issue.fields.scope_boundary }}

- ONLY create/modify files within your scope boundary
- Create new files rather than editing shared ones
- Do NOT run formatters on files outside your scope
```

### 3. Structured Output Contract

Never let the agent decide how to report results. Define the exact JSON schema it must produce. This lets the orchestrator validate the result, route to the next state, and retry on malformed output.

```markdown
Write the result JSON to `{{ result_path }}`:

\`\`\`json
{{ result_format | tojson(indent=2) }}
\`\`\`
```

Include the schema directly in the prompt so the agent can self-check without guessing.

### 4. Fail-Safe Exits

Always give the agent a way to say "I can't do this" rather than forcing it to produce bad work. If the plan is insufficient, report `blocked`. If the scope is wrong, report `needs_rescope`. If the merge fails, report `failed`.

Agents that have no escape hatch will hallucinate success to satisfy the prompt.

```yaml
result_format:
  outcome:
    type: enum
    values: [done, blocked]
    values_description:
      done: "All tests pass, changes committed"
      blocked: "Cannot proceed — explain why in summary"
```

### 5. Step-by-Step Instructions

Agents follow numbered sequential instructions better than prose paragraphs. Break the work into clear steps with explicit ordering.

```markdown
### Step 1: Read the Plan
Find and read the implementation plan in `docs/plans/`.

### Step 2: Read the Tests
Find and read ALL test files created by the planning agent.

### Step 3: Implement
Follow the plan step by step. Run tests frequently.
```

Don't bury critical instructions in the middle of a paragraph. Make each step a heading or a numbered item.

### 6. Verification Before Completion

Require the agent to verify its work before reporting success. Tests, linters, type checks — whatever the project uses.

```markdown
### Step 5: Run All Checks

Before committing:
1. Run unit tests
2. Run pre-commit hooks (`pre-commit run --all-files`)
3. Run type checking
```

Without this, agents commit broken code and report success.

### 7. Conflict Avoidance Rules

When agents work in parallel, explicit rules prevent destructive interference:

```markdown
### Conflict Avoidance

- ONLY modify files within your scope boundary
- Create new files rather than editing shared ones
- Do NOT run formatters on files outside your scope
- Do NOT delete or rename files you did not create
```

### 8. Conditional Context

Include information only when it's relevant. Dependencies, previous attempts, child issues — wrap them in conditionals so the agent doesn't see empty sections or get confused by irrelevant headers.

```jinja2
{% if issue.depends_on %}
## Dependencies

This issue depends on already-completed work:
{% for dep_id in issue.depends_on %}
- {{ dep_id }}
{% endfor %}

Check the repo for files created by these dependencies.
{% endif %}
```

### 9. Previous Failure Context

When an agent retries after a failure, include what went wrong last time. Without this context, the agent repeats the same mistake.

```jinja2
{% if issue.children %}
## Previous Decomposition Attempt

This issue was previously decomposed but came back for rescoping.
Learn from what went wrong:

{% for child in issue.children %}
- **{{ child.fields.title }}** (state: {{ child.state }})
{% endfor %}
{% endif %}
```

### 10. Commit Message Format

Specify the exact commit message format. Agents will invent their own conventions otherwise, making git history unreadable.

```markdown
Commit with message: `plan: {{ issue.fields.title }}`
```

## Orca-Specific Mechanics

### Template Variables

Orca renders prompts as Jinja2 templates. These variables are available in every prompt:

| Variable | Type | Description |
|----------|------|-------------|
| `issue` | dict | Full issue object |
| `issue.fields.*` | varies | Issue fields defined in `orca.yml` (e.g., `title`, `description`, `scope_boundary`) |
| `issue.depends_on` | list | IDs of issues this depends on |
| `issue.children` | list | Child issues from previous decomposition |
| `issue.base_branch` | string | Git branch to merge into |
| `result_format` | dict | Output schema from `orca.yml` |
| `result_path` | string | Absolute path where the agent must write result JSON |

Use Jinja2 filters for formatting:

```jinja2
{{ result_format | tojson(indent=2) }}
{{ issue.fields.title | lower | replace(' ', '-') }}
```

### Result Format

The `result_format` in `orca.yml` defines what the agent must produce. The orchestrator validates this schema and sends correction messages if the output is invalid.

```yaml
result_format:
  outcome:
    type: enum
    values: [ready, needs_rescope]
    description: "Whether the plan is ready"
    values_description:
      ready: "Plan and tests are committed"
      needs_rescope: "Issue needs to go back to scoping"
  summary:
    type: string
    description: "Brief summary of the plan or reason for rescoping"
```

Each `outcome` value maps to a transition in `on:`, which routes the issue to the next state. Design outcomes as meaningful decisions, not just pass/fail.

### Conditional Fields

Use `required_when` to make fields conditional on the outcome:

```yaml
sub_issues:
  type: list
  items: "$issue"
  required_when: [decompose]
  description: "Sub-issues to create (only when decomposing)"
```

### Result File Warning

The orchestrator appends a warning to every rendered prompt automatically:

> **IMPORTANT: Writing the result file is the final action of your session. The orchestrator will terminate this session shortly after detecting the result file. Complete ALL other work — git commits, file writes, code changes — before writing the result file.**

You do not need to include this in your prompt template — it's added by the rendering engine. But you should be aware that any work after the result file is written may be lost.

### Worktree Isolation

Each agent runs in its own git worktree. The agent can freely commit, branch, and modify files without affecting other agents. The `applying` state handles merging back to the base branch.

Design prompts with this in mind:
- The agent's working directory is an isolated copy of the repo
- Other agents' uncommitted work is invisible
- The `base_branch` variable tells the agent where to merge

### Timeouts

Set `timeout` in `orca.yml` to limit how long a worker runs. If the agent might need to know its time budget, include it in the prompt:

```markdown
You have approximately {{ timeout // 60 }} minutes to complete this work.
Prioritize correctness over completeness if time is short.
```

## Prompt Anatomy

A well-structured prompt follows this layout:

```
┌─────────────────────────────────────────┐
│ 1. Role & Mission                       │  One sentence: who you are, what you do
├─────────────────────────────────────────┤
│ 2. Context                              │  Issue fields, dependencies, scope
│    (use conditionals for optional data) │
├─────────────────────────────────────────┤
│ 3. Step-by-Step Instructions            │  Numbered steps with headings
│    - Step 1: Read/understand            │
│    - Step 2: Do the work                │
│    - Step 3: Verify                     │
│    - Step 4: Commit                     │
├─────────────────────────────────────────┤
│ 4. Rules & Constraints                  │  Scope rules, conflict avoidance
├─────────────────────────────────────────┤
│ 5. Output Format                        │  JSON schema + field descriptions
│    (result_path + result_format)        │
├─────────────────────────────────────────┤
│ 6. Result File Warning                  │  (auto-appended by orca)
└─────────────────────────────────────────┘
```

### Example: Minimal Prompt

```markdown
# Review Agent

You are a code review agent. Review the implementation and decide
whether it meets the acceptance criteria.

## Issue

**Title:** {{ issue.fields.title }}

**Scope Boundary:** {{ issue.fields.scope_boundary }}

## Instructions

### Step 1: Read the Plan

Find the implementation plan in `docs/plans/`. Understand what was
supposed to be built.

### Step 2: Read the Implementation

Read all files within the scope boundary. Check for:
- Correctness against the plan
- Test coverage
- Code style and conventions

### Step 3: Run Tests

Run the test suite and verify all tests pass.

### Step 4: Decide

If the implementation matches the plan and tests pass, approve it.
If there are issues, reject with specific feedback.

## Output

Write the result JSON to `{{ result_path }}`:

\`\`\`json
{{ result_format | tojson(indent=2) }}
\`\`\`
```

## Checklist

Use this when writing or reviewing a prompt.

### Clarity

- [ ] Prompt has a single, clear responsibility
- [ ] Role and mission are stated in the first sentence
- [ ] Instructions are numbered steps, not prose paragraphs
- [ ] Each step has a heading or is clearly delineated
- [ ] No ambiguous language ("maybe", "if you want", "consider")

### Scope

- [ ] Scope boundary is explicitly stated using `{{ issue.fields.scope_boundary }}`
- [ ] Conflict avoidance rules are included (if agents run in parallel)
- [ ] Dependencies are shown conditionally (`{% if issue.depends_on %}`)
- [ ] Previous failure context is included (`{% if issue.children %}`)

### Output

- [ ] Result format schema is embedded in the prompt via `{{ result_format | tojson(indent=2) }}`
- [ ] Result path is specified via `{{ result_path }}`
- [ ] Every outcome value maps to a transition in `orca.yml`
- [ ] A fail-safe outcome exists (e.g., `blocked`, `needs_rescope`, `failed`)
- [ ] `required_when` is used for conditional fields
- [ ] Each outcome has a `values_description` in `orca.yml` explaining when to use it

### Verification

- [ ] Agent is told to run tests before committing
- [ ] Agent is told to run linters/formatters/type checks if the project uses them
- [ ] Commit message format is specified
- [ ] Agent commits only files within scope boundary

### Mechanics

- [ ] Result file is written as the last action (no work after it)
- [ ] Jinja2 variables are used for dynamic content (not hardcoded values)
- [ ] Optional sections use `{% if %}` conditionals
- [ ] Timeout is appropriate for the work required (set in `orca.yml`)

## Common Mistakes

**Combining two jobs in one prompt.** A prompt that says "plan the implementation, then implement it" will do both poorly. Split into two states.

**Missing fail-safe outcome.** If the only outcome is `done`, the agent will report `done` even when it's stuck. Always include `blocked`, `failed`, or `needs_rescope`.

**Not including `result_format` in the prompt body.** The agent doesn't automatically know the schema. If you don't render `{{ result_format | tojson(indent=2) }}` in the prompt, the agent guesses the format and gets it wrong.

**Writing result file before committing.** The orchestrator may kill the session within seconds of detecting a valid result file. Any git commits or file writes after that point are lost.

**Hardcoding values that should be dynamic.** Don't write `Commit to branch main` — use `{{ issue.base_branch }}`. Don't write `Edit files in src/auth/` — use `{{ issue.fields.scope_boundary }}`.

**Empty conditional sections.** If `issue.depends_on` is empty and you render `## Dependencies` with no content, it confuses the agent. Wrap the entire section in `{% if issue.depends_on %}`.

**Vague instructions.** "Review the code and make improvements" is not actionable. "Read all files in scope, run the test suite, check for missing error handling" is.

**No verification step.** If the prompt doesn't say "run tests before committing," the agent won't. Always be explicit about verification.
