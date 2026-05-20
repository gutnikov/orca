# Playbook: Create an Orca Test (Interactive)

Author a small orca test under `.orca/tests/<name>/` that exercises a slice of a production workflow under controlled conditions and grades the result against a declarative pass/fail checklist.

An **orca test** is just an orca workflow with a fixed shape:

```
[ 1..N states under test, copied from prod ] -> evaluate
```

The body states are copied verbatim from a production workflow YAML so the prompts under test are exercised exactly as they would be in production. The worktree is checked out from the state branch declared in `input.md` frontmatter (`state_ref`); `evaluate` grades the result against `evaluations.md` and writes `report.md` into the run directory.

This playbook is **conversational**. Walk the user through every step, show your work, and ask before silently making decisions that change the shape of the test.

## Required reading (you, the agent — not the user)

Before asking the user anything:

- [`reference/prompt-design.md`](reference/prompt-design.md) — the evaluations-first paradigm; explains *why* tests anchor prompt design and how to draft evaluations before any prompt
- [`orca-test-review.md`](orca-test-review.md) — the audit checklist you'll run at the end
- [`reference/orca-config-reference.md`](reference/orca-config-reference.md) — full workflow schema (tests are workflows)
- [`reference/orca-workflow-patterns.md`](reference/orca-workflow-patterns.md) — the building blocks you may reuse
- [`orca-prompt-create.md`](orca-prompt-create.md) — inline-prompt conventions used in `evaluate`

## Prerequisites

- Orca CLI installed and the daemon running.
- Working directory is a git repo with a `.orca/` directory.
- At least one production workflow YAML exists under `.orca/` to test against — without one, there's no slice to copy.
- You can name the test in kebab-case. The directory name *is* the test name.

> Note: `orca-workflow-run` can hand off here when supervision surfaces a real-world failure mode worth capturing. If you arrived from a supervision session with a captured context block (failing state, scenario summary, worker input/output, log tail), use it as the starting point for Step 1 (Decide the slice) and Step 2 (Sketch the scenario) rather than starting from scratch.

## Cost note — surface this before the first run

Every test run costs **N + 1 LLM invocations** (N body states + 1 evaluate). A 5-state slice = 6 worker sessions per run. The worktree is set up by `git checkout` rather than an LLM, so there is no per-run setup cost. Prefer **single-state slices** for first tests — they're the cheapest way to start and the easiest to debug.

## The state-branch contract

Read this **before drafting any of the steps below**. It is the load-bearing discipline that keeps tests deterministic. Two roles, sharp boundaries:

- **The state branch** (`orca-test-state/<name>`) is the source of every byte the worker will read. **Creativity lives here, and only here.**
- **Evaluations** anchor on stable bytes in the state branch — literal line numbers, paths, function names. **They reference what the state branch contains, not what the orchestrator might produce.**

The non-negotiable rule: every byte the slice's body state will read came from the state branch, not from any LLM decision at run time. If a criterion says `line within 5 of 42`, then line 42 is where the *state branch* puts the bug — pinned by a commit you reviewed before merging the test.

Why this is the rule: state-branch bytes are stable, version-controlled, and easy to inspect. Any byte produced by an LLM at run time varies run-to-run; criteria that depend on such bytes become flaky. The cure is to drain creativity out of run time and into git history — commits are bytes on disk; nobody reinterprets them.

The steps that follow operationalise this contract: Step 5 copies the slice; Step 6 authors the state branch; Step 8 writes evaluations that cite state-branch facts.

## Interactive process

Run the steps in order. After each, show what you produced and ask the user to confirm before moving on.

### Step 1 — Decide the slice

Ask the user, in plain language:

1. **Which workflow?** `ls .orca/*.yml` and list candidates. If there's only one, name it; otherwise ask.
2. **Which states?** One of:
   - **Single state** (unit test of one prompt — e.g. just `review`). Default suggestion.
   - **Subgraph** (integration test of a slice — e.g. `planning -> implementing`).
   - **Full workflow** (end-to-end — every active state).
3. **What does success look like?** One sentence: "the slice should …". This becomes the seed for `evaluations.md`.

Echo back what you understood:

> "You want a unit test of the `review` state in `.orca/review.yml`. Success means: given a PR that introduces a SQL injection at `src/api.py:42`, the review state should produce `outcome=request_changes` with at least one finding pointing at that file:line. Right?"

**Do not move on until the user confirms.**

### Step 2 — Sketch the scenario

One paragraph. Write the situation the slice will face and what it should do.

> "A user submits a PR that adds a `get_user` helper to `src/api.py`. The helper builds a SQL query via f-string interpolation on line 42 — a textbook SQL injection. The review state should read the diff, identify the unsafe interpolation, and emit `outcome=request_changes` with at least one finding whose `file` is `src/api.py` and whose `line` is near 42."

This paragraph drives three downstream artefacts:

- `input.md` body (the prose context — for a human reader)
- the state branch commits (what the worktree should contain before the slice runs)
- `evaluations.md` (the criteria — derived from "should do" wording above)

Show the paragraph and ask the user to refine. Do not start writing files yet.

### Step 3 — Scaffold the directory

Pick a kebab-case name that describes the scenario, not the state:

| Good | Bad |
|---|---|
| `review-catches-sql-injection` | `test-1`, `review-test` |
| `implementing-adds-pagination-to-endpoint` | `implementing` |
| `planning-splits-multi-module-feature` | `test-plan` |

Then scaffold:

```bash
orca test add review-catches-sql-injection
```

This creates `.orca/tests/review-catches-sql-injection/` with skeleton `test-flow.yml`, `input.md`, `evaluations.md`. It also creates the orphan branch `orca-test-state/review-catches-sql-injection` and a persistent author worktree at `.orca-state/test-states/review-catches-sql-injection/`. **Edit the skeleton in place** — don't write a fresh structure beside it.

### Step 4 — Write `input.md`

Two sections: YAML frontmatter (engine-parsed into `issue.fields.*` before the first body state runs) and freeform prose body. The frontmatter also carries the `state_ref` marker — the scaffold stamps it; you generally don't need to edit it.

Before:

```markdown
---
title: "TODO: a one-line title for the test scenario"
description: |
  TODO: a one-paragraph description of the situation the slice should handle.
state_ref: orca-test-state/<test-name>
---

# Scenario

TODO: describe (for a human reader) what this test asserts and how the
state branch is arranged.
```

After (concrete):

```markdown
---
title: "Review a PR that adds a SQL injection"
description: |
  PR adds a `get_user(user_id)` helper in `src/api.py` that builds a SQL
  query via f-string interpolation. The function is called from the
  `/users/<id>` route handler.
scope_boundary: "src/"
state_ref: orca-test-state/review-catches-sql-injection
---

# Scenario

The user submitted a PR that introduces a SQL injection on line 42 of
`src/api.py`. The state branch `orca-test-state/review-catches-sql-injection`
carries that file at the expected path. The review state should read the
diff, identify the unsafe f-string into a SQL query, and emit
`outcome=request_changes` with a finding that points at `src/api.py:42`.
```

Rules:

- Frontmatter keys are issue field names. **Only declare fields the slice's entry state actually reads.** Cross-check against `issue.fields` in the production workflow.
- `state_ref` is required. Without it `orca test <name>` refuses to start the run.
- Prose body is for the reader's eyes — it does not seed `issue.fields`.
- If the test should share state with another test, point `state_ref` at that test's branch instead of the scaffolded default.

### Step 5 — Copy slice states into `test-flow.yml`

The skeleton has placeholders. Replace them with body states copied verbatim from production, plus the wiring rules below.

**Rewrite rules.** For each body state copied from production:

1. **`result_format` is copied verbatim.** Drift here is the whole point of having tests — keep them in sync.
2. **Internal transitions stay verbatim.** If `planning` in prod routes `done -> implementing` and both states are in the slice, copy the rule unchanged.
3. **Outgoing-to-outside-slice transitions are rewritten to `evaluate`.** If `implementing` in prod routes `done -> reviewing` but `reviewing` is *not* in the slice, rewrite to `done -> evaluate`. The same applies to any rule that targets the built-in `done` — rewrite to `evaluate` so the grader sees the final result.
4. **`initial:` names the slice's entry state.** Replace the placeholder `initial: TODO_BODY_STATE` with the real entry state name (e.g. `initial: review`).

Concrete example — copying a single `review` state from `.orca/review.yml`:

Before (in `.orca/review.yml`):

```yaml
states:
  review:
    worker:
      kind: claude-code
      prompt: prompts/review.md
      result_format:
        outcome:
          type: enum
          values: [approve, request_changes, blocked]
        findings:
          type: list
          items:
            file: { type: string }
            line: { type: integer }
            severity: { type: enum, values: [critical, major, minor] }
            message: { type: string }
          required_when: [request_changes]
    on:
      approve: done
      request_changes: revising
      blocked: done
```

After (in `.orca/tests/review-catches-sql-injection/test-flow.yml`, body section):

```yaml
  review:
    worker:
      kind: claude-code
      prompt: ../../prompts/review.md
      result_format:
        outcome:
          type: enum
          values: [approve, request_changes, blocked]
        findings:
          type: list
          items:
            file: { type: string }
            line: { type: integer }
            severity: { type: enum, values: [critical, major, minor] }
            message: { type: string }
          required_when: [request_changes]
    on:
      approve: evaluate
      request_changes: evaluate
      blocked: evaluate
```

Notes:

- The `prompt:` path is now `../../prompts/review.md` — relative to `test-flow.yml`. The loader resolves it at load time; the worker never sees `..`.
- The production `request_changes: revising` transition is collapsed to a plain `evaluate` route. Tests grade against the slice's *output*, not the orchestrator's downstream behaviour. We don't want the `revising` state to spawn during a test — the `evaluate` state inspects the `findings` field directly.
- Every outcome routes to `evaluate`. The grader decides pass/fail; the slice never reaches `done` on its own.

After editing the body, replace the placeholder `initial: TODO_BODY_STATE` with the entry state name (here, `review`). Then the file's `review -> evaluate` shape is complete.

### Step 6 — Author the state branch

`orca test add <name>` already created `orca-test-state/<name>` as an orphan branch and a persistent author worktree at `.orca-state/test-states/<name>/`. Now you arrange the fixture bytes there using plain git — no orca tooling involved.

```
cd .orca-state/test-states/<name>/
# write the files the slice will read
vim src/api.py
# commit when the state is ready
git add . && git commit -m "seed: <describe the scenario>"
```

#### Rules

- **Stable facts go in commits, not in run-time prompts.** A criterion that says "line 42 contains the SQL injection" anchors on a byte that the state branch carries. There is no LLM that could move it.
- **Minimum realistic context.** A state branch contains *just* enough plausible code to make the diff look like real work and to make the scenario interpretable. No filler.
- **No project chrome.** Do not commit `.orca/`, `pyproject.toml`, or `README.md` to the state branch. The orchestrator reads workflow YAML and prompts from the iteration branch; the worktree only needs the bytes the slice will actually look at.
- **Sharing.** Multiple tests can point `state_ref` at the same branch. After `orca test add` creates `orca-test-state/<test-name>`, edit `input.md` to retarget the marker if you want this test to share an already-authored state.
- **Iteration.** `cd` back into the author worktree, edit, commit. The next test run picks up the new tip automatically — `state_ref` is a ref name, not a commit hash.

#### Cross-checking facts

If a criterion anchors on `src/api.py:42`, count the lines in the file the state branch carries and verify line 42 is the bug. The fact and the file must agree. Both live in git now, so a single mismatch becomes a deliberate commit you can review.

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
# Evaluations: review-catches-sql-injection

A PR introducing a SQL injection at `src/api.py:42` should be rejected
with `outcome=request_changes` and at least one finding pointing at the
offending file:line. Approving the PR is a critical failure of the
review prompt.

## Criteria

### outcome-is-request-changes
The review state's result `outcome` is `request_changes` (not `approve` or `blocked`).

### at-least-one-finding
The `findings` field contains at least one entry.

### finding-points-at-sql-injection
Some `findings[i]` has `file == "src/api.py"` and `line` within 5 of 42.

### findings-have-required-fields
Every finding has a non-empty `file`, a positive integer `line`, a
`severity` in `{critical, major, minor}`, and a non-empty `message`.

### messages-are-imperative
Every `findings[i].message` matches `^(Use|Remove|Replace|Fix|Add|Avoid)\b` —
actionable verbs rather than "There is..." or "I see...".
```

Rules:

- One `### <id>` per criterion. `<id>` is kebab-case. The id appears verbatim in `report.md` and the result JSON — keep it stable.
- Prose under each heading **is** the criterion. The evaluator reads it literally.
- **Prefer objective criteria over judgment-heavy ones.** Counts, presence, regexes, enum equality are reproducible. "Is this prose good?" flip-flops between runs (both setup and evaluate are LLM-driven — the double non-determinism amplifies).
- No ordering. No severity/weighting. Pass/fail only in v1.
- Optional `## Setup notes` or `## Context` sections at the top are passed through as background and not graded.

Aim for **3–7 criteria** for a first draft. Fewer is fine if the test is narrow.

### Step 9 — Run the test

```bash
orca test review-catches-sql-injection
```

The CLI submits the run to the daemon and prints the run id. The CLI is currently fire-and-forget in v1 — it does not block until completion. Use `orca runs` or the TUI to watch progress.

After the run completes, read the report:

```bash
cat .orca-state/runs/orca/test-review-catches-sql-injection-*/report.md
```

Or use the path printed by the evaluate state.

**Iterate.** First runs usually surface one of three problems:

| Symptom | Likely cause | Fix |
|---|---|---|
| Daemon error: `state ref '<...>' not found` | The state branch was deleted or renamed, or `state_ref` in `input.md` is wrong. | `git branch --list 'orca-test-state/*'` to confirm; recreate via `orca test add` or fix the marker. |
| Worktree contents look wrong | State branch tip changed since the author last edited; or someone committed `.orca/` or other chrome to the state branch. | `cd .orca-state/test-states/<name>/ && git log --oneline` to inspect; amend or reset as needed. |
| Slice fails with worker error | `result_format` drift between test and prod, or the production prompt has a bug. | Re-copy `result_format` verbatim from prod; if still failing, the prompt itself is buggy — fix in prod. |
| Criteria flip-flop run-to-run | Judgment-heavy criteria. | Rewrite to be objective (counts, presence, regexes). |
| Every criterion `fail` | Evaluate prompt isn't reading evidence from the right place. | Double-check `{{ run.run_dir }}/state-results/` references; confirm the slice actually emitted a result. |

## Anti-patterns to refuse

- **State branches that include project chrome.** Committing `.orca/`, `pyproject.toml`, or other top-level files to `orca-test-state/<name>` makes the branch confusing to inspect and risks the worker reading state from the wrong place. The state branch should contain only the bytes the slice will actually read.
- **`state_ref` pointing at a branch outside the `orca-test-state/` namespace.** Tests pointing at `main` or a feature branch run against arbitrary history that may change underfoot. Use the dedicated namespace; share within it freely.
- **More than one `evaluate` state.** The shape is body→evaluate — exactly one evaluate. If you need branching, branch in the body.
- **Body states whose `result_format` differs from production.** That defeats the point of the test. If you need a different schema, you're not testing the prompt — you're testing something else. Stop and ask the user what they actually want to test.
- **Judgment-heavy criteria.** "Is this prose well-written?" "Does this title sound good?" Replace with objective tests or drop the criterion.
- **`evaluate` routing anywhere except `done`.** All three outcomes (`passed`, `failed`, `inconclusive`) terminate the test.
- **Calling the test directory `test-1`, `test-foo`, `unit-test`.** Use a descriptive kebab-case name that says what the scenario is testing.

## Done

Report:

- Directory created: `.orca/tests/<name>/`
- Files: `test-flow.yml`, `input.md` (with `state_ref` marker), `evaluations.md`
- State branch: `orca-test-state/<name>` (commits arranging the worktree)
- Slice shape: single-state / subgraph / e2e — and which states
- Criteria count
- Whether a first run was performed and its outcome
- Path to `report.md` (if a run completed)
- Next step (iterate on prompts/criteria, or commit the test and move on)
