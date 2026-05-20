# Playbook: Create an Orca Eval (Interactive)

Author a small orca eval under `.orca/evals/<name>/` that exercises a slice of a production workflow under controlled conditions and grades the result against a declarative pass/fail checklist.

An **orca eval** is just an orca workflow with a fixed shape:

```
[ 1..N states under eval, copied from prod ] -> assert
```

The body states are copied from a production workflow YAML with only eval-harness rewrites: prompt paths are made relative to `eval-flow.yml`, and routes leaving the slice are redirected to `assert`. The prompts under eval are still the production prompt files. The worktree is checked out from the state branch declared in `input.md` frontmatter (`state_ref`); `assert` grades the result against `assertions.md` and writes `report.md` into the run directory.

This playbook is **conversational**. Walk the user through every step, show your work, and ask before silently making decisions that change the shape of the eval.

## Required reading (you, the agent — not the user)

Before asking the user anything:

- [`reference/assertions-design.md`](reference/assertions-design.md) — explains why evals anchor prompt behavior and how semantic assertions drive prompt changes
- [`orca-eval-review.md`](orca-eval-review.md) — the audit checklist you'll run at the end
- [`reference/orca-config-reference.md`](reference/orca-config-reference.md) — full workflow schema (evals are workflows)
- [`reference/orca-workflow-patterns.md`](reference/orca-workflow-patterns.md) — the building blocks you may reuse
- [`orca-prompt-create.md`](orca-prompt-create.md) — inline-prompt conventions used in `assert`

## Prerequisites

- Orca CLI installed and the daemon running.
- Working directory is a git repo with a `.orca/` directory.
- At least one production workflow YAML exists under `.orca/` to eval against — without one, there's no slice to copy.
- You can name the eval in kebab-case. The directory name *is* the eval name.

## Modes

This playbook runs in one of two modes. Pick the right one *before* Step 1; the steps below assume you've made the call.

### Create mode (default)

You're starting from nothing — no `.orca/evals/<name>/` directory yet. Run all nine steps end to end.

### Update mode

An eval directory already exists and you're extending it. Two common arrivals:

- **Adding semantic criteria to a scaffolded smoke eval.** `orca-workflow-create` Step 8 ships a structural `<state>-smoke` eval per active state (enum coverage, `required_when` presence). The directory, `eval-flow.yml`, `result_format`, and a minimal structural `assertions.md` already exist. **Skip Step 3 (Scaffold) and most of Step 5 (Copy body states); use Step 2 to design the real scenario, then Step 4 (write `input.md`), Step 6 (author the state branch), and Step 8 (append semantic criteria).** Do not rewrite the structural criteria — they're still load-bearing.
- **`orca-workflow-run` handed off a failure case.** Supervision surfaced a real-world failure mode worth capturing. You arrive with a context block (failing state, scenario summary, worker input/output, log tail). Use it as the seed for Step 1 (Decide the slice) and Step 2 (Sketch the scenario), then continue from Step 3 if no eval directory exists yet, or jump to Step 4 if one does.

In either Update-mode flow, walk the *Anti-patterns to refuse* checklist at the end before declaring done — it's the easiest place to introduce drift while editing.

## Cost note — surface this before the first run

Every eval run costs **N + 1 LLM invocations** (N body states + 1 assert). A 5-state slice = 6 worker sessions per run. The worktree is set up by `git checkout` rather than an LLM, so there is no per-run setup cost. Prefer **single-state slices** for first evals — they're the cheapest way to start and the easiest to debug.

## The state-branch contract

Read this **before drafting any of the steps below**. It is the load-bearing discipline that keeps evals deterministic. Two roles, sharp boundaries:

- **The state branch** (`orca-eval-state/<name>`) is the source of every byte *in the worktree* that the worker will read. **Worktree creativity lives here, and only here.**
- **Assertions** anchor on stable bytes in the state branch — literal line numbers, paths, function names. **They reference what the state branch contains, not what the orchestrator might produce.**

The non-negotiable rule: every byte *the worker reads from its worktree* came from the state branch, not from any LLM decision at run time. If a criterion says `line within 5 of 42`, then line 42 is where the *state branch* puts the bug — pinned by a commit you reviewed before merging the eval.

(The prompts and `assertions.md` live on the iteration branch, not the state branch — they're eval configuration, not worktree content. The "every byte" rule applies to worktree bytes only.)

Why this is the rule: state-branch bytes are stable, version-controlled, and easy to inspect. Any byte produced by an LLM at run time varies run-to-run; criteria that depend on such bytes become flaky. The cure is to drain creativity out of run time and into git history — commits are bytes on disk; nobody reinterprets them.

The steps that follow operationalise this contract: Step 5 copies the slice; Step 6 authors the state branch; Step 8 writes assertions that cite state-branch facts.

## Interactive process

Run the steps in order. After each, show what you produced and ask the user to confirm before moving on.

### Step 1 — Decide the slice

Ask the user, in plain language:

1. **Which workflow?** `ls .orca/*.yml` and list candidates. If there's only one, name it; otherwise ask.
2. **Which states?** One of:
   - **Single state** (unit eval of one prompt — e.g. just `review`). Default suggestion.
   - **Subgraph** (integration eval of a slice — e.g. `planning -> implementing`).
   - **Full workflow** (end-to-end — every active state).
3. **What does success look like?** One sentence: "the slice should …". This becomes the seed for `assertions.md`.

Echo back what you understood:

> "You want a unit eval of the `review` state in `.orca/review.yml`. Success means: given a PR that introduces a SQL injection at `src/api.py:42`, the review state should produce `outcome=request_changes` with at least one finding pointing at that file:line. Right?"

**Do not move on until the user confirms.**

### Step 2 — Sketch the scenario

One paragraph. Write the situation the slice will face and what it should do.

> "A user submits a PR that adds a `get_user` helper to `src/api.py`. The helper builds a SQL query via f-string interpolation on line 42 — a textbook SQL injection. The review state should read the diff, identify the unsafe interpolation, and emit `outcome=request_changes` with at least one finding whose `file` is `src/api.py` and whose `line` is near 42."

This paragraph drives three downstream artefacts:

- `input.md` body (the prose context — for a human reader)
- the state branch commits (what the worktree should contain before the slice runs)
- `assertions.md` (the criteria — derived from "should do" wording above)

Show the paragraph and ask the user to refine. Do not start writing files yet.

### Step 3 — Scaffold the directory

Pick a kebab-case name that describes the scenario, not the state:

| Good | Bad |
|---|---|
| `review-catches-sql-injection` | `eval-1`, `review-eval` |
| `implementing-adds-pagination-to-endpoint` | `implementing` |
| `planning-splits-multi-module-feature` | `eval-plan` |

Then scaffold:

```bash
orca eval add review-catches-sql-injection
```

This creates `.orca/evals/review-catches-sql-injection/` with skeleton `eval-flow.yml`, `input.md`, `assertions.md`. It also creates the orphan branch `orca-eval-state/review-catches-sql-injection` and a persistent author worktree at `.orca-state/eval-states/review-catches-sql-injection/`. **Edit the skeleton in place** — don't write a fresh structure beside it.

#### If `orca eval add` errors

- **`eval directory already exists`** — the `.orca/evals/<name>/` directory already exists. Either pick a different name or, if you're recovering from an aborted attempt, remove the persistent worktree and then the orphan branch (`git worktree remove .orca-state/eval-states/<name> && git branch -D orca-eval-state/<name>`) before retrying.
- **`state branch already exists: orca-eval-state/<name>`** — the orphan branch is present but the eval directory isn't. Either you're reusing a branch from a deleted eval (sharing — see below) and you should hand-create the `.orca/evals/<name>/` skeleton instead of using `orca eval add`, or there's leftover state to clean up first.

#### Sharing a state branch across multiple evals

Multiple evals may point `state_ref` at the same `orca-eval-state/<branch>` if they exercise the same fixture. To share:

1. Scaffold the first eval normally with `orca eval add`. Author the state branch from its persistent worktree.
2. Scaffold the second eval with `orca eval add`, then edit its `input.md` to retarget `state_ref:` at the first eval's branch. The second eval's own orphan branch becomes unused — you can delete its worktree first and then the branch (`git worktree remove .orca-state/eval-states/<second-name>` followed by `git branch -D orca-eval-state/<second-name>`) or leave it as an empty seed.

When the shared branch is updated, every eval pointing at it picks up the new tip on the next run. That's the point — and the risk: a tweak that helps one eval may break another. Run all sharing evals after any state-branch edit.

#### Should you push the `orca-eval-state/<name>` branch?

Yes — these branches are part of the eval fixture and need to travel with the repo. Evals are unrunnable on a fresh clone if the branches are local-only. Push them alongside the eval directory commit. Treat them like any other eval asset; rebases on them are fine, but force-pushes will invalidate any in-flight CI runs that already checked out the prior tip.

### Step 4 — Write `input.md`

Two sections: YAML frontmatter (engine-parsed into `issue.fields.*` before the first body state runs) and freeform prose body. The frontmatter also carries the `state_ref` marker — the scaffold stamps it; you generally don't need to edit it.

Before:

```markdown
---
title: "TODO: a one-line title for the eval scenario"
description: |
  TODO: a one-paragraph description of the situation the slice should handle.
state_ref: orca-eval-state/<eval-name>
---

# Scenario

TODO: describe (for a human reader) what this eval asserts and how the
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
state_ref: orca-eval-state/review-catches-sql-injection
---

# Scenario

The user submitted a PR that introduces a SQL injection on line 42 of
`src/api.py`. The state branch `orca-eval-state/review-catches-sql-injection`
carries that file at the expected path. The review state should read the
diff, identify the unsafe f-string into a SQL query, and emit
`outcome=request_changes` with a finding that points at `src/api.py:42`.
```

Rules:

- Frontmatter keys are issue field names. **Only declare fields the slice's entry state actually reads.** Cross-check against `issue.fields` in the production workflow.
- `state_ref` is required. Without it `orca eval <name>` refuses to start the run.
- Prose body is for the reader's eyes — it does not seed `issue.fields`.
- If the eval should share state with another eval, point `state_ref` at that eval's branch instead of the scaffolded default.

### Step 5 — Copy slice states into `eval-flow.yml`

The skeleton has placeholders. Replace them with body states copied from production, applying only the eval-harness rewrites below.

**Rewrite rules.** For each body state copied from production:

1. **`result_format` is copied verbatim.** Drift here is the whole point of having evals — keep them in sync.
2. **Internal transitions stay verbatim.** If `planning` in prod routes `done -> implementing` and both states are in the slice, copy the rule unchanged.
3. **Outgoing-to-outside-slice transitions are rewritten to `assert`.** If `implementing` in prod routes `done -> reviewing` but `reviewing` is *not* in the slice, rewrite to `done -> assert`. The same applies to any rule that targets the built-in `done` — rewrite to `assert` so the grader sees the final result.
4. **`initial:` names the slice's entry state.** Replace the placeholder `initial: TODO_BODY_STATE` with the real entry state name (e.g. `initial: review`).

Concrete example — copying a single `review` state from `.orca/review.yml`. Both YAML blocks below are shown under their own file's `states:` parent (the parent is included for context — do not double-nest when you copy).

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

After (in `.orca/evals/review-catches-sql-injection/eval-flow.yml`):

```yaml
states:
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
      approve: assert
      request_changes: assert
      blocked: assert
  assert:
    # ... see Step 7 below
```

Notes:

- The `prompt:` path is now `../../prompts/review.md` — relative to `eval-flow.yml`. The loader resolves it at load time; the worker never sees `..`.
- The production `request_changes: revising` transition is collapsed to a plain `assert` route. Evals grade against the slice's *output*, not the orchestrator's downstream behaviour. We don't want the `revising` state to spawn during an eval — the `assert` state inspects the `findings` field directly.
- Every outcome routes to `assert`. The grader decides pass/fail; the slice never reaches `done` on its own.

After editing the body, replace the placeholder `initial: TODO_BODY_STATE` with the entry state name (here, `review`). Then the file's `review -> assert` shape is complete.

### Step 6 — Author the state branch

`orca eval add <name>` already created `orca-eval-state/<name>` as an orphan branch and a persistent author worktree at `.orca-state/eval-states/<name>/`. Now you arrange the fixture bytes there using plain git — no orca tooling involved.

```
cd .orca-state/eval-states/<name>/
# write the files the slice will read
vim src/api.py
# commit when the state is ready
git add . && git commit -m "seed: <describe the scenario>"
```

#### Rules

- **Stable facts go in commits, not in run-time prompts.** A criterion that says "line 42 contains the SQL injection" anchors on a byte that the state branch carries. There is no LLM that could move it.
- **Minimum realistic context.** A state branch contains *just* enough plausible code to make the diff look like real work and to make the scenario interpretable. No filler.
- **Minimal project chrome.** Do not commit `.orca/` to the state branch. Avoid `pyproject.toml`, `README.md`, or other top-level files unless the state under eval actually reads them or needs them for a verification command. The orchestrator reads workflow YAML and prompts from the iteration branch; the worktree should contain only scenario-relevant bytes.
- **Sharing.** Multiple evals can point `state_ref` at the same branch. After `orca eval add` creates `orca-eval-state/<eval-name>`, edit `input.md` to retarget the marker if you want this eval to share an already-authored state.
- **Iteration.** `cd` back into the author worktree, edit, commit. The next eval run picks up the new tip automatically — `state_ref` is a ref name, not a commit hash.

#### Cross-checking facts

If a criterion anchors on `src/api.py:42`, count the lines in the file the state branch carries and verify line 42 is the bug. The fact and the file must agree. Both live in git now, so a single mismatch becomes a deliberate commit you can review.

### Step 7 — Leave the assert prompt alone (usually)

The assert state is an agent worker that reads `{{ run.repo_root }}/.orca/evals/{{ run.eval_name }}/assertions.md`, inspects the worktree and per-state results, grades each criterion, writes `{{ run.run_dir }}/report.md`, and emits a structured result at `{{ result_path }}`.

`orca eval add` ships a minimal inline prompt that does exactly this. It's deliberately terse:

````yaml
    worker:
      kind: claude-code
      prompt:
        text: |
          # Assert
          Read {{ run.repo_root }}/.orca/evals/{{ run.eval_name }}/assertions.md, grade each criterion,
          write {{ run.run_dir }}/report.md, then write {{ result_path }}.

          ```json
          {{ result_example | tojson(indent=2) }}
          ```
      inactivity_timeout: 600
      result_format:
        outcome:
          type: enum
          values: [passed, failed, inconclusive]
        criteria:
          type: list
          items: "string"
    on:
      passed: done
      failed: done
      inconclusive: done
````

**Keep the scaffold as-is for most evals.** The evaluator agent knows how to read assertions and produce a report from a short instruction; over-specifying the prompt risks the evaluator overfitting to a particular report shape and missing criteria that don't fit it. The terseness is intentional, not provisional.

Extend the prompt only when the scaffold demonstrably falls short — e.g. the evaluator is consistently failing to gather evidence from the right place, or you need a specific report layout for a downstream consumer. Reasonable extensions, in increasing order of intrusiveness:

- Add a *gather evidence* line listing the dirs to inspect (worktree, `{{ run.run_dir }}/state-results/`, `{{ run.summary }}`, `{{ run.sessions }}`).
- Add a *grading rubric* line defining `pass` / `fail` / `not_applicable`.
- Add a *report shape* template if the report needs a fixed columnar layout.
- Add explicit *outcome rules* (`passed = all pass-or-na`; `failed = any fail`; `inconclusive = ungradeable`).

If you make any of these changes, add a one-line comment above the change naming the symptom it fixes — otherwise future you will trim it back as "extra".

The skeleton's three outcomes (`passed`, `failed`, `inconclusive`) already route to `done`; leave that wiring alone — the eval terminates after evaluation in every case.

### Step 8 — Write `assertions.md`

The pass/fail checklist. One criterion per `### <id>` heading.

Before:

```markdown
# Assertions: TODO

TODO: one paragraph describing what this eval asserts overall.

## Criteria

### criterion-id-here
TODO: a sentence stating one concrete, gradeable thing the result must satisfy.
```

After (concrete):

```markdown
# Assertions: review-catches-sql-injection

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
- **Prefer objective criteria over judgment-heavy ones.** Counts, presence, regexes, enum equality are reproducible. "Is this prose good?" flip-flops between runs (both the body worker and assert evaluator are LLM-driven — the double non-determinism amplifies).
- No ordering. No severity/weighting. Pass/fail only in v1.
- Optional `## Setup notes` or `## Context` sections at the top are passed through as background and not graded.

Aim for **3–7 criteria** for a first draft. Fewer is fine if the eval is narrow.

### Step 9 — Run the eval

```bash
orca eval review-catches-sql-injection
```

The CLI submits the run to the daemon with eval-fast bounds (`max_hops=10`, `max_retries=2`) and prints the run id. The CLI is currently fire-and-forget in v1 — it does not block until completion. Use `orca runs` or the TUI to watch progress.

After the run completes, read the report:

```bash
cat .orca-state/runs/<branch>/<workflow>/report.md
```

The layout is `.orca-state/runs/<branch>/<workflow>/` — for `orca eval <name>`, the `<branch>` segment defaults to `orca-eval-run-<name>` and the `<workflow>` segment is the eval name. The path printed by the assert state at end-of-run is the canonical one — copy from there if you're unsure.

**Iterate.** First runs usually surface one of three problems:

| Symptom | Likely cause | Fix |
|---|---|---|
| Daemon error: `state ref '<...>' not found` | The state branch was deleted or renamed, or `state_ref` in `input.md` is wrong. | `git branch --list 'orca-eval-state/*'` to confirm; recreate via `orca eval add` or fix the marker. |
| Worktree contents look wrong | State branch tip changed since the author last edited; or someone committed `.orca/` or other chrome to the state branch. | `cd .orca-state/eval-states/<name>/ && git log --oneline` to inspect; amend or reset as needed. |
| Slice fails with worker error | `result_format` drift between eval and prod, or the production prompt has a bug. | Re-copy `result_format` verbatim from prod; if still failing, the prompt itself is buggy — fix in prod. |
| Criteria flip-flop run-to-run | Judgment-heavy criteria. | Rewrite to be objective (counts, presence, regexes). |
| Every criterion `fail` | Assert prompt isn't reading evidence from the right place. | Double-check `{{ run.run_dir }}/state-results/` references; confirm the slice actually emitted a result. |

## Anti-patterns to refuse

- **State branches bloated with project chrome.** Committing `.orca/` or unrelated top-level files to `orca-eval-state/<name>` makes the branch confusing to inspect and risks the worker reading state from the wrong place. Keep only the bytes the slice will actually read, plus minimal config files required by the state's verification commands.
- **`state_ref` pointing at a branch outside the `orca-eval-state/` namespace.** Evals pointing at `main` or a feature branch run against arbitrary history that may change underfoot. Use the dedicated namespace; share within it freely.
- **More than one `assert` state.** The shape is body→assert — exactly one assert. If you need branching, branch in the body.
- **Body states whose `result_format` differs from production.** That defeats the point of the eval. If you need a different schema, you're not evaluating the prompt — you're evaluating something else. Stop and ask the user what they actually want to evaluate.
- **Judgment-heavy criteria.** "Is this prose well-written?" "Does this title sound good?" Replace with objective evals or drop the criterion.
- **`assert` routing anywhere except `done`.** All three outcomes (`passed`, `failed`, `inconclusive`) terminate the eval.
- **Calling the eval directory `eval-1`, `eval-foo`, `unit-eval`.** Use a descriptive kebab-case name that says what the scenario evaluates.

## Done

Report:

- Directory created: `.orca/evals/<name>/`
- Files: `eval-flow.yml`, `input.md` (with `state_ref` marker), `assertions.md`
- State branch: `orca-eval-state/<name>` (commits arranging the worktree)
- Slice shape: single-state / subgraph / e2e — and which states
- Criteria count
- Whether a first run was performed and its outcome
- Path to `report.md` (if a run completed)
- Next step (iterate on prompts/criteria, or commit the eval and move on)
