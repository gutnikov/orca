# Playbook: Review (Audit) an Orca Eval

Audit an eval directory under `.orca/evals/<name>/` against the structural, slice-integrity, and assertions-quality checklist. Produce a structured report (Critical / Important / Minor) with file:line citations and concrete fix suggestions.

An eval that runs is not necessarily an eval that's correct. Evals drift from their production counterparts silently — this audit is the only thing that catches drift before the next time the production prompt is edited.

## Required reading (you, the agent — not the user)

- [`orca-eval-create.md`](orca-eval-create.md) — authoring procedure; remediation for findings refers back to this
- [`reference/orca-config-reference.md`](reference/orca-config-reference.md) — workflow schema (evals are workflows)

## When to use this

- After editing an eval (`eval-flow.yml`, `assertions.md`, or any prompt the eval exercises).
- After editing a production workflow that has evals pointing at it — production drift is the most common reason an eval silently rots.
- On a schedule (weekly) for repos with several evals.
- When CI surfaces a stale or unreliable eval.
- As the eval-side analog of [`orca-workflow-review.md`](orca-workflow-review.md) — both should run together when a workflow changes.

## Prerequisites

- The eval directory exists at `.orca/evals/<name>/` and contains at minimum `eval-flow.yml`, `input.md`, `assertions.md`.
- A production workflow YAML exists under `.orca/` that the eval's body states were copied from. Ask the user which one if it's not obvious.

## Phase 1 — Inventory

Before running checks, build an in-memory map:

1. List evals: `ls .orca/evals/`. If multiple, ask which to audit (or audit all and aggregate at the end).
2. For the target eval, parse `eval-flow.yml` and enumerate:
   - All state names, in order.
   - The initial state.
   - `result_format` per state.
   - `on:` rules per state.
   - All `worker.prompt` paths (file or inline).
3. Identify the production workflow and issue type each body state was copied from. Search `.orca/*.yml` for matching type/state pairs. If a body state name appears in multiple workflows or under multiple issue types in one workflow, use prompt path and `result_format` as hints, but ask the user when the source is still ambiguous.
4. Parse `assertions.md` and enumerate every `### <id>` heading.

Most checks below cross-reference these tables. Build them once, then run the checklist.

## Phase 2 — Structural checks

These catch shape violations that would fail at runtime or produce uninterpretable results.

- [ ] **`initial:` names a body state, not a reserved name.** `initial:` must point at the slice's entry state — not `setup`, `assert`, `done`, or `failed`.
- [ ] **Last state before `done` is `assert`.** Every terminal outcome in the workflow must route to `done` *through* `assert`, or directly route from `assert` to `done`.
- [ ] **Exactly one `assert` state.** No `assert-2`, `final-assert`, etc. The tail is rigid by design.
- [ ] **No `setup` state.** State-branch evals don't have a setup state — the daemon checks the state branch out into the worktree before any state runs.
- [ ] **Every body state's terminal outgoing route lands in `assert`.** Routes to states outside the slice get rewritten to `assert`.
- [ ] **No reserved state names misused.** No body state named `assert`, `done`, or `failed`.

**Severity:** failures here are **Critical**. The eval will either fail to load or produce meaningless results.

## Phase 3 — Slice integrity

These catch drift between the eval and its production counterpart — the most insidious failure mode.

- [ ] **Every body state matches a state in some production workflow under `.orca/`.** Prefer an exact type/state match when the production workflow is typed; if the eval is legacy single-type, record the selected production type in the audit notes. If a body state name doesn't appear in any production YAML, the eval is evaluating something that doesn't exist — flag.
- [ ] **`worker.prompt` paths resolve.** For file-based prompts (`prompt: ../../prompts/foo.md`), the file must exist relative to the eval workflow's directory. Verify on disk.
- [ ] **`result_format` is verbatim against production.** For each body state, diff `result_format` against the matched production type/state. Any difference is reported as drift — the eval no longer exercises the production contract.
- [ ] **`worker.prompt` path points at the production prompt.** An eval that ships its own prompt copy is evaluating a copy, not the production prompt. The path should be relative (`../../prompts/...`) and resolve to a file under `.orca/prompts/`.
- [ ] **Outgoing routes from body states land in `assert` or another body state in this file.** Routes to states that exist in production but not in the eval file are dangling references and must be rewritten to `assert`.

**Severity:** drift in `result_format` is **Critical** because the eval is silently evaluating a stale production contract. Dangling routes are **Critical** because config fails to load.

## Phase 4 — Reference integrity

These are the standard workflow-level checks, scoped to the eval file.

- [ ] **All `on:` targets exist.** Every transition target is either a state in `eval-flow.yml`, the literal `assert`, or the built-in `done`/`failed`.
- [ ] **Outcomes and routes agree.** Every key in `on:` must be a value in the state's `result_format.outcome.values`; every non-`waiting` outcome the body/assert worker may emit should route to another body state, `assert`, or `done`.
- [ ] **All body states reachable.** Every body state must be reachable from `initial:` via the `on:` graph. Unreachable body states are dead code in the eval.
- [ ] **Worker `kind` valid.** `claude-code`, `codex`, or `opencode`.
- [ ] **Run bounds accounted for.** `orca eval` submits eval-fast bounds (`max_hops=10`, `max_retries=2`). If an eval is started through another caller, confirm equivalent daemon-level limits or supervise for loop/retry symptoms.

**Severity:** failures here are **Critical** (config invalid) or **Important** (unbounded eval could runaway).

## Phase 5 — Assertions well-formed

- [ ] **One `### <id>` per criterion.** No nested headings under criteria. No `####` sub-criteria.
- [ ] **IDs are kebab-case.** Lowercase letters, digits, hyphens. No spaces, underscores, or capitals.
- [ ] **IDs are unique within the file.** Two criteria with the same id would silently merge in the result JSON.
- [ ] **Prose under each heading is non-empty.** A heading with no prose is unparseable — flag.
- [ ] **Criterion count is reasonable.** Aim for 3–7 per eval. Fewer than 3 → the eval probably under-asserts. More than 10 → the eval is doing too much; consider splitting.
- [ ] **No judgment-heavy criteria.** Flag criteria that ask qualitative questions ("is this prose well-written?", "does this look good?"). Suggest objective rewrites.
- [ ] **References to result fields exist in `result_format`.** If a criterion talks about `findings`, `outcome` values, or any other field, those must appear in some body state's `result_format`. Mismatch means the criterion is ungradeable.

**Severity:** unparseable headings → **Critical**. Judgment-heavy criteria → **Important** (flake-prone). Reference mismatch → **Important** (silent fail-by-default).

## Phase 6 — State branch contract

The contract: every byte in the worktree comes from `state_ref`'s commit history; no LLM-arranged content. See `orca-eval-create.md` ("The state-branch contract") for the rationale.

### Marker & resolution

All commands in this subsection assume the current directory is the repo root.

- [ ] **`state_ref` is present in `input.md` frontmatter.** Grep: `grep -n '^state_ref:' .orca/evals/<name>/input.md` — should return exactly one line.
- [ ] **`state_ref` is not the placeholder.** `TODO_STATE_REF` means the eval predates the current scaffold or was hand-written incompletely. Flag as Critical — the eval cannot run.
- [ ] **`state_ref` resolves to a real branch.** Extract it from the YAML frontmatter, then verify it:
  ```bash
  state_ref=$(awk 'NR==1 && $0=="---"{fm=1; next} fm && $0=="---"{exit} fm && /^state_ref:/{sub(/^state_ref:[[:space:]]*/, ""); print; exit}' .orca/evals/<name>/input.md)
  git rev-parse --verify "$state_ref"
  ```
  Exit code 0 = ref exists. If not, the eval cannot run.
- [ ] **`state_ref` lives in the `orca-eval-state/` namespace.** Branches outside the namespace (e.g. `main`, feature branches) tie the eval to history that changes under your feet. Sharing within the namespace is fine; pointing at `main` is Important.

### Branch contents

- [ ] **State branch contains only scenario-relevant bytes.** Run `git ls-tree --name-only "$state_ref"` using the actual ref from `input.md` — confirm no `.orca/` and no top-level files unrelated to the scenario. `pyproject.toml` or similar config is acceptable only when the state under eval reads it or needs it for verification.
- [ ] **Assertion criteria anchor on bytes in the state branch.** For every criterion that references a literal file path, line number, function name, or fixed string, run `git show "$state_ref":<path>` (or similar) and verify the bytes match. Mismatches mean the state was edited but the criterion wasn't updated.
- [ ] **No body state has its own `setup` re-implementation.** If a body state's prompt instructs the worker to copy files, run git commands, or seed scenario content, it's recreating the deleted setup step — fold those bytes into the state branch instead.

### Issue fields

- [ ] **`input.md` frontmatter covers every `issue.fields.*` the slice's entry state reads.** Cross-reference frontmatter keys with the `issue.fields.*` references in the entry state's prompt and the selected production type's `fields:` block. Missing fields → the slice will fail at first run.

**Severity:** unresolved `state_ref` → **Critical**. Project chrome in state branch → **Important**. Assertion/fixture anchor mismatch → **Critical** (criteria pass or fail for wrong reasons). Missing issue.fields → **Critical**.

## Phase 7 — Drift report

For each body state, produce a comparison table:

```
| State | Prod type/state result_format | Eval result_format | Status |
|---|---|---|---|
| review | <hash or summary> | <hash or summary> | match |
| implementing | outcome.values=[done, blocked] | outcome.values=[done, blocked, waiting] | drift: waiting outcome added in eval |
```

For each `drift` entry, suggest the fix: either update the eval (most common — production is the source of truth) or update production (rare — only if the eval caught a real prod bug).

Hash/summary is up to the auditor — a stable summary string (e.g. sorted `outcome.values` plus the field-name set) is enough to detect drift; a literal text diff is fine too.

## Phase 8 — Report

Use the same format as [`orca-workflow-review.md`](orca-workflow-review.md) so output is greppable:

```
## Eval audit: .orca/evals/<name>/

### Critical
- [state-branch] input.md:L8 — `state_ref` is `TODO_STATE_REF`; create or retarget the state branch and update the marker.
- [assertions] assertions.md:L24 — duplicate id `outcome-is-request-changes`.
- [drift] review — result_format diverges from .orca/review.yml#review: eval adds `waiting` to outcome.values. Re-copy from prod.

### Important
- [assertions] assertions.md:L34 — criterion "messages-are-actionable" asks a judgment question. Rewrite as a regex check (e.g., message starts with a verb from a fixed list).

### Minor
- [state-branch] orca-eval-state/<name> — contains unrelated `README.md` at root. Remove it from the state branch unless the scenario requires the worker to read it.
```

Rules:

- Prefix every finding with the layer: `[structural]`, `[drift]`, `[reference]`, `[assertions]`, or `[state-branch]`.
- Cite `file:line` for line-specific findings. Cite the file alone for shape-level findings (drift, unreachable body, etc).
- Suggest a concrete fix. Refer the user to a specific step in [`orca-eval-create.md`](orca-eval-create.md) when the fix maps to one.
- Sort within each section by file path so reruns produce stable diffs.

## Anti-patterns to flag

- **No body states.** `initial:` points straight at `assert`. The eval grades nothing real. Refuse — ask the user what they meant to eval.
- **A `setup` state.** State-branch evals have no setup state. If you find one, the eval predates the migration — re-scaffold via `orca eval add` or migrate by hand (see `orca-eval-create.md` Step 6).
- **`fixtures/` directory present.** Same as above — the directory is a fossil from the pre-state-branch model. Move its contents into commits on `orca-eval-state/<name>` and delete the directory.
- **Two body states with the same name.** The YAML parser may accept this (silently keeping the last); the eval is unverifiable. Flag as Critical.
- **Body state routes to a state not in this file.** Dangling reference — config fails to load. Critical.
- **Criteria that reference fields not in any `result_format`.** The criterion will silently fail every run. Important.
- **Evals in `.orca/evals/<name>/` without `assertions.md`.** The eval directory is incomplete — the evaluator has nothing to grade against. Critical.
- **`state_ref` points at a branch outside `orca-eval-state/`.** Evals pointing at `main` or feature branches run against history that changes underfoot. Important.

## Done

Report:

- Eval audited: `.orca/evals/<name>/`
- Phase pass/fail summary: structural / slice-integrity / reference / assertions / state-branch
- Counts: Critical / Important / Minor
- Drift table (separate from the main report — drift is high-signal even when not yet broken)
- Total criteria count
- Suggested next step (apply fixes via [`orca-eval-create.md`](orca-eval-create.md), or accept the drift and update production)
