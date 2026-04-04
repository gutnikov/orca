# Audit Checklist

Three-layer audit for orca workflows. Run all checks against `orca.{flow}.yml` and its prompt templates. Report findings as critical (will break), important (anti-pattern), or minor (could be better).

## Layer 1: Structural Checks

These catch config errors that will cause runtime failures.

- [ ] **All on: targets exist** — every transition target is a state name or built-in state (`done`, `failed`). Check both simple transitions (`done: testing`) and decompose rules (`then: done`).

- [ ] **Outcomes match on: keys** — every key in `on:` must be a value in `result_format.outcome.values`. If `on:` says `ready: planning` but outcome values don't include `ready`, config will fail to load.

- [ ] **At least one routable outcome** — every active state has ≥1 non-reserved outcome with an `on:` rule. A state with only `needs_feedback` as its outcome cannot progress.

- [ ] **Decompose has sub_issues** — any state with `on: { X: { action: decompose } }` must have `sub_issues: { type: list, items: "$issue" }` in its `result_format`.

- [ ] **Decompose child_type exists** — if `child_type: task` is specified, `task` must be a key in `types:`.

- [ ] **No reserved state names** — no states named `done` or `failed` in the `states:` block.

- [ ] **All states reachable** — every non-initial, non-passive state can be reached from the initial state via `on:` rules. Passive states (no worker, no on:) are exempt.

- [ ] **Worker kind valid** — `kind` is `claude-code` or `opencode`.

- [ ] **Worker prompt non-empty** — `prompt` field is present and non-empty for every worker.

- [ ] **Prompt files exist** — every `worker.prompt` path points to an actual file. Check with `ls <path>`.

## Layer 2: Efficiency Checks

These catch anti-patterns that waste time or cause confusing behavior.

- [ ] **Single responsibility per state** — no state's prompt does two distinct jobs (e.g. "plan and implement"). If a prompt has two major phases, split into two states.

- [ ] **Fail-safe outcomes present** — every active state has `blocked`, `needs_feedback`, or some escape hatch beyond the happy-path outcome. Without this, workers report "done" even when stuck.

- [ ] **Merge/apply states serialized** — states that merge branches or write to shared resources have `max_workers: 1`. Without this, concurrent merges cause conflicts.

- [ ] **max_hops is set** — global `max_hops` prevents infinite state transition loops. Recommended: 10-20 depending on workflow complexity.

- [ ] **max_worker_retries is set** — prevents infinite failure retries. Recommended: 3-5.

- [ ] **Timeouts set for long states** — states where workers do heavy work (implementing, testing) should have `timeout` or `inactivity_timeout`. Default inactivity timeout is 300s (5 min) which may be too short for complex tasks.

- [ ] **Decomposition scope boundaries** — when a state decomposes issues, the prompt instructs the worker to define clear, non-overlapping `scope_boundary` fields for sub-issues. Overlapping scopes cause workers to edit each other's files.

- [ ] **No unnecessary serialization** — `max_workers: 1` only on states that genuinely need it (merging, deploying). Serializing implementation or planning states wastes time.

## Layer 3: Prompt Quality Checks

These catch prompt issues that cause worker failures or poor output.

- [ ] **result_format embedded** — prompt contains `{{ result_format | tojson(indent=2) }}` or shows the exact JSON schema the worker must produce. Workers that guess the format produce invalid results.

- [ ] **result_path referenced** — prompt contains `{{ result_path }}` telling the worker where to write the result file.

- [ ] **Constraints near end** — constraints are in a dedicated `## Constraints` section in the bottom half of the prompt, not buried in the introduction. Workers forget early constraints.

- [ ] **No hardcoded values** — values that come from issue fields use `{{ issue.fields.* }}` template variables, not hardcoded strings. Especially: scope boundaries, branch names, file paths.

- [ ] **Verification step present** — prompt includes a step to verify work (run tests, lint, typecheck) before committing. Without this, workers produce untested code.

- [ ] **Commit before result** — prompt explicitly says to commit all changes before writing the result file. The orchestrator kills the session ~30s after detecting a valid result.

- [ ] **Scope boundary enforced** — if `scope_boundary` field exists, prompt has a constraint like "ONLY modify files under {{ issue.fields.scope_boundary }}."

- [ ] **Conditional sections guarded** — sections that reference optional data (feedback_context, depends_on, children) use `{% if %}` guards so they don't render as empty headers.

- [ ] **Single clear responsibility** — prompt describes one job. If you find phrases like "first do X, then do Y" where X and Y are different kinds of work, the state should be split.

- [ ] **Result file is final action** — prompt says writing the result file is the last thing the worker does. No work planned after it.

## Reporting Format

After running all checks, report like this:

```
## Audit: orca.develop.yml

### Critical
- [structural] State "reviewing" not reachable from initial state "planning" — no on: rule targets it
- [structural] prompts/implementing.md does not exist (referenced by implementing.worker.prompt)

### Important
- [efficiency] State "implementing" has no fail-safe outcome — only [done]. Add "blocked" or "needs_feedback"
- [prompt] prompts/scoping.md:L45 — result_format not embedded. Workers will guess JSON shape.

### Minor
- [prompt] prompts/planning.md:L12 — hardcoded "src/auth/" instead of {{ issue.fields.scope_boundary }}
- [efficiency] No inactivity_timeout on implementing state (uses default 300s — may be too short)
```
