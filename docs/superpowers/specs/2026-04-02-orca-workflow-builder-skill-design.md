# Orca Workflow Builder Skill — Design Spec

## Overview

A Claude Code skill that enables an agent to create, update, and audit orca workflows. The agent understands orca's full config surface area (states, transitions, worker protocol, result formats, Jinja2 prompts) and applies best practices to produce correct, efficient, well-prompted workflows.

The skill is adaptive — it works for users who've never written an orca workflow and for experts who want faster iteration. It delivers complete packages: `orca.{flow}.yml` config + all prompt templates as a unit.

## Architecture

### Skill File Layout

```
skills/
  orca-workflow-builder/
    SKILL.md                   # Core skill — three modes + procedures
    config-reference.md        # Full orca.yml schema, validation, field types
    workflow-patterns.md       # Reusable workflow building blocks
    prompt-guide.md            # Effective prompt writing, template vars, anti-patterns
    audit-checklist.md         # Structural, efficiency, prompt quality checks
```

The core skill is loaded on invocation. Reference docs are read on-demand based on mode.

### Runtime Context

- The agent may run from the **orca repo** (when invoked by orca-manager) or from the **target project repo** (when invoked directly by user).
- Workflows live in the target project: `orca.{flow-name}.yml` at the repo root, prompts in `prompts/`.
- The `example/` directory in the orca repo serves as a living reference for real-world patterns.

## Three Modes

### 1. Create Mode

User describes a goal, agent builds `orca.{flow}.yml` + prompt templates from scratch.

```
UNDERSTAND GOAL
  What does the user want to accomplish?
  What's the target project? What does it do?
       │
       ▼
DESIGN STATE MACHINE
  Read workflow-patterns.md for building blocks
  Map goal → states → transitions
  Decide: single-type or multi-type?
  Set limits: max_hops, max_worker_retries, max_workers
       │
       ▼
DEFINE ISSUE FIELDS
  Read config-reference.md for field types
  What data flows through the workflow?
  Which fields does each state's worker need?
       │
       ▼
WRITE ORCA.{FLOW}.YML
  Config-first: states, workers, result_formats, on: rules
  Validate against config-reference rules
       │
       ▼
WRITE PROMPT TEMPLATES
  Read prompt-guide.md for structure/anti-patterns
  One prompt per active state
  Embed: {{ result_format | tojson(indent=2) }}, {{ result_path }}
  Include: scope boundaries, constraints, verification steps
       │
       ▼
VALIDATE
  Mental check against validation rules in config-reference
  Verify: all on: targets exist, outcomes match, no unreachable states
```

**Key decisions the agent makes:**

- **Single vs multi-type**: If the workflow decomposes work (e.g. epic → tasks), use multi-type. If it's a linear pipeline on one issue, use single-type.
- **Where to decompose**: Early decomposition (scoping state) creates parallelism. Late decomposition limits it. Agent advises based on the task.
- **max_workers placement**: Serialization states (like "applying" for merges) need `max_workers: 1`. Parallel states (like "implementing") leave it unlimited.
- **Fail-safe outcomes**: Every active state gets at least `blocked` and/or `needs_feedback` in addition to success outcomes.
- **Flow naming**: Workflows are named `orca.{flow-name}.yml` (e.g. `orca.develop.yml`, `orca.prd.yml`). A project can have many flows.

### 2. Update Mode

User wants to modify an existing workflow — add states, change transitions, fix config errors, optimize prompts.

```
READ EXISTING WORKFLOW
  Parse orca.{flow}.yml
  Read all referenced prompt templates
  Build mental model: states, transitions, field flow
       │
       ▼
UNDERSTAND CHANGE
  What does the user want to change?
  Classify: add state, change transition, fix config error,
            optimize prompt, add outcome, restructure
       │
       ▼
ASSESS IMPACT
  What else breaks if we change this?
  - Adding a state: need prompt template, on: rules pointing to it
  - Changing result_format: prompt must be updated to match
  - Removing an outcome: check all on: rules referencing it
  - Adding a type: needs fields, initial state, full state machine
       │
       ▼
APPLY CHANGES
  Config and prompts updated as a unit (never one without the other)
  If result_format changes → prompt changes
  If state added → prompt created, transitions wired
       │
       ▼
VALIDATE
  Check against config-reference validation rules
  Verify no orphaned states, no broken transitions
```

**The "config and prompts are a unit" rule is critical.** If the agent changes `result_format` in a state's worker config, it must also update the prompt template that instructs the worker what to produce. Never commit a config change without the corresponding prompt change.

### 3. Audit Mode

Agent reviews an existing workflow against the audit checklist, reports findings, and optionally fixes issues.

```
READ WORKFLOW
  Parse orca.{flow}.yml + all prompt templates
  If multiple flows exist, audit each or the one specified
       │
       ▼
RUN CHECKLIST
  Read audit-checklist.md
  Three layers: structural, efficiency, prompt quality
       │
       ▼
REPORT FINDINGS
  Categorize: critical (will break), important (anti-pattern),
              minor (could be better)
  Include: file:line references, specific fix suggestions
       │
       ▼
FIX (if authorized)
  If invoked by orca-manager at supervised/full autonomy → apply fixes
  If invoked by user → present findings, ask before fixing
```

**Three audit layers:**

1. **Structural** — config validation errors, unreachable states, mismatched outcome/on: rules, missing result_format fields, decompose without sub_issues, reserved state names redefined.
2. **Efficiency** — states combining two jobs, missing fail-safe outcomes (no `blocked`/`needs_feedback`), no `max_workers` on merge/apply states, excessive `max_hops`, missing `timeout`/`inactivity_timeout`.
3. **Prompt quality** — result_format not embedded in prompt, constraints buried at top instead of near end, hardcoded values instead of `{{ issue.fields.* }}`, no verification step, no commit-before-result instruction, missing scope boundary enforcement, empty sections from missing `{% if %}` guards.

## Mode Detection

The agent infers the mode from context:

| User says | Mode |
|---|---|
| "create a workflow for...", "I need a flow that..." | Create |
| "add a review state", "fix my orca config", "the scoping prompt is wrong" | Update |
| "check my workflow", "why is implementing slow", "audit orca.develop.yml" | Audit |
| (invoked by orca-manager with worker logs) | Audit (on specific state) |

## Reference Doc Structures

### `config-reference.md`

Full orca.yml schema as a lookup reference, not a tutorial. Covers:

- Top-level fields: `root_type`, `types`, `max_hops`, `max_worker_retries`, `base_branch`, `integrations`
- Type definition: `fields` (string, enum types), `initial`, `states`
- State definition: `worker`, `on`, `max_workers`
- Worker config: `kind` (claude-code, opencode), `prompt`, `timeout`, `inactivity_timeout`, `model`, `args`, `progress`, `result_format`
- Result format field types: `enum` (with `values`, `values_description`), `string` (with `required_when`), `list` (with `items: "$issue"` for decomposition)
- On: rules: transition rules (`outcome: target_state`) and decompose rules (`action: decompose`, `child_type`, `then`)
- Built-in states: `done` (terminal), `failed` (triggers retry logic)
- Reserved outcomes: `needs_feedback` (no on: rule needed, handled by orchestrator)
- Validation rules table: every constraint the config parser enforces
- Multi-flow naming: `orca.{flow-name}.yml`
- Special auto-populated fields: `feedback_questions`, `feedback_context`, `failure_context`, `base_branch`

### `workflow-patterns.md`

Reusable building blocks with config snippets and usage guidance. Each pattern has: when to use, config example, notes.

Patterns (~8):
- **Sequential pipeline** — state A → B → C → done. Simplest pattern, one issue flows linearly.
- **Decompose + parallel execution** — scoping decomposes into child tasks that run in parallel. Parent blocks until all children done.
- **Serialized merge** — `max_workers: 1` on apply/merge state. Prevents concurrent merge conflicts.
- **Retry loop with escalation** — blocked outcome loops back with failure context. Combined with `max_worker_retries` to bound retries.
- **Feedback loop** — `needs_feedback` outcome spawns Slack agent, re-dispatches with user's answer.
- **Multi-type hierarchy** — epic → story → task, each type has its own state machine.
- **Gate state** — passive state (no worker, no on:) for manual advance/approval.
- **Iterative refinement** — review → rework cycle with `max_visits` to bound iterations.

Also references the `example/` directory in the orca repo as a living reference for real-world patterns.

### `prompt-guide.md`

Rules and examples for writing effective orca worker prompts. Covers:

- **Prompt anatomy**: role & mission, context (issue fields), instructions (numbered steps), constraints, verification, result format
- **Template variables**: full reference of `issue.fields.*`, `result_format`, `result_path`, `run.*`, `issue.depends_on`, `issue.children`, `issue.feedback_context`, `issue.event_log`, `issue.base_branch`, `issue.decomposed_from`
- **Jinja2 usage**: filters (`tojson`, `length`, `join`), conditionals (`{% if %}`), loops (`{% for %}`), conditional sections to avoid empty headers
- **The 10 pitfalls** (with before/after examples):
  1. No fail-safe outcome — only `done`, no way to report problems
  2. Combining two jobs in one prompt — plan+implement in one state
  3. Not embedding result_format — worker guesses JSON shape
  4. Writing result file before committing — session killed before commit
  5. Hardcoding values instead of template variables
  6. Missing scope boundary enforcement
  7. No verification steps (tests, lint, typecheck)
  8. Unreachable states in config
  9. Decompose without sub_issues in result_format
  10. Infinite loops without max_hops
- **Single responsibility rule**: one job per prompt, split if doing two things
- **Constraint placement**: dedicated section near end, imperative language
- **Commit-before-result ordering**: always commit, then write result as final action

### `audit-checklist.md`

Three-layer audit organized as a runnable checklist. Each check has: what to look for, why it matters, how to fix.

**Structural checks (~10):**
- All on: targets exist in states or built-in states
- All on: keys match result_format.outcome.values
- Every active state has at least one routable (non-reserved) outcome
- Decompose states have sub_issues with items: "$issue"
- Decompose child_type exists in types (if specified)
- No states named "done" or "failed" (reserved)
- All non-initial states reachable from initial via on: rules
- Worker kind is "claude-code" or "opencode"
- Worker prompt path is non-empty
- Timeout values are positive integers

**Efficiency checks (~8):**
- No state combines two distinct responsibilities
- Active states have fail-safe outcomes (blocked/needs_feedback)
- Merge/apply states have max_workers: 1
- max_hops is set (prevents infinite loops)
- max_worker_retries is set (prevents infinite failure retries)
- Timeout/inactivity_timeout set for long-running states
- Decomposition creates clear, non-overlapping scope boundaries
- No unnecessary serialization (max_workers: 1 only where needed)

**Prompt quality checks (~10):**
- result_format embedded via `{{ result_format | tojson(indent=2) }}`
- result_path referenced via `{{ result_path }}`
- Constraints in dedicated section near end of prompt
- No hardcoded values that should be `{{ issue.fields.* }}`
- Verification step present (test, lint, typecheck)
- Commit instruction before result file write
- Scope boundary enforced if `scope_boundary` field exists
- Conditional sections use `{% if %}` guards (no empty headers)
- Single clear responsibility (not doing two jobs)
- Result file instruction as final step

## Integration with orca-manager

### Manager → Builder

When orca-manager diagnoses a PROMPT_ISSUE or config problem beyond its catalog:

1. Manager reads `skills/orca-workflow-builder/SKILL.md`
2. Passes context: which flow, which state, worker logs, what was already tried
3. Builder runs in audit mode on the specific state/prompt
4. Builder applies fix (respecting manager's autonomy level)
5. Manager retries the issue

The manager's `prompt-issues.md` gets an entry pointing to the builder:

```markdown
### Problem beyond catalog fixes

**Pattern:** Issue persists after applying catalog fixes, or problem is novel
**Root cause:** Structural workflow or prompt issue requiring deeper analysis
**Fix:** Invoke orca-workflow-builder skill in audit mode on the affected flow/state.
  Read `skills/orca-workflow-builder/SKILL.md`, pass worker logs as context.
```

### Builder → Manager

After creating or updating a workflow, the builder can suggest a test run:

> "Workflow created. Want me to start a test run? I'll invoke the orca-manager to run this flow and monitor it."

The builder reads `skills/orca-manager/SKILL.md` and starts a single-flow monitoring mission. If the test run surfaces issues, the builder can fix them immediately — a create-test-fix loop.

### Autonomy Inheritance

When invoked by orca-manager, the builder inherits the manager's autonomy level:
- `cautious` — report findings only, don't modify files
- `supervised` — apply fixes from audit checklist, escalate novel issues
- `full` — apply any fix it can diagnose

When invoked directly by the user, the builder always applies changes (that's what the user asked for).
