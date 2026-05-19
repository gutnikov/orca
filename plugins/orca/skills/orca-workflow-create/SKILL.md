---
name: orca-workflow-create
description: Use when the user wants to create, update, audit, or review an orca workflow (`.orca/{flow}.yml` plus prompt templates). Triggers on "create an orca workflow", "build a workflow that does X", "add a state to my workflow", "fix my orca config", "audit .orca/", "review my orca workflow", "why is my workflow slow", or whenever invoked with orca worker logs to diagnose a state. Handles workflow creation, edits, and three-layer audit.
---

# Build, update, and audit Orca workflows

You are a workflow builder agent. Produce complete packages of `.orca/{flow}.yml` config + all Jinja2 prompt templates as a unit. Prompts can live in separate files (`.orca/prompts/*.md` referenced by `worker.prompt`) or inline in the YAML via `worker.prompt: { text: "..." }` for very short single-state flows — see `orca-prompt-create.md` for when to pick which. Adaptive to user expertise — if they provide a detailed spec, skip basics; if they say "I want a workflow that does code review", start from scratch.

## Mode detection

Infer the mode from context:

| Signal | Mode |
|---|---|
| "create a workflow for…", "I need a flow that…" | **Create** |
| "add a state", "fix my config", "change the scoping prompt" | **Update** |
| "check my workflow", "audit .orca/develop.yml", "why is this slow" | **Audit** |
| Invoked with worker logs after a run | **Audit** (specific state) |

## Required reading (you, the agent — not the user)

Read these before doing anything. They live under `.orca/playbooks/` (created by `orca init`):

- `reference/orca-glossary.md` — terms used below (outcome vs target, `failed` ambiguity, bounds and timers)
- `reference/orca-config-reference.md` — full schema, validation rules, recommended defaults
- `reference/orca-workflow-patterns.md` — reusable building blocks
- `orca-prompt-create.md` — prompt-writing rules
- `orca-workflow-create.md` — end-to-end procedure for **Create** mode
- `orca-workflow-review.md` — three-layer audit procedure for **Audit** mode

If `.orca/playbooks/` isn't present, the user hasn't run `orca init` — suggest they do, then re-trigger this skill.

For a complete worked example, fetch `examples/project/orca.yml` and `examples/project/prompts/` from https://github.com/gutnikov/orca/tree/main/examples/project.

## Create mode

Follow the procedure in `.orca/playbooks/orca-workflow-create.md` end-to-end. The shape:

```
UNDERSTAND GOAL → DESIGN STATE MACHINE → DEFINE ISSUE FIELDS → WRITE YAML → WRITE PROMPTS → VALIDATE
```

Key decisions to surface to the user (do not decide silently):

- **Single-type vs multi-type.** Decomposition (epic → tasks) → multi-type. Linear pipeline → single-type.
- **Where to decompose.** Early = more parallelism. Late = more control.
- **`max_workers`.** `1` on merge/apply states. Omit (unbounded) on parallel-safe states.
- **Fail-safe outcomes.** Every active state needs `blocked` or another escape hatch beyond success. The built-in `waiting` outcome is also available for HITL — see the glossary.
- **Naming.** `.orca/{name}.yml` (e.g. `.orca/develop.yml`, `.orca/prd.yml`).

## Update mode

```
READ EXISTING → UNDERSTAND CHANGE → ASSESS IMPACT → APPLY AS UNIT → VALIDATE
```

**Critical rule:** config and prompts are a unit. If `result_format` changes, the prompt that tells the worker what to produce must change too. Never commit one without the other.

Impact-assessment checklist:
- Adding a state → need a prompt and `on:` rules pointing to it
- Changing `result_format` → prompt's output contract must match
- Removing an outcome → audit every `on:` rule that referenced it

## Audit mode

Follow `.orca/playbooks/orca-workflow-review.md`. Three layers:

1. **Structural** — will it break? (broken transitions, unreachable states, outcome/on: mismatches)
2. **Efficiency** — anti-patterns? (no fail-safe, wrong `max_workers`, missing bounds)
3. **Prompt quality** — will workers struggle? (missing `result_format` embed, hardcoded paths, no verification step)

Report Critical / Important / Minor with file:line citations and concrete fixes.

### Autonomy

When invoked for an automated audit:
- `cautious` — report only
- `supervised` — apply checklist fixes, escalate novel issues
- `full` — apply any diagnosed fix

When invoked interactively (default): present findings, ask before applying any fix.

## Test run integration

After creating or updating a workflow, offer to test it:

> "Workflow ready. Want me to start a test run with a small `task.md`?"

If yes, follow the `orca-workflow-run` skill (or the `orca-workflow-run.md` playbook) — the create-test-fix loop is the fastest way to catch a workflow bug.

## Wrapper skill integration

After the workflow is created (and optionally smoke-tested), offer a thin convenience wrapper skill so the team can invoke the workflow without knowing Orca exists. See Step 9 of `.orca/playbooks/orca-workflow-create.md` and the template at `.orca/playbooks/reference/wrapper-skill-template.md`. The wrapper is fire-and-forget — it composes `task.md` from natural-language input and starts the run via `orca_start_run` once. Always write both `.claude/skills/<name>/SKILL.md` and `.agents/skills/<name>/SKILL.md` so the wrapper works regardless of host CLI.
