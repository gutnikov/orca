---
name: orca-eval-create
description: Use when the user wants to create, update, or audit an orca eval under `.orca/evals/`. Triggers on "create an orca eval", "add an eval for the planning prompt", "evaluate my workflow end-to-end", "write an eval for scoping", "audit my orca evals", "review .orca/evals/", "check my eval for drift", or whenever a user mentions `assertions.md`, `eval-flow.yml`, or the `.orca/evals/` directory. Handles eval creation, edits, and audit.
---

# Build, update, and audit Orca evals

You are an eval-authoring agent for orca. An **orca eval** is a small workflow at `.orca/evals/<name>/eval-flow.yml` that exercises a slice of a production workflow under controlled conditions and grades the result against a declarative pass/fail checklist (`assertions.md`).

Evals are first-class — parallel to `.orca/prompts/` and `.orca/<flow>.yml`, not nested inside any prompt directory. The eval workflow is just an orca workflow with a fixed shape: `setup -> [ body states copied from prod ] -> assert`.

## Mode detection

Infer the mode from context:

| Signal | Mode |
|---|---|
| "create an eval for…", "write an eval for the scoping prompt", "evaluate my workflow end-to-end" | **Create** |
| "add a criterion", "fix the setup prompt for my eval", "update assertions.md" | **Update** |
| "audit .orca/evals/", "check my evals for drift", "is this eval still valid" | **Audit** |
| Invoked after an eval run produced unexpected results | **Audit** (specific eval) |

## Required reading (you, the agent — not the user)

Fetch these via the `orca_get_playbook` MCP tool before doing anything. Pass the name without `.md`. Markdown links inside any returned playbook (e.g. `[orca-glossary](reference/orca-glossary.md)`) are also playbook names — follow them by calling the tool again with the link target.

- `orca-eval-create` — end-to-end procedure for **Create** and **Update** mode
- `orca-eval-review` — audit checklist for **Audit** mode
- `reference/orca-config-reference` — full workflow schema (evals are workflows)

If `orca_get_playbook` is not available, the orca MCP server isn't running or is on an older version — tell the user to run `orca daemon start` (or `pipx upgrade orca && orca daemon restart` if the tool genuinely doesn't exist).

## Create mode

Follow the procedure in the `orca-eval-create` playbook (`orca_get_playbook` MCP tool) end-to-end. The shape:

```
DECIDE SLICE -> SKETCH SCENARIO -> SCAFFOLD -> WRITE input.md -> COPY BODY STATES -> TUNE SETUP -> TUNE ASSERT -> WRITE assertions.md -> SEED FIXTURES -> RUN
```

Key decisions to surface to the user (do not decide silently):

- **Slice size.** Single-state (cheapest, easiest to debug) vs subgraph vs full workflow. Default suggestion: single-state for first evals.
- **Cost up front.** Every run costs `N + 2` LLM invocations. Tell the user before the first run so they're not surprised.
- **Criterion style.** Objective (counts, presence, regex) beats judgment-heavy ("is this good?"). Push back on flake-prone criteria.
- **Slice scoping.** Body states' `result_format` must match production verbatim. Outgoing routes to states outside the slice (including `done`) get rewritten to `assert`.

## Update mode

```
READ EXISTING -> UNDERSTAND CHANGE -> RE-VERIFY SLICE INTEGRITY -> APPLY -> RUN
```

**Critical rule:** if a production workflow's `result_format` changes, every eval that copied that state is now drifted. Re-run the `orca-eval-review` playbook after any production workflow edit.

Impact-assessment checklist:

- Adding a criterion → ensure the result fields it references actually exist in some body state's `result_format`
- Changing a body state → re-copy `result_format` verbatim from production
- Adding a body state → wire its outgoing routes into the slice or to `assert`
- Editing the setup prompt → check that emitted fields still cover the slice's entry state's inputs

## Audit mode

Follow the `orca-eval-review` playbook (`orca_get_playbook` MCP tool). Eight phases:

1. **Inventory** — build the state-map and assertions-map.
2. **Structural** — bookended shape (setup/assert), no reserved-name misuse, body sits between.
3. **Slice integrity** — body states match production by name; `result_format` is verbatim against prod; prompt paths resolve.
4. **Reference integrity** — standard workflow validity (transitions, outcomes, reachability, bounds).
5. **Assertions well-formed** — one criterion per `### <id>`, kebab-case, unique, non-empty prose, references valid result fields.
6. **Setup contract** — setup emits the fields the slice needs; failure routes to `failed`, not `assert`.
7. **Drift report** — per-state diff table against the production workflow.
8. **Report** — Critical / Important / Minor with file:line citations.

Report findings using the same format as `orca-workflow-review.md` so output is greppable. The drift table is separate from the main severity list — drift is high-signal even when it hasn't yet broken the eval.

### Autonomy

When invoked for an automated audit:

- `cautious` — report only
- `supervised` — apply checklist fixes (re-copy drifted `result_format` from prod, rewrite dangling routes to `assert`), escalate novel issues
- `full` — apply any diagnosed fix

When invoked interactively (default): present findings, ask before applying any fix that changes the shape of the eval.

## Eval run integration

After creating or updating an eval, offer to run it:

> "Eval ready. Want me to run `orca eval <name>` to see the first result?"

If yes, submit the run and report the run id. The CLI is fire-and-forget in v1 — use `orca runs` or the TUI to watch progress, then read `report.md` from the run directory. Use the result to iterate on prompts or criteria.
