---
name: orca-create-test
description: Use when the user wants to create, update, or audit an orca test under `.orca/tests/`. Triggers on "create an orca test", "add a test for the planning prompt", "test my workflow end-to-end", "write a unit test for scoping", "audit my orca tests", "review .orca/tests/", "check my test for drift", or whenever a user mentions `evaluations.md`, `test-flow.yml`, or the `.orca/tests/` directory. Handles test creation, edits, and audit.
---

# Build, update, and audit Orca tests

You are a test-authoring agent for orca. An **orca test** is a small workflow at `.orca/tests/<name>/test-flow.yml` that exercises a slice of a production workflow under controlled conditions and grades the result against a declarative pass/fail checklist (`evaluations.md`).

Tests are first-class — parallel to `.orca/prompts/` and `.orca/<flow>.yml`, not nested inside any prompt directory. The test workflow is just an orca workflow with a fixed shape: `setup -> [ body states copied from prod ] -> evaluate`.

## Mode detection

Infer the mode from context:

| Signal | Mode |
|---|---|
| "create a test for…", "add a unit test for the scoping prompt", "test my workflow end-to-end" | **Create** |
| "add a criterion", "fix the setup prompt for my test", "update evaluations.md" | **Update** |
| "audit .orca/tests/", "check my tests for drift", "is this test still valid" | **Audit** |
| Invoked after a test run produced unexpected results | **Audit** (specific test) |

## Required reading (you, the agent — not the user)

Read these before doing anything. They live under `.orca/playbooks/` (created by `orca init`):

- `orca-test-create.md` — end-to-end procedure for **Create** and **Update** mode
- `orca-test-review.md` — audit checklist for **Audit** mode
- `reference/orca-config-reference.md` — full workflow schema (tests are workflows)

If `.orca/playbooks/` isn't present, the user hasn't run `orca init` — suggest they do, then re-trigger this skill.

## Create mode

Follow the procedure in `.orca/playbooks/orca-test-create.md` end-to-end. The shape:

```
DECIDE SLICE -> SKETCH SCENARIO -> SCAFFOLD -> WRITE input.md -> COPY BODY STATES -> TUNE SETUP -> TUNE EVALUATE -> WRITE evaluations.md -> SEED FIXTURES -> RUN
```

Key decisions to surface to the user (do not decide silently):

- **Slice size.** Single-state (cheapest, easiest to debug) vs subgraph vs full workflow. Default suggestion: single-state for first tests.
- **Cost up front.** Every run costs `N + 2` LLM invocations. Tell the user before the first run so they're not surprised.
- **Criterion style.** Objective (counts, presence, regex) beats judgment-heavy ("is this good?"). Push back on flake-prone criteria.
- **Slice scoping.** Body states' `result_format` must match production verbatim. Outgoing routes to states outside the slice (including `done`) get rewritten to `evaluate`.

## Update mode

```
READ EXISTING -> UNDERSTAND CHANGE -> RE-VERIFY SLICE INTEGRITY -> APPLY -> RUN
```

**Critical rule:** if a production workflow's `result_format` changes, every test that copied that state is now drifted. Re-run [`orca-test-review.md`](orca-test-review.md) after any production workflow edit.

Impact-assessment checklist:

- Adding a criterion → ensure the result fields it references actually exist in some body state's `result_format`
- Changing a body state → re-copy `result_format` verbatim from production
- Adding a body state → wire its outgoing routes into the slice or to `evaluate`
- Editing the setup prompt → check that emitted fields still cover the slice's entry state's inputs

## Audit mode

Follow `.orca/playbooks/orca-test-review.md`. Eight phases:

1. **Inventory** — build the state-map and evaluations-map.
2. **Structural** — bookended shape (setup/evaluate), no reserved-name misuse, body sits between.
3. **Slice integrity** — body states match production by name; `result_format` is verbatim against prod; prompt paths resolve.
4. **Reference integrity** — standard workflow validity (transitions, outcomes, reachability, bounds).
5. **Evaluations well-formed** — one criterion per `### <id>`, kebab-case, unique, non-empty prose, references valid result fields.
6. **Setup contract** — setup emits the fields the slice needs; failure routes to `failed`, not `evaluate`.
7. **Drift report** — per-state diff table against the production workflow.
8. **Report** — Critical / Important / Minor with file:line citations.

Report findings using the same format as `orca-workflow-review.md` so output is greppable. The drift table is separate from the main severity list — drift is high-signal even when it hasn't yet broken the test.

### Autonomy

When invoked for an automated audit:

- `cautious` — report only
- `supervised` — apply checklist fixes (re-copy drifted `result_format` from prod, rewrite dangling routes to `evaluate`), escalate novel issues
- `full` — apply any diagnosed fix

When invoked interactively (default): present findings, ask before applying any fix that changes the shape of the test.

## Test run integration

After creating or updating a test, offer to run it:

> "Test ready. Want me to run `orca test <name>` to see the first result?"

If yes, submit the run and report the run id. The CLI is fire-and-forget in v1 — use `orca runs` or the TUI to watch progress, then read `report.md` from the run directory. Use the result to iterate on prompts or criteria.
