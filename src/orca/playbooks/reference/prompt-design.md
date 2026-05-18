# Prompt Design (Evaluations-First)

The methodology Orca uses to design state prompts: **evaluations come first, prompts are downstream.**

This is a reference, not a procedural playbook. It explains *why* the codebase has [`orca-prompt-create.md`](../orca-prompt-create.md) and [`orca-test-create.md`](../orca-test-create.md), and how to use them under one consistent discipline. Read it before either playbook. The playbooks are the *how*; this doc is the *what for*.

> Audience: you, the agent. Not the user.

## 1. The paradigm

A modern Orca prompt is 200–500 lines of carefully-stacked instructions, variable references, and constraints. It is agent-authored — the user almost never writes a prompt from scratch, and rarely reads one end-to-end. So when output drifts, the natural human moves are unproductive: rewriting from scratch loses prior wins; pasting more details makes the prompt longer, more entangled, and more brittle. Prompts rot.

The antidote is **evaluations** — a small, human-readable, user-curated list of verifiable objectives that the prompt's result must satisfy. Where prompts are long, opaque, and agent-authored, evaluations are short, scannable, and human-authored. They are the durable specification of "what 'good output' means" for a given scenario.

The paradigm has three consequences the agent must internalize:

1. **You don't design a prompt in isolation. You design a prompt *to satisfy* a set of evaluations.** The evaluations exist before the prompt does. The prompt's job is to converge the worker on output that passes them.
2. **When the result is wrong, the first move is reading the report — not editing the prompt.** The report names the failing criterion. The criterion points at the cause. Editing without reading presumes a cause.
3. **"Looks fine to me" is not a valid state.** Either the result passes the evaluations, or it doesn't. If you find yourself eyeballing output to judge quality, you are missing a criterion — write it.

This paradigm overrides [`orca-prompt-create.md`](../orca-prompt-create.md) Step 8 ("Consider a unit test"). Under this paradigm, tests do not come last. They come *first*, in stub form, and evolve alongside the prompt.

## 2. Anatomy of a good evaluation

Each test directory has `evaluations.md` — the user-curated checklist. Its shape is rigid by design.

### Structure

- One `### <id>` heading per criterion. Id is kebab-case and stable across edits — it appears verbatim in `report.md` and in result JSON; renaming an id silently breaks history.
- Prose under the heading IS the criterion. The evaluator reads it literally — it is not a description of the criterion, it *is* the criterion.
- 3–7 criteria per test. Fewer → the test under-asserts. More → the test is doing too much; split it.

### Evidence access

A criterion is gradable only if the evaluator has access to evidence that answers it. The evaluator can read:

- Worktree files after the slice runs
- Per-state results in `{{ run.run_dir }}/state-results/`
- Run summary (`{{ run.summary }}`) — outcomes, transitions, retries
- Session history (`{{ run.sessions }}`)

If answering the criterion requires reading the worker's mind, the user's intent, or a future state that didn't run, rewrite or drop the criterion.

### Primitive types, ranked by reliability

| Rank | Primitive | Example |
|---|---|---|
| 1 | Enum equality | `outcome == request_changes` |
| 2 | Field presence | `findings` is present when `outcome == request_changes` |
| 3 | Count | `len(test_cases) >= 3` |
| 4 | Regex / closed vocabulary | every `function_name` matches `^[a-z_][a-z0-9_]*$` |
| 5 | Set / boundary coverage | union of `files_modified` ⊆ `src/auth/` |
| 6 | Pairwise constraint | no two findings share `(file, line)` |

**Below the line — avoid:** subjective judgment ("title sounds good", "plan is comprehensive", "change makes sense"). Both `setup` and `evaluate` are LLM-driven; the double non-determinism amplifies flake. A criterion that flips run-to-run is worse than no criterion — it teaches you to ignore the report.

### Good / bad rewrites

| Bad (judgment-heavy) | Good (objective) |
|---|---|
| "The code is clean" | "`ruff check .` exits 0" |
| "Tests are thorough" | "Every public function in `src/` has at least one test in `tests/` whose name contains the function name" |
| "The fix is correct" | "`pytest tests/test_auth.py::test_login_with_expired_token` exits 0" |
| "The review caught the bug" | "Some finding has `file == 'src/api.py'` and `line` within 5 of the deliberately-injected SQL injection on line 42" |
| "Names are good" | "Every new identifier matches `^[a-z_][a-z0-9_]*$` (snake_case)" |

Side-effects (commits, edited files) are gradable too — but coarser than `result_format` fields. Prefer field-shape evidence over diff-shape evidence. If a guarantee can move from "the worker committed correctly" into "the `result_format` has field X", move it.

## 3. Designing prompts for checkability

The link between evaluations and prompts is `result_format`. Every criterion needs evidence; every piece of evidence comes from a field in `result_format` or from a worktree side-effect. So the order of design is:

1. **Draft `evaluations.md`** (with the user's help, per Section 4 bootstrap).
2. **Sketch `result_format` *from the evaluations*** — every field a criterion references must be emitted.
3. **Then draft the prompt** — its job is to make the worker emit the `result_format` correctly.

This inverts what feels natural ("write the prompt, then add a result schema"). The inversion is what prevents rot.

### H1. Prefer structured fields over free-form text

Enum outcomes beat free-form `status` strings. Lists of structured items beat markdown blob outputs. Named scalars (counts, ids, paths) beat `summary` fields. Every escape into prose is an escape from checkability.

Bad — a code-review state with everything buried in prose:

```yaml
result_format:
  outcome: { type: enum, values: [approve, request_changes] }
  summary: { type: string }
```

Every interesting criterion ("did the reviewer point at the SQL injection on line 42?", "did it flag more than one issue?", "are the messages actionable?") is unevaluable — the answers are buried in `summary`.

Good — the same state with findings promoted to a typed list:

```yaml
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
```

Now criteria can count findings, check that some finding points at the expected file:line, validate severity, regex-check messages, and detect duplicates.

### H2. Lift constraints from prompt-prose into evaluable fields

A constraint stated only in the prompt is hope; a constraint reflected in the `result_format` (or in a worktree-readable side-effect) is verifiable.

Example: "ONLY modify files under `issue.fields.scope_boundary`". The prompt should still say this. But you also want an evaluation:

```markdown
### scope-boundary-respected
Every path in `git diff --name-only` (for the slice's commits) ends in `.py`
and lives under `issue.fields.scope_boundary` (e.g. `src/auth/`).
No files outside this prefix were modified.
```

Now the constraint is double-bound: stated in the prompt, checked by the test.

### H3. Sketch the result schema *while* drafting evaluations, not after

While drafting each criterion, ask: *what field does this read?* If the answer is "I don't know yet", add the field to a running `result_format` sketch. The two artifacts grow together. By the time evaluations are complete, the schema is already designed — and the prompt has a concrete output contract to converge on.

Cross-reference: [`orca-prompt-create.md`](../orca-prompt-create.md) Step 1 ("Pin down the state's contract") tells you to read `result_format` before drafting the prompt. Under this paradigm, you *design* `result_format` while drafting the evaluations — so by the time that step runs, the contract is already pinned.

## 4. The iteration loop & failure attribution

The canonical loop:

```
[ Bootstrap ]
  2-3 questions  →  draft evaluations.md  →  draft result_format  →  draft stub prompt  →  run

[ Iterate ]
  read report  →  attribute failure  →  minimal edit  →  re-run
                       ↓
                (drift surfaces a new concern → write a criterion FIRST,
                 confirm it fails, then minimal-edit the prompt)
```

### Bootstrap (hybrid)

The agent asks at most 3 questions before writing anything:

1. **What is a one-sentence success?** ("the scoping state should decompose a multi-subsystem spec into non-overlapping sub-issues")
2. **What is an obvious failure mode?** ("it just returns `ready` without splitting", or "the sub_issues overlap")
3. **What shape should the result have?** ("outcome + a list of sub_issues with title and scope_boundary")

Then draft a minimal `evaluations.md` (2–3 criteria from the answers), a minimal `result_format` aligned with them, and a stub prompt. Run the test.

**Cost note.** Every test run is N+2 LLM invocations (1 setup, N body states, 1 evaluate). A single-state slice is the cheapest starting point; default to it. See [`orca-test-create.md`](../orca-test-create.md).

### Failure attribution

When the report shows a failed criterion, walk this taxonomy **before** editing anything:

| Failure mode | Symptom | Fix |
|---|---|---|
| **Prompt** | Worker had access to a clear instruction in the prompt and didn't follow it. | Sharpen or add the relevant instruction. Minimal edit. |
| **Evaluation** | Criterion is ambiguous, judgment-heavy, or references a key not in `result_format`. | Rewrite the criterion. |
| **Scenario** | Test input (`input.md`, fixtures) doesn't actually exercise the path the criterion grades. | Edit `input.md` / fixtures. |
| **`result_format`** | The field the criterion needs isn't emitted. | Add the field to `result_format` AND update the prompt to emit it. |
| **Model** | Output is correct in shape but consistently misses semantic detail across retries. | Swap model in YAML, or split the state into smaller responsibilities. |
| **Flow** | Slice's entry state expected a field that upstream (setup or another state) didn't seed. | Update setup's `result_format` (or the upstream state in production). |

The first three are the common ones. The fourth is the most-missed — it's the one that quietly causes "every criterion fails" reports.

### Minimal-edit discipline

Once attributed, the edit is the *minimum* needed to make the failing criterion pass. Not a broad rewrite. Resist "while we're at it" — that is the rot speaking.

- One failing criterion → one targeted change (one sentence in the prompt, one field in the schema, one line in `evaluations.md`).
- Group cleanups happen on their own pass with their own test runs, not bundled with a fix.

### Drift = new evaluation first

When the user reports a new kind of bad output not currently graded by any criterion, the agent's first move is **not** editing the prompt. It is:

1. Write a criterion in `evaluations.md` that catches the new bad output.
2. Re-run the test — the new criterion should fail. If it passes, the user's complaint is already covered; ask them to point at a failing case.
3. Now attribute the failure and apply the minimal edit.

Never add prompt prose without a failing criterion that justifies it. "Just in case" content is how prompts grow from 100 to 500 lines.

### Changing model or flow

Every change is validated by the same loop. Model swaps (`claude-code` vs `codex` vs `opencode`), `max_hops` adjustments, prompt rewrites, schema changes — none have a "just edit and ship" path. Run the test.

## 5. Worked example

End-to-end walkthrough for a `review` state that audits a Python pull request — a typical Orca use case.

**Cold start.** User says: "I want a `review` state that catches common bugs in Python PRs."

**Bootstrap — 3 questions:**

- *What is a one-sentence success?* → "On a PR that contains a SQL injection, it should request changes and point at the offending file:line; on a clean PR, it should approve."
- *What is an obvious failure mode?* → "It approves a PR with an obvious bug, or it requests changes without saying where the bug is."
- *What shape should the result have?* → "outcome (approve / request_changes), plus a list of findings with file, line, severity, and message."

**Draft `evaluations.md` first (3 criteria).** The scenario in `input.md` will be a PR that introduces a SQL injection at `src/api.py:42`.

```markdown
### outcome-is-request-changes
The review state's `outcome` is `request_changes` (the PR contains a deliberate SQL injection).

### finding-points-at-the-bug
Some `findings[i]` has `file == "src/api.py"` and `line` within 5 of 42.

### findings-have-required-fields
Every finding has a non-empty `file`, a positive integer `line`, a `severity` in `{critical, major, minor}`, and a non-empty `message`.
```

**Design `result_format` to match:**

```yaml
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
```

**Draft a stub prompt** (~40 lines: role, context, 3 numbered steps — read diff, identify bugs, write result — and a result block, per [`orca-prompt-create.md`](../orca-prompt-create.md)).

**First run.** Report: 2 pass, 1 fail (`finding-points-at-the-bug`). The worker said *"the `get_user` function has a SQL injection risk"* but emitted `file: "src/api.py"`, `line: 1`.

**Attribute.** Prompt failure — no instruction telling the worker to set `line` to the exact line of the issue, not the file's first line.

**Minimal edit.** One sentence in Step 2: "For every finding, set `line` to the exact 1-indexed line number of the offending statement, not the file's first line or the function's `def` line."

**Re-run.** 3 pass.

**Later — drift.** User notices that finding messages start with "There is..." or "I see...", which makes them noisy and hard to act on.

**First move:** *not* editing the prompt. Write a criterion:

```markdown
### messages-are-imperative
Every `findings[i].message` matches `^(Use|Remove|Replace|Fix|Add|Avoid)\b`.
```

**Re-run.** The new criterion fails (as expected — it caught the drift).

**Attribute.** Prompt failure — no guidance on message shape.

**Minimal edit.** One sentence: "Each finding's `message` must start with one of these verbs: Use, Remove, Replace, Fix, Add, Avoid."

**Re-run.** 4 pass.

The whole story: evaluations first, attribution second, minimal edit third. Drift creates new criteria, not new prompt prose. The prompt grew by *two sentences* across two improvements — not two paragraphs.

## 6. Anti-patterns

- **Drafting the prompt before the evaluations.** The prompt has nothing to converge on. Refuse and go back to bootstrap.
- **Adding prompt prose to fix drift without a failing evaluation.** Drift = new criterion first, then minimal edit.
- **Criteria that grade process, not output** ("the worker should follow the plan"). The evaluator only sees results, not the worker's thinking.
- **Judgment-heavy criteria** ("title sounds professional"). Replace with regex / closed-vocab, or drop. The bar: could two evaluator runs disagree on this? If yes, rewrite.
- **More than 7 criteria in one test.** Split into multiple tests with different scenarios.
- **Catch-all `result_format` blobs** (`summary: "a markdown writeup"`). Field-shape evidence beats prose-shape evidence every time.
- **Editing the prompt before reading the report.** The fix presumes a cause; the report names the cause.
- **"While we're at it" prompt edits.** Each edit fixes one failing criterion. Cleanups happen on their own pass.
- **Renaming criterion ids on a whim.** Ids are stable identifiers — they appear in `report.md` and the result JSON. Renames silently break history.

## Cross-references

- [`orca-prompt-create.md`](../orca-prompt-create.md) — mechanics of writing a single state prompt (template variables, structure, pitfalls). Read after this doc.
- [`orca-test-create.md`](../orca-test-create.md) — interactive procedure for authoring a test. The bootstrap step in Section 4 above maps to that playbook's Steps 1–8.
- [`orca-test-review.md`](../orca-test-review.md) — audit checklist for an existing test. Use it to verify your evaluations are well-formed.
- [`orca-config-reference.md`](orca-config-reference.md) — full schema reference, including `result_format` field types.
- [`orca-workflow-patterns.md`](orca-workflow-patterns.md) — reusable building blocks for workflows.
