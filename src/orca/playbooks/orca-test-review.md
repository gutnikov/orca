# Playbook: Review (Audit) an Orca Test

Audit a test directory under `.orca/tests/<name>/` against the structural, slice-integrity, and evaluations-quality checklist. Produce a structured report (Critical / Important / Minor) with file:line citations and concrete fix suggestions.

A test that runs is not necessarily a test that's correct. Tests drift from their production counterparts silently — this audit is the only thing that catches drift before the next time the production prompt is edited.

## Required reading (you, the agent — not the user)

- [`orca-test-create.md`](orca-test-create.md) — authoring procedure; remediation for findings refers back to this
- [`reference/orca-config-reference.md`](reference/orca-config-reference.md) — workflow schema (tests are workflows)

## When to use this

- After editing a test (`test-flow.yml`, `evaluations.md`, or any prompt the test exercises).
- After editing a production workflow that has tests pointing at it — production drift is the most common reason a test silently rots.
- On a schedule (weekly) for repos with several tests.
- When CI surfaces a stale or unreliable test.
- As the test-side analog of [`orca-workflow-review.md`](orca-workflow-review.md) — both should run together when a workflow changes.

## Prerequisites

- The test directory exists at `.orca/tests/<name>/` and contains at minimum `test-flow.yml`, `input.md`, `evaluations.md`.
- A production workflow YAML exists under `.orca/` that the test's body states were copied from. Ask the user which one if it's not obvious.

## Phase 1 — Inventory

Before running checks, build an in-memory map:

1. List tests: `ls .orca/tests/`. If multiple, ask which to audit (or audit all and aggregate at the end).
2. For the target test, parse `test-flow.yml` and enumerate:
   - All state names, in order.
   - The initial state.
   - `result_format` per state.
   - `on:` rules per state.
   - All `worker.prompt` paths (file or inline).
3. Identify the production workflow each body state was copied from. Search `.orca/*.yml` for matching state names. If a body state name appears in multiple workflows, ask the user.
4. Parse `evaluations.md` and enumerate every `### <id>` heading.

Most checks below cross-reference these tables. Build them once, then run the checklist.

## Phase 2 — Structural checks

These catch shape violations that would fail at runtime or produce uninterpretable results.

- [ ] **`initial:` names a body state, not a reserved name.** `initial:` must point at the slice's entry state — not `setup`, `evaluate`, `done`, or `failed`.
- [ ] **Last state before `done` is `evaluate`.** Every terminal outcome in the workflow must route to `done` *through* `evaluate`, or directly route from `evaluate` to `done`.
- [ ] **Exactly one `evaluate` state.** No `evaluate-2`, `final-evaluate`, etc. The tail is rigid by design.
- [ ] **No `setup` state.** State-branch tests don't have a setup state — the daemon checks the state branch out into the worktree before any state runs.
- [ ] **Every body state's terminal outgoing route lands in `evaluate`.** Routes to states outside the slice get rewritten to `evaluate`.
- [ ] **No reserved state names misused.** No body state named `evaluate`, `done`, or `failed`.

**Severity:** failures here are **Critical**. The test will either fail to load or produce meaningless results.

## Phase 3 — Slice integrity

These catch drift between the test and its production counterpart — the most insidious failure mode.

- [ ] **Every body state matches a state in some production workflow under `.orca/` by name.** If a body state name doesn't appear in any production YAML, the test is testing something that doesn't exist — flag.
- [ ] **`worker.prompt` paths resolve.** For file-based prompts (`prompt: ../../prompts/foo.md`), the file must exist relative to the test workflow's directory. Verify on disk.
- [ ] **`result_format` is verbatim against production.** For each body state, diff `result_format` against the matched production state. Any difference is reported as drift — the test no longer exercises the production contract.
- [ ] **`worker.prompt` path points at the production prompt.** A test that ships its own prompt copy is testing a copy, not the production prompt. The path should be relative (`../../prompts/...`) and resolve to a file under `.orca/prompts/`.
- [ ] **Outgoing routes from body states land in `evaluate` or another body state in this file.** Routes to states that exist in production but not in the test file are dangling references and must be rewritten to `evaluate`.

**Severity:** drift in `result_format` is **Important** (the test is silently testing a stale contract). Dangling routes are **Critical** (config fails to load).

## Phase 4 — Reference integrity

These are the standard workflow-level checks, scoped to the test file.

- [ ] **All `on:` targets exist.** Every transition target is either a state in `test-flow.yml`, the literal `evaluate`, or the built-in `done`/`failed`.
- [ ] **Outcomes match `on:` keys.** Every key in `on:` must be a value in the state's `result_format.outcome.values`.
- [ ] **All body states reachable.** Every body state must be reachable from `initial:` via the `on:` graph. Unreachable body states are dead code in the test.
- [ ] **Worker `kind` valid.** `claude-code`, `codex`, or `opencode`.
- [ ] **`max_hops` and `max_worker_retries` set.** Tests need bounds just like production. Recommended: `max_hops: 10`, `max_worker_retries: 2` (tests should fail fast).

**Severity:** failures here are **Critical** (config invalid) or **Important** (unbounded test could runaway).

## Phase 5 — Evaluations well-formed

- [ ] **One `### <id>` per criterion.** No nested headings under criteria. No `####` sub-criteria.
- [ ] **IDs are kebab-case.** Lowercase letters, digits, hyphens. No spaces, underscores, or capitals.
- [ ] **IDs are unique within the file.** Two criteria with the same id would silently merge in the result JSON.
- [ ] **Prose under each heading is non-empty.** A heading with no prose is unparseable — flag.
- [ ] **Criterion count is reasonable.** Aim for 3–7 per test. Fewer than 3 → the test probably under-asserts. More than 10 → the test is doing too much; consider splitting.
- [ ] **No judgment-heavy criteria.** Flag criteria that ask qualitative questions ("is this prose well-written?", "does this look good?"). Suggest objective rewrites.
- [ ] **References to result fields exist in `result_format`.** If a criterion talks about `findings`, `outcome` values, or any other field, those must appear in some body state's `result_format`. Mismatch means the criterion is ungradeable.

**Severity:** unparseable headings → **Critical**. Judgment-heavy criteria → **Important** (flake-prone). Reference mismatch → **Important** (silent fail-by-default).

## Phase 6 — State branch contract

The contract: every byte in the worktree comes from `state_ref`'s commit history; no LLM-arranged content. See `orca-test-create.md` ("The state-branch contract") for the rationale.

### Marker & resolution

- [ ] **`state_ref` is present in `input.md` frontmatter.** Grep: `grep -n '^state_ref:' .orca/tests/<name>/input.md` — should return exactly one line.
- [ ] **`state_ref` is not the placeholder.** `TODO_STATE_REF` means the scaffold ran but the author never authored the state. Flag as Critical — the test cannot run.
- [ ] **`state_ref` resolves to a real branch.** Run: `git rev-parse --verify $(yq '.state_ref' .orca/tests/<name>/input.md)`. Exit code 0 = ref exists. If not, the test cannot run.
- [ ] **`state_ref` lives in the `orca-test-state/` namespace.** Branches outside the namespace (e.g. `main`, feature branches) tie the test to history that changes under your feet. Sharing within the namespace is fine; pointing at `main` is Important.

### Branch contents

- [ ] **State branch contains no project chrome.** Run: `git ls-tree --name-only orca-test-state/<name>` — confirm no `.orca/`, `pyproject.toml`, `README.md`, or other top-level files unrelated to the scenario.
- [ ] **Evaluation criteria anchor on bytes in the state branch.** For every criterion that references a literal file path, line number, function name, or fixed string, run `git show orca-test-state/<name>:<path>` (or similar) and verify the bytes match. Mismatches mean the state was edited but the criterion wasn't updated.
- [ ] **No body state has its own `setup` re-implementation.** If a body state's prompt instructs the worker to copy files, run git commands, or seed scenario content, it's recreating the deleted setup step — fold those bytes into the state branch instead.

### Issue fields

- [ ] **`input.md` frontmatter covers every `issue.fields.*` the slice's entry state reads.** Cross-reference frontmatter keys with the `issue.fields.*` references in the entry state's prompt. Missing fields → the slice will fail at first run.

**Severity:** unresolved `state_ref` → **Critical**. Project chrome in state branch → **Important**. Evaluation/fixture anchor mismatch → **Critical** (criteria pass or fail for wrong reasons). Missing issue.fields → **Critical**.

## Phase 7 — Drift report

For each body state, produce a comparison table:

```
| State | Prod result_format | Test result_format | Status |
|---|---|---|---|
| review | <hash or summary> | <hash or summary> | match |
| implementing | outcome.values=[done, blocked] | outcome.values=[done, blocked, waiting] | drift: waiting outcome added in test |
```

For each `drift` entry, suggest the fix: either update the test (most common — production is the source of truth) or update production (rare — only if the test caught a real prod bug).

Hash/summary is up to the auditor — a stable summary string (e.g. sorted `outcome.values` plus the field-name set) is enough to detect drift; a literal text diff is fine too.

## Phase 8 — Report

Use the same format as [`orca-workflow-review.md`](orca-workflow-review.md) so output is greppable:

```
## Test audit: .orca/tests/<name>/

### Critical
- [state-branch] input.md:L8 — `state_ref` is `TODO_STATE_REF`; author the state branch and update the marker.
- [evaluations] evaluations.md:L24 — duplicate id `outcome-is-request-changes`.

### Important
- [drift] review — result_format diverges from .orca/review.yml#review: test adds `waiting` to outcome.values. Re-copy from prod.
- [evaluations] evaluations.md:L34 — criterion "messages-are-actionable" asks a judgment question. Rewrite as a regex check (e.g., message starts with a verb from a fixed list).

### Minor
- [state-branch] orca-test-state/<name> — contains `README.md` at root. Remove from the state branch; it's project chrome.
```

Rules:

- Prefix every finding with the layer: `[structural]`, `[drift]`, `[reference]`, `[evaluations]`, or `[state-branch]`.
- Cite `file:line` for line-specific findings. Cite the file alone for shape-level findings (drift, unreachable body, etc).
- Suggest a concrete fix. Refer the user to a specific step in [`orca-test-create.md`](orca-test-create.md) when the fix maps to one.
- Sort within each section by file path so reruns produce stable diffs.

## Anti-patterns to flag

- **No body states.** `initial:` points straight at `evaluate`. The test grades nothing real. Refuse — ask the user what they meant to test.
- **A `setup` state.** State-branch tests have no setup state. If you find one, the test predates the migration — re-scaffold via `orca test add` or migrate by hand (see `orca-test-create.md` Step 6).
- **`fixtures/` directory present.** Same as above — the directory is a fossil from the pre-state-branch model. Move its contents into commits on `orca-test-state/<name>` and delete the directory.
- **Two body states with the same name.** The YAML parser may accept this (silently keeping the last); the test is unverifiable. Flag as Critical.
- **Body state routes to a state not in this file.** Dangling reference — config fails to load. Critical.
- **Criteria that reference fields not in any `result_format`.** The criterion will silently fail every run. Important.
- **Tests in `.orca/tests/<name>/` without `evaluations.md`.** The test directory is incomplete — the evaluator has nothing to grade against. Critical.
- **`state_ref` points at a branch outside `orca-test-state/`.** Tests pointing at `main` or feature branches run against history that changes underfoot. Important.

## Done

Report:

- Test audited: `.orca/tests/<name>/`
- Phase pass/fail summary: structural / slice-integrity / reference / evaluations / state-branch
- Counts: Critical / Important / Minor
- Drift table (separate from the main report — drift is high-signal even when not yet broken)
- Total criteria count
- Suggested next step (apply fixes via [`orca-test-create.md`](orca-test-create.md), or accept the drift and update production)
