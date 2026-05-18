# Playbook: Create an Orca Test (Interactive)

Author a small orca test under `.orca/tests/<name>/` that exercises a slice of a production workflow under controlled conditions and grades the result against a declarative pass/fail checklist.

An **orca test** is just an orca workflow with a fixed shape:

```
setup -> [ 1..N states under test, copied from prod ] -> evaluate
```

The body states are copied verbatim from a production workflow YAML so the prompts under test are exercised exactly as they would be in production. `setup` seeds the worktree and issue fields; `evaluate` grades the result against `evaluations.md` and writes `report.md` into the run directory.

This playbook is **conversational**. Walk the user through every step, show your work, and ask before silently making decisions that change the shape of the test.

## Required reading (you, the agent — not the user)

Before asking the user anything:

- [`reference/prompt-design.md`](reference/prompt-design.md) — the evaluations-first paradigm; explains *why* tests anchor prompt design and how to draft evaluations before any prompt
- [`orca-test-review.md`](orca-test-review.md) — the audit checklist you'll run at the end
- [`reference/orca-config-reference.md`](reference/orca-config-reference.md) — full workflow schema (tests are workflows)
- [`reference/orca-workflow-patterns.md`](reference/orca-workflow-patterns.md) — the building blocks you may reuse
- [`orca-prompt-create.md`](orca-prompt-create.md) — inline-prompt conventions used in `setup` and `evaluate`

## Prerequisites

- Orca CLI installed and the daemon running.
- Working directory is a git repo with a `.orca/` directory.
- At least one production workflow YAML exists under `.orca/` to test against — without one, there's no slice to copy.
- You can name the test in kebab-case. The directory name *is* the test name.

## Cost note — surface this before the first run

Every test run costs **N + 2 LLM invocations** (1 setup, N body states, 1 evaluate). A 5-state slice = 7 worker sessions per run. Tell the user this up front so they aren't surprised. Prefer **single-state slices** for first tests — they're the cheapest way to start and the easiest to debug.

## Interactive process

Run the steps in order. After each, show what you produced and ask the user to confirm before moving on.

### Step 1 — Decide the slice

Ask the user, in plain language:

1. **Which workflow?** `ls .orca/*.yml` and list candidates. If there's only one, name it; otherwise ask.
2. **Which states?** One of:
   - **Single state** (unit test of one prompt — e.g. just `scoping`). Default suggestion.
   - **Subgraph** (integration test of a slice — e.g. `planning -> implementing`).
   - **Full workflow** (end-to-end — every active state).
3. **What does success look like?** One sentence: "the slice should …". This becomes the seed for `evaluations.md`.

Echo back what you understood:

> "You want a unit test of the `scoping` state in `.orca/develop.yml`. Success means: given a 5-section feature spec covering two unrelated subsystems, scoping should produce `outcome=decompose` with at least 2 well-bounded sub_issues. Right?"

**Do not move on until the user confirms.**

### Step 2 — Sketch the scenario

One paragraph. Write the situation the slice will face and what it should do.

> "A user submits a 5-section feature spec that touches both an auth module and a payments module. The scoping state should recognize the spec is too broad for a single feature, decompose it, and emit non-overlapping `scope_boundary` values that cover both subsystems."

This paragraph drives three downstream artefacts:

- `input.md` body (the prose context the setup agent reads)
- the setup prompt (what the worktree should look like before the slice runs)
- `evaluations.md` (the criteria — derived from "should do" wording above)

Show the paragraph and ask the user to refine. Do not start writing files yet.

### Step 3 — Scaffold the directory

Pick a kebab-case name that describes the scenario, not the state:

| Good | Bad |
|---|---|
| `scoping-decomposes-large-spec` | `test-1`, `scoping-test` |
| `planning-rescopes-when-ambiguous` | `planning` |
| `implementing-respects-scope-boundary` | `test-impl` |

Then scaffold:

```bash
orca test add scoping-decomposes-large-spec
```

This creates `.orca/tests/scoping-decomposes-large-spec/` with skeleton `test-flow.yml`, `input.md`, `evaluations.md`, and an empty `fixtures/`. **Edit the skeleton in place** — don't write a fresh structure beside it.

### Step 4 — Write `input.md`

Two sections: YAML frontmatter (engine-parsed into `issue.fields.*` before setup runs) and freeform prose body.

Before:

```markdown
---
title: "TODO: a one-line title for the test scenario"
description: |
  TODO: a one-paragraph description of the situation the slice should handle.
---

# Scenario

TODO: describe the test scenario — what should the slice do, what does the
worktree need to look like beforehand, and what fixtures should setup copy in.
```

After (concrete):

```markdown
---
title: "Decompose a multi-module feature spec"
description: |
  Add multi-factor auth across the auth module and the payments checkout flow.
  Spec touches roughly 5 user-facing sections and spans two unrelated services.
scope_boundary: "src/"
---

# Scenario

The user submitted a broad feature request spanning two subsystems. Before the
slice runs, the worktree should contain the two legacy modules at `src/auth/`
and `src/payments/` (copy them from `fixtures/`). The scoping state should
recognize the spec is too large for a single feature and produce a decompose
outcome with one sub_issue per subsystem.
```

Rules:

- Frontmatter keys are issue field names. **Only declare fields the slice's entry state actually reads.** Cross-check against `issue.fields` in the production workflow.
- Prose body is for the setup agent's eyes — it does not seed `issue.fields`.
- If setup needs to copy files into the worktree, name them under `fixtures/` here.

### Step 5 — Copy slice states into `test-flow.yml`

The skeleton has placeholders. Replace them with body states copied verbatim from production, plus the wiring rules below.

**Rewrite rules.** For each body state copied from production:

1. **`result_format` is copied verbatim.** Drift here is the whole point of having tests — keep them in sync.
2. **Internal transitions stay verbatim.** If `planning` in prod routes `done -> implementing` and both states are in the slice, copy the rule unchanged.
3. **Outgoing-to-outside-slice transitions are rewritten to `evaluate`.** If `implementing` in prod routes `done -> reviewing` but `reviewing` is *not* in the slice, rewrite to `done -> evaluate`. The same applies to any rule that targets the built-in `done` — rewrite to `evaluate` so the grader sees the final result.
4. **The setup state's success outcome routes to the slice's entry state.** Replace the placeholder `ready: TODO_BODY_STATE` with the real entry state name.

Concrete example — copying a single `scoping` state from `.orca/develop.yml`:

Before (in `.orca/develop.yml`):

```yaml
states:
  scoping:
    worker:
      kind: claude-code
      prompt: prompts/scoping.md
      result_format:
        outcome:
          type: enum
          values: [ready, decompose, blocked]
        sub_issues:
          type: list
          items: "$issue"
          required_when: [decompose]
    on:
      ready: planning
      decompose: { action: decompose, child_type: task, then: done }
      blocked: done
```

After (in `.orca/tests/scoping-decomposes-large-spec/test-flow.yml`, body section):

```yaml
  scoping:
    worker:
      kind: claude-code
      prompt: ../../prompts/scoping.md
      result_format:
        outcome:
          type: enum
          values: [ready, decompose, blocked]
        sub_issues:
          type: list
          items: "$issue"
          required_when: [decompose]
    on:
      ready: evaluate
      decompose: evaluate
      blocked: evaluate
```

Notes:

- The `prompt:` path is now `../../prompts/scoping.md` — relative to `test-flow.yml`. The loader resolves it at load time; the worker never sees `..`.
- The decompose action is collapsed to a plain transition. Tests grade against the slice's *output*, not the orchestrator's downstream behaviour. We don't actually want decomposed children to spawn during a test — the `evaluate` state inspects the `sub_issues` field directly.
- Every outcome routes to `evaluate`. The grader decides pass/fail; the slice never reaches `done` on its own.

After editing the body, replace the placeholder `setup.on.ready: TODO_BODY_STATE` with the entry state name (here, `scoping`). Then the file's `setup -> scoping -> evaluate` shape is complete.

### Step 6 — Tune the setup prompt

The skeleton setup prompt reads `input.md` and arranges the worktree. Customise the inline prompt for the scenario.

Default skeleton (in `setup.worker.prompt.text`):

```yaml
        text: |
          # Setup
          Read tests/{{ run.test_name }}/input.md and arrange the worktree.
          Write {{ result_path }} with the issue field values.
```

After (concrete for the scoping example):

```yaml
        text: |
          # Setup

          You are the setup agent for test `{{ run.test_name }}`.

          ## Step 1: Read the scenario
          Read `.orca/tests/{{ run.test_name }}/input.md`. Frontmatter is already
          parsed into issue.fields; the prose body describes the scenario.

          ## Step 2: Arrange the worktree
          Copy these fixture files into the worktree:
          - `.orca/tests/{{ run.test_name }}/fixtures/legacy-auth.py` -> `src/auth/legacy.py`
          - `.orca/tests/{{ run.test_name }}/fixtures/legacy-payments.py` -> `src/payments/legacy.py`

          Commit the worktree changes with message "test setup: seed fixtures".

          ## Step 3: Emit the result
          Write `{{ result_path }}`:

          ```json
          {{ result_example | tojson(indent=2) }}
          ```

          The frontmatter has already seeded `title`, `description`, and
          `scope_boundary`. Re-emit them verbatim unless your worktree
          arrangement requires changes (rare).
```

Rules:

- The setup `result_format` must cover every `issue.fields.*` the slice's entry state reads. Engine seeds these from frontmatter; setup either re-emits them or overrides them.
- `setup_failed` outcome routes to `failed` (in the skeleton). Don't route it to `evaluate` — failed setups produce `inconclusive`, not `failed`.

### Step 7 — Tune the evaluate prompt

The evaluate state is an agent worker that:

- reads `.orca/tests/{{ run.test_name }}/evaluations.md`,
- inspects the worktree, the slice's per-state result files under `{{ run.run_dir }}/state-results/`, and the run summary,
- grades each criterion `pass | fail | not_applicable`,
- writes `{{ run.run_dir }}/report.md`,
- writes a structured result JSON at `{{ result_path }}`.

Concrete inline prompt:

```yaml
        text: |
          # Evaluate

          You are the evaluator for test `{{ run.test_name }}`.

          ## Step 1: Load the criteria
          Read `.orca/tests/{{ run.test_name }}/evaluations.md`. Each `### <id>`
          heading is one criterion. The prose under the heading IS the criterion
          — read it literally.

          ## Step 2: Gather evidence
          - Worktree state (current files).
          - Per-state results in `{{ run.run_dir }}/state-results/`.
          - Run summary: `{{ run.summary }}`.
          - Session history: `{{ run.sessions }}`.

          ## Step 3: Grade each criterion
          For each `### <id>`, decide:
          - `pass` — the criterion is satisfied.
          - `fail` — the criterion is not satisfied.
          - `not_applicable` — the slice didn't reach a point where this could
            be evaluated (e.g. blocked early). Use sparingly.

          One-sentence reason per criterion.

          ## Step 4: Write report.md
          Write `{{ run.run_dir }}/report.md` with this shape:

          ```markdown
          # Test report: {{ run.test_name }}

          **Outcome:** <passed | failed | inconclusive>

          ## Summary
          <N> / <total> criteria passed.

          ## Criteria
          | ID | Status | Reason |
          |---|---|---|
          | <id-1> | pass | ... |
          ```

          ## Step 5: Emit the structured result (FINAL action)
          Write `{{ result_path }}`:

          ```json
          {{ result_example | tojson(indent=2) }}
          ```

          Outcome rules:
          - `passed` — every criterion reported `pass` or `not_applicable`.
          - `failed` — at least one criterion reported `fail`.
          - `inconclusive` — you couldn't grade reliably (slice crashed, setup
            failed upstream, evidence missing).
```

Default the skeleton's three outcomes (`passed`, `failed`, `inconclusive`) all to `done` — the test terminates after evaluation in every case.

### Step 8 — Write `evaluations.md`

The pass/fail checklist. One criterion per `### <id>` heading.

Before:

```markdown
# Evaluations: TODO

TODO: one paragraph describing what this test asserts overall.

## Criteria

### criterion-id-here
TODO: a sentence stating one concrete, gradeable thing the result must satisfy.
```

After (concrete):

```markdown
# Evaluations: scoping-decomposes-large-spec

A 5-section feature spec covering two unrelated subsystems should be decomposed
into sub-issues, not passed through as-is. Sub-issues should cover both
subsystems with non-overlapping scope boundaries.

## Criteria

### outcome-is-decompose
The scoping state's result `outcome` is `decompose` (not `ready` or `blocked`).

### produces-multiple-sub-issues
The `sub_issues` field contains at least 2 entries.

### sub-issues-cover-original-scope
Across all sub_issues, the union of `scope_boundary` paths covers every
top-level directory mentioned in the input description (`src/auth`, `src/payments`).

### sub-issues-are-non-overlapping
No two sub_issues share a top-level path component in their `scope_boundary`.

### titles-are-actionable
Every sub_issue `title` starts with a verb (e.g. "Add", "Refactor", "Extract")
rather than a noun phrase (e.g. "Authentication").
```

Rules:

- One `### <id>` per criterion. `<id>` is kebab-case. The id appears verbatim in `report.md` and the result JSON — keep it stable.
- Prose under each heading **is** the criterion. The evaluator reads it literally.
- **Prefer objective criteria over judgment-heavy ones.** Counts, presence, regexes, enum equality are reproducible. "Is this prose good?" flip-flops between runs (both setup and evaluate are LLM-driven — the double non-determinism amplifies).
- No ordering. No severity/weighting. Pass/fail only in v1.
- Optional `## Setup notes` or `## Context` sections at the top are passed through as background and not graded.

Aim for **3–7 criteria** for a first draft. Fewer is fine if the test is narrow.

### Step 9 — Seed fixtures (optional)

If the scenario references files in `fixtures/`, drop them in now. Keep them small (under ~200 lines each) and realistic — the goal is for the setup agent to copy plausible-looking source files into the worktree, not to ship a mini-app.

Examples:

- `fixtures/legacy-auth.py` — ~50 lines of plausibly-tangled auth code with header comments like `# --- session handling ---`, `# --- password hashing ---` to make the "needs splitting" smell obvious.
- `fixtures/legacy-payments.py` — same pattern for a different subsystem.

Skip this step entirely if setup arranges the worktree by writing stub files inline rather than copying fixtures.

### Step 10 — Run the test

```bash
orca test scoping-decomposes-large-spec
```

The CLI submits the run to the daemon and prints the run id. The CLI is currently fire-and-forget in v1 — it does not block until completion. Use `orca runs` or the TUI to watch progress.

After the run completes, read the report:

```bash
cat .orca-state/runs/orca/test-scoping-decomposes-large-spec-*/report.md
```

Or use the path printed by the evaluate state.

**Iterate.** First runs usually surface one of three problems:

| Symptom | Likely cause | Fix |
|---|---|---|
| Setup fails (`inconclusive`) | Setup prompt couldn't arrange the worktree (missing fixtures, wrong paths). | Re-read fixture paths in the setup prompt; verify `fixtures/` files exist. |
| Slice fails with worker error | `result_format` drift between test and prod, or the production prompt has a bug. | Re-copy `result_format` verbatim from prod; if still failing, the prompt itself is buggy — fix in prod. |
| Criteria flip-flop run-to-run | Judgment-heavy criteria. | Rewrite to be objective (counts, presence, regexes). |
| Every criterion `fail` | Evaluate prompt isn't reading evidence from the right place. | Double-check `{{ run.run_dir }}/state-results/` references; confirm the slice actually emitted a result. |

## Anti-patterns to refuse

- **More than one `setup` or `evaluate` state.** The shape is bookended — exactly one of each. If you need branching, branch in the body.
- **Body states whose `result_format` differs from production.** That defeats the point of the test. If you need a different schema, you're not testing the prompt — you're testing something else. Stop and ask the user what they actually want to test.
- **Judgment-heavy criteria.** "Is this prose well-written?" "Does this title sound good?" Replace with objective tests or drop the criterion.
- **Fixtures larger than ~200 lines.** If you need that much code, the test is doing too much. Split into smaller tests.
- **`evaluate` routing anywhere except `done`.** All three outcomes (`passed`, `failed`, `inconclusive`) terminate the test.
- **Calling the test directory `test-1`, `test-foo`, `unit-test`.** Use a descriptive kebab-case name that says what the scenario is testing.

## Done

Report:

- Directory created: `.orca/tests/<name>/`
- Files: `test-flow.yml`, `input.md`, `evaluations.md`, optionally `fixtures/`
- Slice shape: single-state / subgraph / e2e — and which states
- Criteria count
- Whether a first run was performed and its outcome
- Path to `report.md` (if a run completed)
- Next step (iterate on prompts/criteria, or commit the test and move on)
