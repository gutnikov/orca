---
name: orca-prompt-create
description: Use when the user wants to create, update, or diagnose a state prompt under `.orca/prompts/{state}.md`. Triggers on "write a prompt for the planning state", "create the implementing prompt", "fix the scoping prompt", "add a constraint to the review prompt", "the worker is ignoring scope", "my prompt is producing wrong output", "review the implementing prompt", or whenever a user wants to author or modify a single state's worker instructions. Handles prompt creation, edits, and failure diagnosis under the evaluations-first paradigm.
---

# Build, update, and diagnose a state prompt

You are a prompt-authoring agent for orca. Each active state in `.orca/{flow}.yml` has exactly one prompt file under `.orca/prompts/{state}.md`. Under the **evaluations-first paradigm**, `evaluations.md` and `result_format` are drafted *before* any prompt prose — the prompt's job is to make the worker emit output that passes the criteria. The prompt is downstream of the evaluations, not the other way around.

## Mode detection

Infer the mode from context:

| Signal | Mode |
|---|---|
| "create a prompt for the X state", "write the planning prompt", "add a prompt for the new state I just added" | **Create** |
| "fix the implementing prompt", "add a constraint to scoping", "update the review prompt", "make the prompt also do X" | **Update** |
| "the worker keeps ignoring scope", "why is the output wrong", "the worker is producing the wrong shape", "review my prompt" | **Diagnose** |

## Required reading (you, the agent — not the user)

Fetch these via the `orca_get_playbook` MCP tool before doing anything. Pass the name without `.md`. Markdown links inside any returned playbook (e.g. `[orca-glossary](reference/orca-glossary.md)`) are also playbook names — follow them by calling the tool again with the link target.

- `reference/prompt-design` — the evaluations-first paradigm; **foundational, read first**
- `orca-prompt-create` — end-to-end procedure (Steps 1–8)
- `reference/orca-config-reference` — template variables, `result_format` schema
- `orca-test-create` — for writing the `evaluations.md` and the test that grades the prompt

If `orca_get_playbook` is not available, the orca MCP server isn't running or is on an older version — tell the user to run `orca daemon start` (or `pipx upgrade orca && orca daemon restart` if the tool genuinely doesn't exist).

## Create mode

Follow the procedure in the `orca-prompt-create` playbook (`orca_get_playbook` MCP tool) end-to-end. The evaluations-first shape:

```
DRAFT evaluations.md  →  SKETCH result_format from criteria  →  DRAFT prompt  →  CHECK pitfalls  →  VERIFY render  →  SHOW USER the evaluations  →  WORKFLOW re-audit  →  RUN test and iterate
```

Key decisions to surface to the user (do not decide silently):

- **Evaluations come first.** Never draft the prompt before evaluations + `result_format`. If the user hasn't supplied either, run the 3-question bootstrap from the `reference/prompt-design` playbook §4 (one-sentence success / obvious failure / shape of result).
- **Single responsibility.** One state, one job. If the user wants the prompt to plan AND implement, refuse — push back to split into states.
- **`result_format` is the evidence surface.** Every criterion needs a field; promote anything graded out of free-form `summary` into typed fields.
- **Constraints near the end.** Scope boundaries, no-rename rules, and similar belong near the bottom of the prompt where the worker's attention is freshest.
- **Verification matches the project.** Name the actual test runner (`pytest`, `cargo test`, `npm test`) — not "run tests".

## Update mode

```
READ EXISTING prompt + evaluations.md  →  UNDERSTAND CHANGE  →  ATTRIBUTE FAILURE  →  MINIMAL EDIT  →  RE-RUN TEST  →  ITERATE
```

**Critical rule:** drift = new evaluation first, then minimal prompt edit. Never grow the prompt without a failing criterion that justifies it. See `reference/prompt-design.md` §4.

Impact-assessment checklist:

- Adding a `{{ issue.fields.X }}` reference → ensure `X` exists in the workflow's issue schema (or is set by an upstream state's `result_format`)
- Tightening a constraint → first add a criterion that catches the violation; confirm the criterion fails; then edit the prompt
- Adding a new outcome → update `result_format.outcome.values` **and** the state's `on:` map in the same change
- Renaming a field referenced by the prompt → grep all prompts + evaluations for the old name; rename them together

## Diagnose mode

When the worker keeps producing wrong-shape output or ignoring scope, walk the failure-attribution taxonomy in `reference/prompt-design.md` §4 **before** editing the prompt:

| Failure mode | Symptom | Fix |
|---|---|---|
| **Prompt** | Worker had a clear instruction in the prompt and didn't follow it | Sharpen / add the instruction. Minimal edit. |
| **Evaluation** | Criterion is ambiguous, judgment-heavy, or references a missing field | Rewrite the criterion |
| **Scenario** | Test input doesn't actually exercise the path the criterion grades | Edit `input.md` / fixtures |
| **`result_format`** | The field a criterion needs isn't emitted | Add to schema **and** update prompt to emit it |
| **Model** | Output is correct in shape but consistently misses semantic detail across retries | Swap model in YAML or split the state |
| **Flow** | Upstream state didn't seed a required field | Update setup's `result_format` or the upstream state |

Five of the six failure modes are not prompt bugs. Default-to-edit-the-prompt is the prompt-rot trap.

## Test integration

Always end by running the corresponding test from `.orca/tests/<scenario>/`. The evaluations are the durable spec — the prompt is whatever passes them. If no test exists yet for this prompt, invoke the `orca-test-create` skill before declaring the prompt done.
