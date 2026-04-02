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
