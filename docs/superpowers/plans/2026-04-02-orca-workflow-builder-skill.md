# Orca Workflow Builder Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a Claude Code skill that enables agents to create, update, and audit orca workflows — producing correct `orca.{flow}.yml` configs and Jinja2 prompt templates as a unit.

**Architecture:** Core skill file (SKILL.md) defines three modes (create/update/audit) and procedures. Four reference docs loaded on-demand: config-reference (schema), workflow-patterns (building blocks), prompt-guide (writing prompts), audit-checklist (review criteria). Also updates orca-manager's prompt-issues.md with a cross-reference entry.

**Tech Stack:** Claude Code skills (markdown with YAML frontmatter), orca config format (YAML), Jinja2 prompt templates

**Spec:** `docs/superpowers/specs/2026-04-02-orca-workflow-builder-skill-design.md`

---

### Task 1: Create core skill file

**Files:**
- Create: `skills/orca-workflow-builder/SKILL.md`

- [ ] **Step 1: Create directory**

```bash
mkdir -p skills/orca-workflow-builder
```

- [ ] **Step 2: Write the core skill file**

Write `skills/orca-workflow-builder/SKILL.md` with this exact content:

````markdown
---
name: building-orca-workflows
description: Use when creating, updating, or auditing orca workflows. Triggers on "create a workflow", "build a flow", "add a state", "fix my orca config", "audit workflow", "check my prompts", or any orca workflow authoring task.
---

# Building Orca Workflows

Create, update, and audit orca workflows. You produce complete packages: `orca.{flow-name}.yml` config + all Jinja2 prompt templates as a unit.

Adaptive to user expertise — if they provide a detailed spec, skip basics. If they say "I want a workflow that does code review," start from scratch.

## Mode Detection

Infer the mode from context:

| Signal | Mode |
|---|---|
| "create a workflow for...", "I need a flow that..." | **Create** |
| "add a state", "fix my config", "change the scoping prompt" | **Update** |
| "check my workflow", "audit orca.develop.yml", "why is this slow" | **Audit** |
| Invoked by orca-manager with worker logs | **Audit** (specific state) |

## Create Mode

Read these reference docs before starting:
- `skills/orca-workflow-builder/config-reference.md` — full schema
- `skills/orca-workflow-builder/workflow-patterns.md` — building blocks
- `skills/orca-workflow-builder/prompt-guide.md` — prompt writing rules

Also read `example/orca.yml` and `example/prompts/` in the orca repo for real-world patterns.

### Process

```
UNDERSTAND GOAL
  What does the user want to accomplish?
  What's the target project? What language/framework?
       │
       ▼
DESIGN STATE MACHINE
  Map goal → states → transitions
  Pick patterns from workflow-patterns.md
  Single-type or multi-type? Where to decompose?
  Set: max_hops, max_worker_retries, max_workers
       │
       ▼
DEFINE ISSUE FIELDS
  What data flows through the workflow?
  Which fields does each state's worker need?
       │
       ▼
WRITE ORCA.{FLOW}.YML
  States, workers, result_formats, on: rules
  Validate against config-reference rules
       │
       ▼
WRITE PROMPT TEMPLATES
  One prompt per active state (prompts/{state}.md)
  Follow prompt-guide.md structure
  Embed: {{ result_format | tojson(indent=2) }}, {{ result_path }}
  Include: scope boundaries, constraints, verification steps
       │
       ▼
VALIDATE
  Check all config-reference validation rules
  All on: targets exist, outcomes match, no unreachable states
```

### Key Decisions

- **Single vs multi-type**: Decomposition (epic → tasks) → multi-type. Linear pipeline → single-type.
- **Where to decompose**: Early = more parallelism. Late = more control.
- **max_workers**: `1` on merge/apply states. Unlimited on parallel-safe states.
- **Fail-safe outcomes**: Every active state needs `blocked` and/or `needs_feedback` beyond success outcomes.
- **Naming**: `orca.{flow-name}.yml` (e.g. `orca.develop.yml`, `orca.prd.yml`).

## Update Mode

```
READ EXISTING
  Parse orca.{flow}.yml + all prompt templates
  Understand: states, transitions, field flow
       │
       ▼
UNDERSTAND CHANGE
  Add state? Change transition? Fix error? Optimize prompt?
       │
       ▼
ASSESS IMPACT
  Adding state → need prompt, on: rules pointing to it
  Changing result_format → prompt must match
  Removing outcome → check all on: rules
       │
       ▼
APPLY AS UNIT
  Config + prompts always change together
  Never commit config without corresponding prompt update
       │
       ▼
VALIDATE
  Check config-reference rules, no broken transitions
```

**Critical rule:** Config and prompts are a unit. If `result_format` changes, the prompt that tells the worker what to produce must change too.

## Audit Mode

Read `skills/orca-workflow-builder/audit-checklist.md` before auditing.

```
READ WORKFLOW
  Parse orca.{flow}.yml + all prompt templates
       │
       ▼
RUN THREE-LAYER CHECKLIST
  1. Structural — will it break?
  2. Efficiency — anti-patterns?
  3. Prompt quality — will workers struggle?
       │
       ▼
REPORT FINDINGS
  Critical / Important / Minor
  File:line references, specific fix suggestions
       │
       ▼
FIX (if authorized)
  From orca-manager: respect autonomy level
  From user: present findings, ask before fixing
```

### Autonomy (when invoked by orca-manager)

- `cautious` — report only
- `supervised` — apply checklist fixes, escalate novel issues
- `full` — apply any diagnosed fix

### Test Run Integration

After creating/updating a workflow, offer to test it:

> "Workflow ready. Want me to start a test run? I'll use the orca-manager skill to run and monitor it."

Read `skills/orca-manager/SKILL.md` for single-flow monitoring. If the test surfaces issues, fix them — a create-test-fix loop.
````

- [ ] **Step 3: Commit**

```bash
git add skills/orca-workflow-builder/SKILL.md
git commit -m "feat(skills): add orca-workflow-builder core skill"
```

---

### Task 2: Create config reference

**Files:**
- Create: `skills/orca-workflow-builder/config-reference.md`

This task is independent of Tasks 3, 4, and 5 — they can run in parallel.

- [ ] **Step 1: Write the config reference**

Write `skills/orca-workflow-builder/config-reference.md` with this exact content:

````markdown
# Orca Config Reference

Full `orca.{flow-name}.yml` schema. Use as lookup when creating or validating workflows.

## Top-Level Structure

Two formats supported:

**Typed (recommended):**
```yaml
root_type: feature
max_hops: 10
max_worker_retries: 5
base_branch: origin/main
types:
  feature:
    fields: { ... }
    initial: planning
    states: { ... }
  task:
    fields: { ... }
    initial: implementing
    states: { ... }
integrations:
  slack:
    bot_token_env: SLACK_BOT_TOKEN
    app_token_env: SLACK_APP_TOKEN
```

**Legacy (single-type, auto-wrapped as type "default"):**
```yaml
issue:
  fields: { ... }
initial: planning
states: { ... }
max_hops: 10
```

## Global Fields

| Field | Type | Required | Description |
|---|---|---|---|
| `root_type` | string | yes (typed) | Must match a key in `types:` |
| `max_hops` | positive int | no | Max state transitions per issue. Prevents infinite loops |
| `max_worker_retries` | positive int | no | Max worker failures per issue in same state before giving up |
| `base_branch` | string | no | Default git branch for merging. Available as `{{ issue.base_branch }}` |
| `integrations` | object | no | Slack config for `needs_feedback` |

## Type Definition

Each type has its own independent state machine.

```yaml
types:
  feature:
    fields:
      title:
        type: string
        description: "Feature title"
      scope_boundary:
        type: string
        description: "Files this feature owns"
      priority:
        type: enum
        values: [high, medium, low]
        description: "Priority level"
    initial: planning      # Required. Must be a key in states:
    states:
      planning: { ... }
      implementing: { ... }
```

### Field Types

| Type | Description | Extra Fields |
|---|---|---|
| `string` | Arbitrary text | `description` |
| `enum` | Predefined values | `values`, `description` |

### Auto-Populated Fields

These are set by the orchestrator, not the user. Define them in `fields:` if your prompts need them:

| Field | Set When | Contains |
|---|---|---|
| `feedback_questions` | Worker returns `needs_feedback` | Questions the worker asked |
| `feedback_context` | User answers via Slack | User's answers |
| `failure_context` | Worker fails | Error message from last failure |
| `base_branch` | Run starts | Git branch for merging |

## State Definition

```yaml
states:
  implementing:
    max_workers: 1          # Optional. Concurrent worker limit for this (type, state) pair
    worker:                  # Optional. If absent, state is passive (manual advance only)
      kind: claude-code      # Required. "claude-code" or "opencode"
      prompt: prompts/impl.md  # Required. Jinja2 template path (relative to repo root)
      timeout: 1200          # Optional. Hard kill after N seconds
      inactivity_timeout: 300  # Optional. Kill if no result file for N seconds. Default: 300
      model: claude-3-5-sonnet  # Optional. Override worker model
      args: ["--max-turns", "100"]  # Optional. Extra CLI args
      progress: true         # Optional. Enable PROGRESS: <pct> | <status> reporting
      result_format:         # Required if worker present
        outcome:             # Required. Must be enum type
          type: enum
          values: [done, blocked, needs_feedback]
          description: "Result"
          values_description:
            done: "Complete"
            blocked: "Cannot proceed"
            needs_feedback: "Need user input"
        summary:
          type: string
          description: "Brief summary"
          required_when: [blocked]  # Only required when outcome matches
        sub_issues:
          type: list
          items: "$issue"    # Special: each item is a full issue for decomposition
          required_when: [decompose]
    on:                      # Optional. Routing rules based on outcome
      done: testing          # Transition: outcome → target state
      blocked: planning      # Can loop back
      # needs_feedback — reserved, no rule needed
```

### State Types

| Type | Has worker? | Has on:? | Behavior |
|---|---|---|---|
| Active | yes | yes | Worker runs, outcome routes to next state |
| Passive | no | no | Issue waits for manual `AdvanceEvent` |

## On: Rules

### Transition Rule

```yaml
on:
  done: testing            # outcome "done" → move to state "testing"
  blocked: planning        # outcome "blocked" → move to state "planning"
```

Target must be a state name or built-in state (`done`, `failed`).

### Decompose Rule

```yaml
on:
  decompose:
    action: decompose      # Required
    child_type: task       # Optional. Type for child issues. Defaults to root_type
    then: done             # Optional. Parent transitions here after creating children
                           # If omitted, parent blocks until all children reach "done"
```

Requires `sub_issues` with `items: "$issue"` in `result_format`.

## Built-in States

Always available. Never define them in `states:`.

| State | Behavior |
|---|---|
| `done` | Terminal. Issue stays here permanently. Triggers cascading unblock of parents/dependents. |
| `failed` | Not actually visited. Using `on: { outcome: failed }` triggers worker failure/retry semantics. |

## Reserved Outcomes

| Outcome | Behavior |
|---|---|
| `needs_feedback` | No `on:` rule needed. Orchestrator spawns Slack feedback agent, re-dispatches worker with `feedback_context` after user answers. Increments `failure_count`. |

## Multi-Flow Convention

A project can have many workflows: `orca.{flow-name}.yml`

Examples: `orca.develop.yml`, `orca.prd.yml`, `orca.qa-spec.yml`, `orca.investigate.yml`

## Validation Rules

The config parser enforces all of these. A workflow that violates any rule will fail to load.

| Rule | Constraint |
|---|---|
| Root type exists | `root_type` must be a key in `types:` |
| Initial state exists | `initial` must be a key in `states:` |
| On targets exist | Every transition target must be in `states:` or built-in states |
| Outcomes match | Every `on:` key must be a value in `result_format.outcome.values` |
| Active state routing | States with worker + on: must have `outcome` enum in result_format |
| At least one routable outcome | State must have ≥1 non-reserved outcome with an `on:` rule |
| Valid worker kind | Must be `claude-code` or `opencode` |
| Non-empty prompt | `worker.prompt` required if worker defined |
| Positive timeouts | `timeout`, `inactivity_timeout` must be positive integers |
| Positive max_workers | `max_workers` must be positive integer |
| Positive max_hops | `max_hops` must be positive integer |
| Decompose requires sub_issues | If `on:` has decompose action, result_format needs `sub_issues` with `items: "$issue"` |
| Decompose child_type exists | `child_type` must be a key in `types:` (if specified) |
| Decompose then target exists | `then` target must be in states or built-in states |
| Reserved names protected | Cannot define states named `done` or `failed` |
| No unreachable states | Non-initial, non-passive states must be reachable from initial via on: rules |
````

- [ ] **Step 2: Commit**

```bash
git add skills/orca-workflow-builder/config-reference.md
git commit -m "feat(skills): add orca-workflow-builder config reference"
```

---

### Task 3: Create workflow patterns

**Files:**
- Create: `skills/orca-workflow-builder/workflow-patterns.md`

This task is independent of Tasks 2, 4, and 5.

- [ ] **Step 1: Write the workflow patterns**

Write `skills/orca-workflow-builder/workflow-patterns.md` with this exact content:

````markdown
# Workflow Patterns

Reusable building blocks for orca workflows. Compose these into complete workflows. Each pattern shows when to use it, a config snippet, and notes.

Also read `example/orca.yml` and `example/prompts/` in the orca repo for a complete real-world workflow.

## Sequential Pipeline

**When:** Simple linear flow — one issue progresses through stages.

```yaml
initial: planning
states:
  planning:
    worker:
      kind: claude-code
      prompt: prompts/planning.md
      result_format:
        outcome:
          type: enum
          values: [ready, blocked]
    on:
      ready: implementing
      blocked: planning
  implementing:
    worker:
      kind: claude-code
      prompt: prompts/implementing.md
      result_format:
        outcome:
          type: enum
          values: [done, blocked]
    on:
      done: done
      blocked: planning
```

**Notes:**
- Each state has one clear job
- `blocked` loops back for human intervention or retry
- Add more states in the middle as needed (testing, review, applying)

## Decompose + Parallel Execution

**When:** Large task needs to be broken into independent sub-tasks that run in parallel.

```yaml
root_type: epic
types:
  epic:
    fields:
      title: { type: string, description: "Epic title" }
      description: { type: string, description: "What to build" }
    initial: scoping
    states:
      scoping:
        worker:
          kind: claude-code
          prompt: prompts/scoping.md
          result_format:
            outcome:
              type: enum
              values: [decompose, ready]
              values_description:
                decompose: "Break into sub-tasks"
                ready: "Small enough to implement directly"
            sub_issues:
              type: list
              items: "$issue"
              required_when: [decompose]
        on:
          decompose:
            action: decompose
            child_type: task
            then: done
          ready: done
  task:
    fields:
      title: { type: string, description: "Task title" }
      scope_boundary: { type: string, description: "Files this task owns" }
    initial: implementing
    states:
      implementing:
        worker:
          kind: claude-code
          prompt: prompts/implementing.md
          result_format:
            outcome:
              type: enum
              values: [done, blocked, needs_feedback]
        on:
          done: applying
          blocked: implementing
      applying:
        max_workers: 1
        worker:
          kind: claude-code
          prompt: prompts/applying.md
          result_format:
            outcome:
              type: enum
              values: [applied, failed]
        on:
          applied: done
          failed: implementing
```

**Notes:**
- Epic scoping creates child tasks with clear scope boundaries
- Tasks run in parallel (no max_workers on implementing)
- Applying serialized with `max_workers: 1` to prevent merge conflicts
- Epic auto-unblocks when all tasks reach `done`

## Serialized Merge

**When:** A state where only one worker should run at a time (merging, deploying, writing to shared resource).

```yaml
applying:
  max_workers: 1
  worker:
    kind: claude-code
    prompt: prompts/applying.md
    timeout: 600
    result_format:
      outcome:
        type: enum
        values: [applied, conflict]
  on:
    applied: done
    conflict: implementing
```

**Notes:**
- `max_workers: 1` queues issues — next pops when current finishes
- Limit is per (type, state) pair — different types have separate queues
- Set a reasonable `timeout` since queued issues wait

## Retry Loop with Escalation

**When:** Work might fail and should be retried with context about the failure.

```yaml
max_worker_retries: 3

states:
  implementing:
    worker:
      kind: claude-code
      prompt: prompts/implementing.md
      result_format:
        outcome:
          type: enum
          values: [done, blocked, needs_feedback]
        blockers:
          type: string
          description: "What's blocking progress"
          required_when: [blocked]
    on:
      done: done
      blocked: implementing
```

**Notes:**
- `blocked` loops back to same state — worker gets another attempt
- Define `failure_context` field so prompts can reference why previous attempt failed
- `max_worker_retries` bounds total failures (prevents infinite loops)
- Worker failures (crashes/timeouts) also count toward the limit
- `needs_feedback` pauses for user input, then re-dispatches

## Feedback Loop

**When:** Worker might need human clarification mid-workflow.

```yaml
implementing:
  worker:
    kind: claude-code
    prompt: prompts/implementing.md
    result_format:
      outcome:
        type: enum
        values: [done, blocked, needs_feedback]
        values_description:
          needs_feedback: "Need user clarification before proceeding"
  on:
    done: done
    blocked: implementing
    # needs_feedback has no on: rule — orchestrator handles it
```

**Notes:**
- `needs_feedback` is reserved — no `on:` rule needed
- Orchestrator spawns Slack feedback agent automatically
- After user answers, worker re-dispatches with `{{ issue.feedback_context }}`
- Define `feedback_questions` and `feedback_context` fields if prompts reference them
- Requires Slack integration configured at top level

## Multi-Type Hierarchy

**When:** Different kinds of work follow different workflows (e.g. epic → story → task).

```yaml
root_type: epic
types:
  epic:
    fields:
      title: { type: string }
    initial: planning
    states:
      planning:
        worker:
          kind: claude-code
          prompt: prompts/plan_epic.md
          result_format:
            outcome:
              type: enum
              values: [decompose]
            sub_issues:
              type: list
              items: "$issue"
              required_when: [decompose]
        on:
          decompose:
            action: decompose
            child_type: story
            then: done
  story:
    fields:
      title: { type: string }
      scope_boundary: { type: string }
    initial: implementing
    states:
      implementing:
        worker:
          kind: claude-code
          prompt: prompts/impl_story.md
          result_format:
            outcome:
              type: enum
              values: [done, decompose]
            sub_issues:
              type: list
              items: "$issue"
              required_when: [decompose]
        on:
          done: done
          decompose:
            action: decompose
            child_type: task
            then: done
  task:
    fields:
      title: { type: string }
      scope_boundary: { type: string }
    initial: coding
    states:
      coding:
        worker:
          kind: claude-code
          prompt: prompts/code_task.md
          result_format:
            outcome:
              type: enum
              values: [done, blocked]
        on:
          done: done
          blocked: coding
```

**Notes:**
- Each type has its own state machine — epic plans, story implements or decomposes further, task codes
- `child_type` controls what type decomposed issues become
- Parent blocks until all children reach `done` (cascading unblock)
- Sub-issues can have `depends_on` keys for ordering within a type

## Gate State

**When:** Workflow needs a human approval point or manual trigger before proceeding.

```yaml
states:
  review:
    # No worker, no on: rules — passive state
    # Issue waits here until manually advanced via AdvanceEvent
  deploying:
    worker: { ... }
    on:
      done: done
```

**Notes:**
- Passive states have no worker and no `on:` rules
- Issue is advanced manually (via API, TUI, or CLI)
- Use for: code review gates, deployment approval, manual QA sign-off
- Passive states are exempt from the "unreachable states" validation (they can be targets of on: rules)

## Iterative Refinement

**When:** Work goes through review cycles — implement, review, rework until approved.

```yaml
states:
  implementing:
    worker:
      kind: claude-code
      prompt: prompts/implementing.md
      result_format:
        outcome:
          type: enum
          values: [ready_for_review, blocked]
    on:
      ready_for_review: reviewing
      blocked: implementing
  reviewing:
    worker:
      kind: claude-code
      prompt: prompts/reviewing.md
      result_format:
        outcome:
          type: enum
          values: [approved, needs_rework]
    on:
      approved: done
      needs_rework: implementing
```

**Notes:**
- `needs_rework` loops back to implementing with review feedback
- Use `max_hops` to bound the cycle (e.g. 10 hops prevents infinite back-and-forth)
- Review worker should produce specific, actionable feedback (not just "needs work")
- Implementing worker should reference `{{ issue.event_log }}` to see previous review feedback
````

- [ ] **Step 2: Commit**

```bash
git add skills/orca-workflow-builder/workflow-patterns.md
git commit -m "feat(skills): add orca-workflow-builder workflow patterns"
```

---

### Task 4: Create prompt guide

**Files:**
- Create: `skills/orca-workflow-builder/prompt-guide.md`

This task is independent of Tasks 2, 3, and 5.

- [ ] **Step 1: Write the prompt guide**

Write `skills/orca-workflow-builder/prompt-guide.md` with this exact content:

````markdown
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
````

- [ ] **Step 2: Commit**

```bash
git add skills/orca-workflow-builder/prompt-guide.md
git commit -m "feat(skills): add orca-workflow-builder prompt guide"
```

---

### Task 5: Create audit checklist

**Files:**
- Create: `skills/orca-workflow-builder/audit-checklist.md`

This task is independent of Tasks 2, 3, and 4.

- [ ] **Step 1: Write the audit checklist**

Write `skills/orca-workflow-builder/audit-checklist.md` with this exact content:

````markdown
# Audit Checklist

Three-layer audit for orca workflows. Run all checks against `orca.{flow}.yml` and its prompt templates. Report findings as critical (will break), important (anti-pattern), or minor (could be better).

## Layer 1: Structural Checks

These catch config errors that will cause runtime failures.

- [ ] **All on: targets exist** — every transition target is a state name or built-in state (`done`, `failed`). Check both simple transitions (`done: testing`) and decompose rules (`then: done`).

- [ ] **Outcomes match on: keys** — every key in `on:` must be a value in `result_format.outcome.values`. If `on:` says `ready: planning` but outcome values don't include `ready`, config will fail to load.

- [ ] **At least one routable outcome** — every active state has ≥1 non-reserved outcome with an `on:` rule. A state with only `needs_feedback` as its outcome cannot progress.

- [ ] **Decompose has sub_issues** — any state with `on: { X: { action: decompose } }` must have `sub_issues: { type: list, items: "$issue" }` in its `result_format`.

- [ ] **Decompose child_type exists** — if `child_type: task` is specified, `task` must be a key in `types:`.

- [ ] **No reserved state names** — no states named `done` or `failed` in the `states:` block.

- [ ] **All states reachable** — every non-initial, non-passive state can be reached from the initial state via `on:` rules. Passive states (no worker, no on:) are exempt.

- [ ] **Worker kind valid** — `kind` is `claude-code` or `opencode`.

- [ ] **Worker prompt non-empty** — `prompt` field is present and non-empty for every worker.

- [ ] **Prompt files exist** — every `worker.prompt` path points to an actual file. Check with `ls <path>`.

## Layer 2: Efficiency Checks

These catch anti-patterns that waste time or cause confusing behavior.

- [ ] **Single responsibility per state** — no state's prompt does two distinct jobs (e.g. "plan and implement"). If a prompt has two major phases, split into two states.

- [ ] **Fail-safe outcomes present** — every active state has `blocked`, `needs_feedback`, or some escape hatch beyond the happy-path outcome. Without this, workers report "done" even when stuck.

- [ ] **Merge/apply states serialized** — states that merge branches or write to shared resources have `max_workers: 1`. Without this, concurrent merges cause conflicts.

- [ ] **max_hops is set** — global `max_hops` prevents infinite state transition loops. Recommended: 10-20 depending on workflow complexity.

- [ ] **max_worker_retries is set** — prevents infinite failure retries. Recommended: 3-5.

- [ ] **Timeouts set for long states** — states where workers do heavy work (implementing, testing) should have `timeout` or `inactivity_timeout`. Default inactivity timeout is 300s (5 min) which may be too short for complex tasks.

- [ ] **Decomposition scope boundaries** — when a state decomposes issues, the prompt instructs the worker to define clear, non-overlapping `scope_boundary` fields for sub-issues. Overlapping scopes cause workers to edit each other's files.

- [ ] **No unnecessary serialization** — `max_workers: 1` only on states that genuinely need it (merging, deploying). Serializing implementation or planning states wastes time.

## Layer 3: Prompt Quality Checks

These catch prompt issues that cause worker failures or poor output.

- [ ] **result_format embedded** — prompt contains `{{ result_format | tojson(indent=2) }}` or shows the exact JSON schema the worker must produce. Workers that guess the format produce invalid results.

- [ ] **result_path referenced** — prompt contains `{{ result_path }}` telling the worker where to write the result file.

- [ ] **Constraints near end** — constraints are in a dedicated `## Constraints` section in the bottom half of the prompt, not buried in the introduction. Workers forget early constraints.

- [ ] **No hardcoded values** — values that come from issue fields use `{{ issue.fields.* }}` template variables, not hardcoded strings. Especially: scope boundaries, branch names, file paths.

- [ ] **Verification step present** — prompt includes a step to verify work (run tests, lint, typecheck) before committing. Without this, workers produce untested code.

- [ ] **Commit before result** — prompt explicitly says to commit all changes before writing the result file. The orchestrator kills the session ~30s after detecting a valid result.

- [ ] **Scope boundary enforced** — if `scope_boundary` field exists, prompt has a constraint like "ONLY modify files under {{ issue.fields.scope_boundary }}."

- [ ] **Conditional sections guarded** — sections that reference optional data (feedback_context, depends_on, children) use `{% if %}` guards so they don't render as empty headers.

- [ ] **Single clear responsibility** — prompt describes one job. If you find phrases like "first do X, then do Y" where X and Y are different kinds of work, the state should be split.

- [ ] **Result file is final action** — prompt says writing the result file is the last thing the worker does. No work planned after it.

## Reporting Format

After running all checks, report like this:

```
## Audit: orca.develop.yml

### Critical
- [structural] State "reviewing" not reachable from initial state "planning" — no on: rule targets it
- [structural] prompts/implementing.md does not exist (referenced by implementing.worker.prompt)

### Important
- [efficiency] State "implementing" has no fail-safe outcome — only [done]. Add "blocked" or "needs_feedback"
- [prompt] prompts/scoping.md:L45 — result_format not embedded. Workers will guess JSON shape.

### Minor
- [prompt] prompts/planning.md:L12 — hardcoded "src/auth/" instead of {{ issue.fields.scope_boundary }}
- [efficiency] No inactivity_timeout on implementing state (uses default 300s — may be too short)
```
````

- [ ] **Step 2: Commit**

```bash
git add skills/orca-workflow-builder/audit-checklist.md
git commit -m "feat(skills): add orca-workflow-builder audit checklist"
```

---

### Task 6: Update orca-manager prompt-issues.md

**Files:**
- Modify: `skills/orca-manager/prompt-issues.md`

- [ ] **Step 1: Add cross-reference entry**

Append this entry to the end of `skills/orca-manager/prompt-issues.md`, after the "Worker misunderstands decomposition" section:

```markdown

## Deep Analysis

### Problem beyond catalog fixes

**Pattern:** Issue persists after applying catalog fixes from this document, or the problem is novel and doesn't match any entry above.
**Root cause:** Structural workflow config or prompt issue requiring deeper analysis than pattern matching.
**Fix:** Invoke the orca-workflow-builder skill in audit mode on the affected flow/state. Read `skills/orca-workflow-builder/SKILL.md` and pass the worker logs and your diagnosis as context. The builder will run its three-layer audit checklist and apply targeted fixes.
**Applies to:** Any workflow when catalog fixes are insufficient
**Risk:** low (audit), medium (fixes)
```

- [ ] **Step 2: Commit**

```bash
git add skills/orca-manager/prompt-issues.md
git commit -m "feat(skills): add workflow-builder cross-reference to orca-manager"
```

---

### Task 7: Register skill in CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add skill reference**

In the `## Skills` section of `CLAUDE.md`, add a second bullet:

```markdown
- `skills/orca-workflow-builder/` — Orca workflow authoring skill. Invoke when creating, updating, or auditing orca workflows and prompt templates.
```

The section should now read:

```markdown
## Skills

- `skills/orca-manager/` — Autonomous orca workflow management skill. Invoke by asking the agent to manage orca workflows or by reading `skills/orca-manager/SKILL.md`.
- `skills/orca-workflow-builder/` — Orca workflow authoring skill. Invoke when creating, updating, or auditing orca workflows and prompt templates.
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: register orca-workflow-builder skill in CLAUDE.md"
```

---

### Task 8: Verify skill structure

**Files:**
- Read: all files in `skills/orca-workflow-builder/`
- Read: `skills/orca-manager/prompt-issues.md` (check cross-reference)
- Read: `CLAUDE.md` (check registration)

- [ ] **Step 1: Verify directory structure**

```bash
find skills/orca-workflow-builder/ -type f | sort
```

Expected:
```
skills/orca-workflow-builder/SKILL.md
skills/orca-workflow-builder/audit-checklist.md
skills/orca-workflow-builder/config-reference.md
skills/orca-workflow-builder/prompt-guide.md
skills/orca-workflow-builder/workflow-patterns.md
```

- [ ] **Step 2: Verify SKILL.md frontmatter**

```bash
head -4 skills/orca-workflow-builder/SKILL.md
```

Expected:
```
---
name: building-orca-workflows
description: Use when creating, updating, or auditing orca workflows. Triggers on "create a workflow", "build a flow", "add a state", "fix my orca config", "audit workflow", "check my prompts", or any orca workflow authoring task.
---
```

- [ ] **Step 3: Verify reference doc entry counts**

Count `### ` headings in each reference doc:
- `config-reference.md` — schema reference (sections, not discrete entries)
- `workflow-patterns.md` — 8 patterns (Sequential Pipeline, Decompose+Parallel, Serialized Merge, Retry Loop, Feedback Loop, Multi-Type Hierarchy, Gate State, Iterative Refinement)
- `prompt-guide.md` — 10 pitfalls numbered 1-10
- `audit-checklist.md` — 3 layers with 10 + 8 + 10 = 28 total checks

- [ ] **Step 4: Verify orca-manager cross-reference**

```bash
grep "beyond catalog" skills/orca-manager/prompt-issues.md
```

Expected: shows "Problem beyond catalog fixes" entry.

- [ ] **Step 5: Verify CLAUDE.md**

```bash
grep "workflow-builder" CLAUDE.md
```

Expected: shows the orca-workflow-builder skill registration.
