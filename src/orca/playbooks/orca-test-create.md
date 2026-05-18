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

## The setup-fixture contract

Read this **before drafting any of the steps below**. It is the load-bearing discipline that keeps tests deterministic. Three roles, sharp boundaries:

- **Fixtures** are checked-in artefacts under `fixtures/`. They contain every byte of the scenario the worker will read. **Creativity lives here, and only here.**
- **Setup** is a mechanical transport. It moves fixtures to worktree paths, runs git commands with literal strings, and emits frontmatter. **It does not invent content.**
- **Evaluations** anchor on stable fixture facts — literal line numbers, paths, function names. **They reference what the fixture contains, not what setup might produce.**

The non-negotiable rule: every byte the slice's body state will read came from a fixture, not from a setup-agent decision. If a criterion says `line within 5 of 42`, then line 42 is where the *fixture* puts the bug — not where the setup agent chose to put it.

Why this is the rule: setup is itself an LLM agent reading an inline prompt. Anything you ask it to invent will vary run-to-run; criteria that depend on those varying outputs become flaky. The cure is to drain creativity out of setup and into fixtures — fixtures are stable bytes on disk; the LLM doesn't reinterpret them.

The steps that follow operationalise this contract: Step 5 copies the slice; Step 6 writes the (mechanical) setup prompt; Step 8 writes evaluations that cite fixture facts; Step 9 designs the fixtures themselves. Step 6 has a full MAY / MAY NOT list for setup operations; Step 9 has the fixture rules including the `# Fact:` header convention.

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

- `input.md` body (the prose context the setup agent reads)
- the setup prompt (what the worktree should look like before the slice runs)
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

This creates `.orca/tests/review-catches-sql-injection/` with skeleton `test-flow.yml`, `input.md`, `evaluations.md`, and an empty `fixtures/`. **Edit the skeleton in place** — don't write a fresh structure beside it.

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
title: "Review a PR that adds a SQL injection"
description: |
  PR adds a `get_user(user_id)` helper in `src/api.py` that builds a SQL
  query via f-string interpolation. The function is called from the
  `/users/<id>` route handler.
scope_boundary: "src/"
---

# Scenario

The user submitted a PR that introduces a SQL injection on line 42 of
`src/api.py`. Before the slice runs, the worktree should contain the
file at `src/api.py` (copy from `fixtures/api-with-sqli.py`). The
review state should read the diff, identify the unsafe f-string into a
SQL query, and emit `outcome=request_changes` with a finding that
points at `src/api.py:42`.
```

Rules:

- Frontmatter keys are issue field names. **Only declare fields the slice's entry state actually reads.** Cross-check against `issue.fields` in the production workflow.
- Prose body is for the setup agent's eyes — it does not seed `issue.fields`.
- If setup needs to copy files into the worktree, name them under `fixtures/` here. See *The setup-fixture contract* above for the rules.

### Step 5 — Copy slice states into `test-flow.yml`

The skeleton has placeholders. Replace them with body states copied verbatim from production, plus the wiring rules below.

**Rewrite rules.** For each body state copied from production:

1. **`result_format` is copied verbatim.** Drift here is the whole point of having tests — keep them in sync.
2. **Internal transitions stay verbatim.** If `planning` in prod routes `done -> implementing` and both states are in the slice, copy the rule unchanged.
3. **Outgoing-to-outside-slice transitions are rewritten to `evaluate`.** If `implementing` in prod routes `done -> reviewing` but `reviewing` is *not* in the slice, rewrite to `done -> evaluate`. The same applies to any rule that targets the built-in `done` — rewrite to `evaluate` so the grader sees the final result.
4. **The setup state's success outcome routes to the slice's entry state.** Replace the placeholder `ready: TODO_BODY_STATE` with the real entry state name.

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

After editing the body, replace the placeholder `setup.on.ready: TODO_BODY_STATE` with the entry state name (here, `review`). Then the file's `setup -> review -> evaluate` shape is complete.

### Step 6 — Tune the setup prompt

The skeleton setup prompt reads `input.md` and arranges the worktree. Customise the inline prompt for the scenario.

Default skeleton (in `setup.worker.prompt.text`):

```yaml
        text: |
          # Setup
          Read tests/{{ run.test_name }}/input.md and arrange the worktree.
          Write {{ result_path }} with the issue field values.
```

After (concrete for the review example — mechanical, no content generation):

```yaml
        text: |
          # Setup

          You are the setup agent for test `{{ run.test_name }}`.
          Your job is mechanical: copy the fixture, commit, emit the result. Do not invent content.

          ## Step 1: Read the scenario
          Read `.orca/tests/{{ run.test_name }}/input.md`. Frontmatter is already
          parsed into issue.fields; the prose body is context for you only.

          ## Step 2: Arrange the worktree (mechanical operations only)
          Copy the fixture verbatim — do NOT modify its bytes:
          - `.orca/tests/{{ run.test_name }}/fixtures/api-with-sqli.py` -> `src/api.py`

          Then run, with these literal arguments:
          - `git add src/api.py`
          - `git commit -m "test setup: seed PR with SQL injection"`

          ## Step 3: Emit the result
          Write `{{ result_path }}` with the frontmatter values verbatim:

          ```json
          {{ result_example | tojson(indent=2) }}
          ```
```

The setup prompt should be **≤ 30 lines**. If it grows past that, it is almost always doing too much — usually inventing content. Audit yourself.

### What setup MAY do

- Copy files from `fixtures/` to worktree paths. Both source and target are literal strings in the prompt.
- Run git commands with literal arguments: `git init`, `git add <literal path>`, `git commit -m "<literal>"`, `git checkout -b <fixed-name>`.
- Append a literal string to a file.
- Create empty directories (`mkdir -p <literal>`).
- Re-emit frontmatter fields verbatim in the result JSON.

### What setup MAY NOT do

- **Generate file content from a description.** "Write a Python file with…", "create a realistic config…", "draft a fixture that…". All forbidden — convert the request into a fixture.
- **Choose paths, names, line numbers, or values based on judgment.** Every such value in the prompt is a literal, or it comes from `input.md` frontmatter, or the operation doesn't belong in setup.
- **Make any worktree decision that isn't pre-baked in a fixture or named explicitly in the input frontmatter.** No improvisation.
- **Depend on external state.** No current time, no network, no RNG, no machine-specific values.

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

### Step 9 — Design fixtures

Fixtures are the *only* source of creativity in the test. Setup transports them; evaluations cite their facts. Build them deliberately.

**Rules:**

- **Document the stable facts in a header comment.** Each fixture starts with one `# Fact:` comment per evaluation-anchored fact. Example:

  ```python
  # Fact: SQL injection at line 42 (f-string into cursor.execute)
  # Fact: function name is `get_user`
  # Fact: route handler at line 18 calls get_user
  ```

  These are the contract between the fixture and the evaluations that cite it. If the fixture is edited and a fact moves, every evaluation that anchored on it must be updated in the same change.

- **Minimum realistic context.** A fixture is *just* enough plausible code to make the diff look like real work and to make the bug interpretable. No filler. If you can remove a function without losing an evaluation anchor or the realism floor, remove it.

- **Size cap.** ≤ 200 lines per fixture, ≤ 3 fixtures per test. Past that, the test is doing too much — split into smaller scenarios.

- **No templates.** A fixture is not a template; it is the literal bytes that land in the worktree. No `{{ placeholders }}`, no setup-time substitution. If you need two variants of a scenario, ship two concrete fixtures and pick which one setup copies via a literal path in the prompt.

- **Anchored facts must match the file.** If a header comment says "SQL injection at line 42", count the lines — line 42 must actually contain the bug. Cross-check before committing.

Examples:

- `fixtures/api-with-sqli.py` — ~50 lines containing a `get_user(user_id)` helper that builds a SQL query via f-string interpolation (the deliberate bug at line 42), plus a couple of unrelated route handlers so the diff looks like a realistic PR rather than a single suspicious change. The file's header comments pin the bug's location, function name, and surrounding route call site.

Skip this step only if the scenario genuinely needs no worktree files (e.g., a planning state that only reads `issue.fields`). In that case, setup still has work — frontmatter re-emission, git init — but no `fixtures/` directory is created.

### Step 10 — Run the test

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
| Setup fails (`inconclusive`) | Setup prompt couldn't arrange the worktree (missing fixtures, wrong paths). | Re-read fixture paths in the setup prompt; verify `fixtures/` files exist. |
| Slice fails with worker error | `result_format` drift between test and prod, or the production prompt has a bug. | Re-copy `result_format` verbatim from prod; if still failing, the prompt itself is buggy — fix in prod. |
| Criteria flip-flop run-to-run | Judgment-heavy criteria. | Rewrite to be objective (counts, presence, regexes). |
| Every criterion `fail` | Evaluate prompt isn't reading evidence from the right place. | Double-check `{{ run.run_dir }}/state-results/` references; confirm the slice actually emitted a result. |

## Anti-patterns to refuse

- **Setup that invents content.** "Write a Python file with…", "Create a realistic-looking config…", "Draft a fixture that has X". Refuse — every byte in the worktree must come from a fixture, not a setup-agent decision.
- **Evaluations anchored on setup-agent decisions.** Criteria like "the file the setup agent created has X" are fragile. Anchor on fixture facts (literal paths, line numbers, function names that the fixture's `# Fact:` header pins down).
- **Templated fixtures.** Fixtures with `{{ vars }}` that setup substitutes. The substitution is a form of generation. Collapse into multiple concrete fixtures, one per variant.
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
