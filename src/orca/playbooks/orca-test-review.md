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

- [ ] **First state is `setup`.** `initial:` must equal `setup`. No other arrangement is supported.
- [ ] **Last state before `done` is `evaluate`.** Every terminal outcome in the workflow must route to `done` *through* `evaluate`, or directly route from `evaluate` to `done`.
- [ ] **Exactly one `setup` state and exactly one `evaluate` state.** No `setup-2`, `pre-setup`, `evaluate-final`. The bookending is rigid by design.
- [ ] **Body sits between them.** Setup's success outcome routes to a body state (not directly to `evaluate`, unless the slice is intentionally empty — flag and confirm). Every body state's terminal outgoing route lands in `evaluate`.
- [ ] **No reserved state names misused.** No body state named `setup`, `evaluate`, `done`, or `failed`.
- [ ] **`setup_failed` routes to `failed` (not `evaluate`).** A failed setup should produce an `inconclusive`-flavoured terminal, not be graded.

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
- [ ] **All body states reachable.** Every body state must be reachable from `setup` via the `on:` graph. Unreachable body states are dead code in the test.
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
- [ ] **References to result fields exist in `result_format`.** If a criterion talks about `sub_issues` or `outcome` values, those must appear in some body state's `result_format`. Mismatch means the criterion is ungradeable.

**Severity:** unparseable headings → **Critical**. Judgment-heavy criteria → **Important** (flake-prone). Reference mismatch → **Important** (silent fail-by-default).

## Phase 6 — Setup contract

- [ ] **Setup's `result_format` covers the slice entry state's input fields.** Cross-reference setup's emitted fields with the `issue.fields.*` references in the entry state's prompt (or in its `result_format` derivations).
- [ ] **Fields seeded by `input.md` frontmatter don't require re-emission.** If `description` is in the frontmatter, setup doesn't need to emit `description` unless it overrides. Flag re-emission of unchanged fields as redundant (Minor) but not wrong.
- [ ] **Setup's success outcome routes to the slice's entry state.** Not to a body state in the middle of the slice.
- [ ] **Setup's failure outcome (`setup_failed` or equivalent) routes to `failed`.** Not to `evaluate`.

**Severity:** missing-field coverage → **Critical** (slice will crash trying to read a field that isn't there). Routing errors → **Critical**.

## Phase 7 — Drift report

For each body state, produce a comparison table:

```
| State | Prod result_format | Test result_format | Status |
|---|---|---|---|
| scoping | <hash or summary> | <hash or summary> | match |
| planning | outcome.values=[done, blocked] | outcome.values=[done, blocked, waiting] | drift: waiting outcome added in test |
```

For each `drift` entry, suggest the fix: either update the test (most common — production is the source of truth) or update production (rare — only if the test caught a real prod bug).

Hash/summary is up to the auditor — a stable summary string (e.g. sorted `outcome.values` plus the field-name set) is enough to detect drift; a literal text diff is fine too.

## Phase 8 — Report

Use the same format as [`orca-workflow-review.md`](orca-workflow-review.md) so output is greppable:

```
## Test audit: .orca/tests/<name>/

### Critical
- [structural] test-flow.yml — initial: is `planning`, not `setup`. Tests must start with setup.
- [evaluations] evaluations.md:L24 — duplicate id `outcome-is-decompose`.

### Important
- [drift] scoping — result_format diverges from .orca/develop.yml#scoping: test adds `waiting` to outcome.values. Re-copy from prod.
- [evaluations] evaluations.md:L34 — criterion "titles-are-actionable" asks a judgment question. Rewrite as a regex check (e.g., title starts with a verb from a fixed list).

### Minor
- [setup] test-flow.yml:L18 — setup re-emits `description` unchanged from frontmatter. Remove from result_format to keep setup small.
```

Rules:

- Prefix every finding with the layer: `[structural]`, `[drift]`, `[reference]`, `[evaluations]`, or `[setup]`.
- Cite `file:line` for line-specific findings. Cite the file alone for shape-level findings (drift, unreachable body, etc).
- Suggest a concrete fix. Refer the user to a specific step in [`orca-test-create.md`](orca-test-create.md) when the fix maps to one.
- Sort within each section by file path so reruns produce stable diffs.

## Anti-patterns to flag

- **No body states.** Setup directly routes to `evaluate`. The test grades nothing real. Refuse — ask the user what they meant to test.
- **Two body states with the same name.** The YAML parser may accept this (silently keeping the last); the test is unverifiable. Flag as Critical.
- **Body state routes to a state not in this file.** Dangling reference — config fails to load. Critical.
- **Criteria that reference fields not in any `result_format`.** The criterion will silently fail every run. Important.
- **Tests in `.orca/tests/<name>/` without `evaluations.md`.** The test directory is incomplete — the evaluator has nothing to grade against. Critical.
- **`fixtures/` files referenced by setup prompt but not present on disk.** Setup will fail at first run. Important (catchable on first run, but worth surfacing before).

## Done

Report:

- Test audited: `.orca/tests/<name>/`
- Phase pass/fail summary: structural / slice-integrity / reference / evaluations / setup-contract
- Counts: Critical / Important / Minor
- Drift table (separate from the main report — drift is high-signal even when not yet broken)
- Total criteria count
- Suggested next step (apply fixes via [`orca-test-create.md`](orca-test-create.md), or accept the drift and update production)
