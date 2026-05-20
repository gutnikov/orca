# Playbook: Review (Audit) an Orca Workflow

Audit `.orca/{flow}.yml` and its prompt templates against the three-layer checklist. Produce a structured report (Critical / Important / Minor) with file:line references and concrete fix suggestions. Optionally apply fixes — but only with the right autonomy.

## When to run this

- After **[orca-workflow-create.md](orca-workflow-create.md)** — as the validation step before a test run.
- After a workflow change — adding a state, changing a `result_format`, renaming an outcome.
- After a run surfaces a bug — to figure out whether the config or the prompts are at fault.
- Periodically, as workflows accumulate edits and drift.

## Prerequisites

- Working directory has `.orca/{flow}.yml` plus any `prompts/*.md` files referenced by file-based `worker.prompt` fields.
- You (the agent) have read these once before auditing:
  - [`reference/orca-config-reference.md`](reference/orca-config-reference.md) — what valid config looks like
  - [`orca-prompt-create.md`](orca-prompt-create.md) — what good prompts look like

## Autonomy mode — establish this first

Before doing anything, decide (or ask) which mode you're in. The mode dictates whether you fix anything.

| Mode | What you do |
|---|---|
| `cautious` | Report findings only. Never edit files. |
| `supervised` | Apply fixes for items explicitly enumerated below; escalate anything novel to the user. |
| `full` | Apply any diagnosed fix. Useful for automated audit loops. |

If the user invoked this playbook from a chat session, default to **supervised** unless told otherwise. If invoked from an automated context, the caller should pass the autonomy level.

## Phase 1 — Inventory

Identify exactly what you're auditing.

1. List workflows: `ls .orca/*.yml`
2. Pick the target — if there's only one, use it; otherwise ask the user.
3. Parse the YAML and enumerate:
   - All state names
   - All `on:` rules (transitions)
   - All `result_format` outcomes per state
   - All `worker.prompt` sources (file or inline)
4. Read each referenced prompt file.

Build a small in-memory map of `state → outcomes → transitions → prompt source` before running checks. Many checks cross-reference these.

## Phase 2 — Layer 1: Structural checks (will it break?)

Run every item below. These catch config errors that cause runtime failures.

- [ ] **All `on:` targets exist** — every transition target is a state name in `states:` or a built-in target (`done`, `failed`). The built-in `failed` is **not** a destination state but a directive that triggers worker-failure handling for that outcome. Check both simple transitions (`done: testing`) and decompose rules (`then: done`).
- [ ] **Outcomes and routes agree** — every key in `on:` must be a value in `result_format.outcome.values`; every non-`waiting` outcome the worker may emit should have an `on:` route. Mismatched `on:` keys fail config load; unrouted emitted outcomes fail at runtime.
- [ ] **At least one routable outcome** — every active state has ≥1 outcome with an `on:` rule. Otherwise the state cannot progress.
- [ ] **Decompose has `sub_issues`** — any state with `on: { X: { action: decompose } }` must have `sub_issues: { type: list, items: "$issue" }` in its `result_format`.
- [ ] **Decompose `child_type` exists** — if `child_type: task` is specified, `task` must be a key in `types:`. In typed configs, a decompose rule should set `child_type` unless the prompt explicitly emits `type` on every child.
- [ ] **No reserved state names** — no states named `done` or `failed` in `states:`.
- [ ] **All active states reachable** — every non-initial active state is reachable from `initial` via `on:` rules. Passive states (no worker, no `on:`) are parser-exempt because humans can advance to them from another passive state; still confirm each passive state is an intentional manual target rather than leftover YAML.
- [ ] **Worker `kind` valid** — `claude-code`, `codex`, or `opencode`.
- [ ] **Worker `prompt` non-empty** — `prompt` field present and non-empty.
- [ ] **Prompt sources exist** — every file-based `worker.prompt` path resolves to a real file, and every inline prompt has non-empty `text`. Verify with the filesystem, not trust.

Anything failing here is **Critical**.

## Phase 3 — Layer 2: Efficiency checks (anti-patterns)

- [ ] **Single responsibility per state** — no prompt does two distinct jobs (e.g. "plan and implement"). Phrases like "first do X, then do Y" where X and Y are different kinds of work → split into two states.
- [ ] **Fail-safe outcomes present** — every active state has `blocked` or another escape hatch beyond happy-path outcomes. Workers can also use the built-in `waiting` outcome for human-in-the-loop.
- [ ] **Merge/apply states serialized** — states that merge branches or write to shared resources have `max_workers: 1`.
- [ ] **Run bounds are accounted for** — `max_hops` and `max_worker_retries` are launch-time limits in the current engine, not workflow YAML fields. CLI runs default to 10 / 3; wrappers, MCP callers, and tests need explicit supervision or caller-level limits because YAML alone will not bound them.
- [ ] **Timeouts set for long states** — heavy-work states (implementing, testing) have `timeout` or `inactivity_timeout`. Default inactivity timeout is 300s (5 min) which is often too short.
- [ ] **Decomposition scope boundaries** — when a state decomposes, the prompt instructs the worker to define clear, non-overlapping `scope_boundary` fields for sub-issues. Overlap = workers stomping each other.
- [ ] **No unnecessary serialization** — `max_workers: 1` only where genuinely needed (merging, deploying). Serializing independent work wastes wall-clock time.

Items here are usually **Important**, sometimes **Minor** depending on impact.

## Phase 4 — Layer 3: Prompt quality checks

For each prompt file, verify:

- [ ] **Concrete result example embedded** — prompt contains `{{ result_example | tojson(indent=2) }}` or a hand-written valid result example. Workers that copy the schema produce invalid results.
- [ ] **`result_path` referenced** — prompt contains `{{ result_path }}` telling the worker where to write the result file.
- [ ] **Constraints near end** — constraints are in a dedicated `## Constraints` section in the bottom half. Workers forget early constraints.
- [ ] **No hardcoded issue-derived values** — values that vary by issue use `{{ issue.fields.* }}` or other template variables. Especially scope boundaries, branch names, and user-provided paths. Fixed project commands and fixed repository paths are fine when they are genuinely workflow constants.
- [ ] **Verification step present** — prompt includes a step to verify work (tests, lint, typecheck) before committing.
- [ ] **Commit before result** — prompt explicitly says commit all changes *before* writing the result file. The orchestrator kills the session ~30s after detecting a valid result.
- [ ] **Scope boundary enforced** — if `scope_boundary` field exists, prompt has a constraint like *"ONLY modify files under `{{ issue.fields.scope_boundary }}`."*
- [ ] **Conditional sections guarded** — sections referencing optional data (`depends_on`, `children`, `event_log`) use `{% if %}` guards.
- [ ] **Single clear responsibility** — prompt describes one job. Two-job prompts → split.
- [ ] **Result file is final action** — prompt says writing any non-`waiting` result file is the last thing the worker does. No work after it.

Most items here are **Important**; missing `result_format` or `result_path` is **Critical**.

## Phase 5 — Report

Use this exact reporting format so output is greppable and machine-friendly:

```
## Audit: .orca/<flow>.yml

### Critical
- [structural] State "reviewing" not reachable from initial state "planning" — no on: rule targets it
- [prompt] prompts/scoping.md — result_format not embedded; workers will guess JSON shape

### Important
- [efficiency] State "implementing" has no fail-safe outcome — only [done]. Add "blocked".
- [prompt] prompts/planning.md:L12 — hardcoded "src/auth/" instead of {{ issue.fields.scope_boundary }}

### Minor
- [efficiency] No inactivity_timeout on implementing state (uses default 300s — may be too short for this codebase)
- [prompt] prompts/reviewing.md — constraints section appears near the top; consider moving to bottom half
```

Rules:
- Prefix every finding with the layer: `[structural]`, `[efficiency]`, or `[prompt]`.
- Citation rules:
  - `[prompt]` findings: cite `file:line` whenever the issue is at a specific line (hardcoded value, missing constraint, wrong reference). Cite the whole file only when the issue is structural to the prompt (missing section).
  - `[structural]` findings: name the file (`.orca/{flow}.yml`); these are graph-level claims (unreachable state, missing transition) and don't have a meaningful line.
  - `[efficiency]` findings: cite the YAML file:line for the relevant state block when the fix is local; name the file when the finding is about workflow shape.
- Suggest a concrete fix — not "this is wrong", but "do X".
- Sort within each section by file path so reruns produce stable diffs.

## Phase 6 — Apply fixes (autonomy-gated)

Only proceed if autonomy mode permits.

### `cautious`
Stop after Phase 5. Print the report. Done.

### `supervised`

Apply fixes that have a single, mechanical answer. Escalate anything that needs user input first.

**Mechanical (apply directly):**
- Add missing `{{ result_example | tojson(indent=2) }}` / `{{ result_path }}` blocks where the section exists but the variable is absent.
- Add `max_workers: 1` to a state the user *has already named* as a merge/apply state.
- Wrap conditional sections (`depends_on`, `children`, `event_log`) in `{% if %}` guards.
- Replace hardcoded values with `{{ issue.fields.* }}` references **only if** the field already exists in the issue schema.

**Partially mechanical (do not half-apply):**
- *Missing `blocked` outcome.* Adding `blocked` to `result_format.outcome.values` is easy, but the workflow also needs a route and prompt instructions for what `blocked` means. Report the missing escape hatch and propose a target if one is obvious; ask before changing the workflow.

**Never silent:**
- State-machine restructure, splitting a prompt, changing `result_format` shape, renaming outcomes — escalate with the report and a proposed change. Do not apply.

### `full`
Apply any diagnosed fix. Still:
- Never delete a state without explicit reason in the diagnosis.
- Never change `initial:` without user input.
- Never rename outcomes (it cascades to every `on:` rule + the prompts; do it as a coordinated edit and confirm).

After applying fixes, **rerun phases 2–4** to verify nothing regressed. Report the second-pass result.

## Phase 7 — Offer a test run

If the audit produced fixes (or even if it didn't and the user wants confidence):

> "Audit complete. Want me to run a small smoke test via [orca-workflow-run.md](orca-workflow-run.md) to confirm nothing regressed?"

If a test run surfaces new issues, loop back to the relevant phase — don't patch ad-hoc.

## Tests under `.orca/tests/`

If `.orca/tests/` exists in the repo, the audit is incomplete without checking the tests. For each directory under `.orca/tests/`, delegate to [orca-test-review.md](orca-test-review.md) and fold its findings into your audit report alongside the workflow findings.

Tests are not optional once they exist — stale tests are worse than no tests, because they create false confidence. Treat a Critical finding in a test (e.g. drift between body `result_format` and production) as Critical for the workflow audit as a whole.

If the user changed a production `result_format` in this audit pass, every test that copied that state is now drifted by definition. Surface this proactively rather than waiting for the next test run to fail.

## Anti-patterns to refuse

- **Hand-wavy "looks good".** If you didn't run every checklist item, you didn't audit — say so.
- **Silent restructure.** Splitting a state, renaming an outcome, or changing `result_format` shape is never a supervised-mode fix.
- **Fixes without a re-audit.** If you edited anything, rerun the checklist. A "fixed" workflow can have new issues introduced by the fix.
- **Glossing critical items.** Every Critical must either be fixed or surfaced. Never bury a Critical in a Minor list.

## Done

Report:
- File audited
- Counts: Critical / Important / Minor
- Whether fixes were applied (and which mode)
- Whether the re-audit was clean
- Next step (test run, commit, or escalate)
