# Assertion Design

The methodology Orca uses to anchor prompt behavior to a durable, user-curated specification: semantic fixes are driven by assertions, and prompts are downstream of the state/result contract.

This is a reference, not a procedural playbook. It explains *why* the codebase has [`orca-eval-create.md`](../orca-eval-create.md) and [`orca-prompt-create.md`](../orca-prompt-create.md), and how to use them under one consistent discipline. Read it before either playbook. The playbooks are the *how*; this doc is the *what for*.

> Audience: you, the agent. Not the user.

## 1. The paradigm

A modern Orca prompt is 200–500 lines of carefully-stacked instructions, variable references, and constraints. It is agent-authored — the user almost never writes a prompt from scratch, and rarely reads one end-to-end. So when output drifts, the natural human moves are unproductive: rewriting from scratch loses prior wins; pasting more details makes the prompt longer, more entangled, and more brittle. Prompts rot.

The antidote is **assertions** — a small, human-readable, user-curated list of verifiable objectives that the prompt's result must satisfy. Where prompts are long, opaque, and agent-authored, assertions are short, scannable, and human-authored. They are the durable specification of "what 'good output' means" for a given scenario.

The paradigm has three consequences the agent must internalize:

1. **You don't tune a prompt in isolation. You tune a prompt *to satisfy* a set of assertions.** New workflows start from a confirmed state spec and `result_format`; semantic prompt improvements start from failing or missing assertions.
2. **When the result is wrong, the first move is reading the report — not editing the prompt.** The report names the failing criterion. The criterion points at the cause. Editing without reading presumes a cause.
3. **"Looks fine to me" is not a valid state.** Either the result passes the assertions, or it doesn't. If you find yourself eyeballing output to judge quality, you are missing a criterion — write it.

Under this paradigm, evals do not come last. During workflow creation, structural smoke evals are scaffolded immediately from each state's `result_format`. During semantic iteration, the assertion is written before the prompt change that is supposed to satisfy it. The prompt-creator still reads only the state spec and `result_format`; it does not read `assertions.md` or reports.

## 1.5. The Three-Agent Principle

The methodology is split across three agents that **must not share procedures or read each other's artifacts**:

| Agent | Reads | Writes | Cannot read |
|---|---|---|---|
| **Prompt-creator** | State spec (job, `result_format`, inputs, constraints, verification) from `.orca/{flow}.yml` | `.orca/prompts/{state}.md` | `assertions.md`, eval reports, evaluator's prompt |
| **Worker** (prompt executor) | The rendered prompt at runtime | `result.json` per the schema | `assertions.md`, the evaluator's prompt, how it's graded |
| **Evaluator** (assertion grader) | `assertions.md`, worker's `result.json`, worktree side-effects | `report.md`, structured outcome | The prompt-creator's playbook, the worker's prompt |

This is a deliberate Chinese-wall pattern. The rationale:

- **A prompt-creator that can read assertions will optimize the prompt to pass them** instead of solving the underlying task — adding "remember to output X to satisfy criterion Y" rather than reasoning about why X matters. Prompts become assertion-shaped rather than task-shaped, and the assertions stop being an independent check.
- **A worker that sees how it will be graded games the grading** — emitting just enough to satisfy each criterion literally, not what the task actually demanded. The prompt's instructions become irrelevant; the worker reverse-engineers the rubric.
- **An evaluator that has seen the prompt may infer the worker's intent and rubber-stamp it** — judging "did the worker try to do what the prompt asked" instead of "did the result satisfy the criterion as written". Soft-grading creeps in.

Each agent must be a pure function of its own inputs. When something goes wrong, attribution is done by a coordinator (a human or an upstream skill); the relevant agent then receives an updated spec or criterion and produces a fresh artifact, without ever seeing the others' work.

For the prompt-creator specifically: [`orca-prompt-create.md`](../orca-prompt-create.md) is deliberately written without any reference to `assertions.md`, eval execution, or the failure-attribution taxonomy. Don't link those concepts into a prompt the agent will read.

## 2. Anatomy of a good assertion

Each eval directory has `assertions.md` — the user-curated checklist. Its shape is rigid by design.

### Structure

- One `### <id>` heading per criterion. Id is kebab-case and stable across edits — it appears verbatim in `report.md` and in result JSON; renaming an id silently breaks history.
- Prose under the heading IS the criterion. The evaluator reads it literally — it is not a description of the criterion, it *is* the criterion.
- Aim for 3–7 criteria in a first semantic eval. Fewer is fine when the slice is intentionally narrow. More usually means the eval is doing too much; split it.

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

**Below the line — avoid:** subjective judgment ("title sounds good", "plan is comprehensive", "change makes sense"). Both the worker and the `assert` evaluator are LLM-driven; the double non-determinism amplifies flake. A criterion that flips run-to-run is worse than no criterion — it teaches you to ignore the report.

### Good / bad rewrites

| Bad (judgment-heavy) | Good (objective) |
|---|---|
| "The code is clean" | "`ruff check .` exits 0" |
| "Evals are thorough" | "Every public function in `src/` has at least one eval in `evals/` whose name contains the function name" |
| "The fix is correct" | "`pytest evals/test_auth.py::test_login_with_expired_token` exits 0" |
| "The review caught the bug" | "Some finding has `file == 'src/api.py'` and `line` within 5 of the deliberately-injected SQL injection on line 42" |
| "Names are good" | "Every new identifier matches `^[a-z_][a-z0-9_]*$` (snake_case)" |

Side-effects (commits, edited files) are gradable too — but coarser than `result_format` fields. Prefer field-shape evidence over diff-shape evidence. If a guarantee can move from "the worker committed correctly" into "the `result_format` has field X", move it.

## 3. The link to `result_format`

The link between assertions and prompts is `result_format`. Every criterion needs evidence; every piece of evidence comes from a field in `result_format` or from a worktree side-effect. That creates two valid flows:

- **Workflow creation:** design the state machine and `result_format` first, write prompts from that contract, then scaffold structural assertions from the schema.
- **Semantic eval creation / drift repair:** draft or update `assertions.md`, check whether the needed evidence already exists in `result_format` or the worktree, and only then make the smallest coordinated change.

If a new criterion needs a field the state does not emit, update `result_format` and the prompt together as a workflow change. Do not silently teach the evaluator to infer data that the worker never reports.

### Check evidence while drafting assertions

While drafting each criterion, ask: *what field or file does this read?* If the answer is "I don't know yet", either rewrite the criterion to use available evidence or propose the `result_format` addition that would make it gradeable. By the time assertions are complete, the evidence path is explicit.

Cross-reference: [`orca-eval-create.md`](../orca-eval-create.md) is the playbook for drafting `assertions.md` around a real scenario. If that process discovers a missing result field, route the coordinated schema/prompt edit through [`orca-workflow-create.md`](../orca-workflow-create.md) or [`orca-workflow-review.md`](../orca-workflow-review.md), depending on whether the workflow is new or existing.

### Structural vs semantic assertions — two phases

Workflow creation produces a *structural* `assertions.md` per active state automatically — derived mechanically from `result_format` (enum coverage, `required_when` presence). These exist as smoke-eval scaffolds the moment a workflow is born; see [`orca-workflow-create.md`](../orca-workflow-create.md) Step 8.

The *semantic* assertions — the ones that grade whether the worker actually solved the task, not just whether it returned a valid shape — are appended later via [`orca-eval-create.md`](../orca-eval-create.md). They are the work this whole document describes. The two phases are deliberately separated: structural assertions need no domain reasoning and ship with the workflow; semantic assertions need a real scenario and are written when the user is ready to invest in regression coverage.

## 4. Lifting constraints into assertions

A constraint stated only in the prompt is hope; a constraint reflected in the `result_format` (or in a worktree-readable side-effect) is verifiable. The prompt should still state the constraint in prose — but it must also be checked.

Example: "ONLY modify files under `issue.fields.scope_boundary`". The prompt should still say this. But you also want an assertion:

```markdown
### scope-boundary-respected
Every path in `git diff --name-only` (for the slice's commits) ends in `.py`
and lives under `issue.fields.scope_boundary` (e.g. `src/auth/`).
No files outside this prefix were modified.
```

Now the constraint is double-bound: stated in the prompt, checked by the eval.

## 5. The iteration loop & failure attribution

The canonical loop:

```
[ Bootstrap ]
  2-3 questions  →  draft assertions.md  →  verify evidence/result_format  →  run

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

Then draft a minimal `assertions.md` (2–3 criteria from the answers) and verify the existing `result_format` exposes the evidence those criteria need. If it does not, stop and make the coordinated schema/prompt edit before running the eval.

**Cost note.** Every eval run is N+1 LLM invocations (N body states, 1 assert). The worktree is set up by `git checkout` from the state branch, not by an LLM — there is no per-run setup cost. A single-state slice is the cheapest starting point; default to it. See [`orca-eval-create.md`](../orca-eval-create.md).

### Failure attribution

When the report shows a failed criterion, walk this taxonomy **before** editing anything:

| Failure mode | Symptom | Fix |
|---|---|---|
| **Prompt** | Worker had access to a clear instruction in the prompt and didn't follow it. | Sharpen or add the relevant instruction. Minimal edit. See [`orca-prompt-create.md`](../orca-prompt-create.md). |
| **Assertion** | Criterion is ambiguous, judgment-heavy, or references a key not in `result_format`. | Rewrite the criterion. |
| **Scenario** | Eval input (`input.md` and the state-branch worktree) doesn't actually exercise the path the criterion grades. | Edit `input.md`, or amend the commit on `orca-eval-state/<name>`. |
| **`result_format`** | The field the criterion needs isn't emitted. | Add the field to `result_format` AND update the prompt to emit it. |
| **Model** | Output is correct in shape but consistently misses semantic detail across retries. | Swap model in YAML, or split the state into smaller responsibilities. |
| **Flow** | Slice's entry state expected a field that nothing upstream seeded. | Add the field to `input.md` frontmatter (so it's seeded into `issue.fields.*`), or fix the upstream production state that should have produced it. |

The first three are the common ones. The fourth is the most-missed — it's the one that quietly causes "every criterion fails" reports.

### Drift = new assertion first

When the user reports a new kind of bad output not currently graded by any criterion, the agent's first move is **not** editing the prompt. It is:

1. Write a criterion in `assertions.md` that catches the new bad output.
2. Re-run the eval — the new criterion should fail. If it passes, the user's complaint is already covered; ask them to point at a failing case.
3. Now attribute the failure and apply the minimal edit.

Never add prompt prose without a failing criterion that justifies it. "Just in case" content is how prompts grow from 100 to 500 lines.

## 6. Worked example

End-to-end walkthrough for a `review` state that audits a Python pull request — a typical Orca use case.

**Cold start.** User says: "I want a `review` state that catches common bugs in Python PRs."

**Bootstrap — 3 questions:**

- *What is a one-sentence success?* → "On a PR that contains a SQL injection, it should request changes and point at the offending file:line; on a clean PR, it should approve."
- *What is an obvious failure mode?* → "It approves a PR with an obvious bug, or it requests changes without saying where the bug is."
- *What shape should the result have?* → "outcome (approve / request_changes), plus a list of findings with file, line, severity, and message."

**Draft semantic `assertions.md` first (3 criteria).** The scenario in `input.md` will be a PR that introduces a SQL injection at `src/api.py:42`.

```markdown
### outcome-is-request-changes
The review state's `outcome` is `request_changes` (the PR contains a deliberate SQL injection).

### finding-points-at-the-bug
Some `findings[i]` has `file == "src/api.py"` and `line` within 5 of 42.

### findings-have-required-fields
Every finding has a non-empty `file`, a positive integer `line`, a `severity` in `{critical, major, minor}`, and a non-empty `message`.
```

**Ensure `result_format` exposes the evidence:**

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

If the production state does not already emit that shape, add the missing fields to the workflow YAML and update the prompt through [`orca-prompt-create.md`](../orca-prompt-create.md) before running the eval. The prompt-creator receives the state spec and result contract, not this `assertions.md`.

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

The whole story: assertions first for semantic drift, attribution second, minimal edit third. Drift creates new criteria, not new prompt prose. The prompt grew by *two sentences* across two improvements — not two paragraphs.

## 7. Anti-patterns

- **Tuning a prompt before the semantic assertion exists.** The edit has nothing objective to converge on. Write the criterion first.
- **Adding prompt prose to fix drift without a failing assertion.** Drift = new criterion first, then minimal edit.
- **Criteria that grade process, not output** ("the worker should follow the plan"). The evaluator only sees results, not the worker's thinking.
- **Judgment-heavy criteria** ("title sounds professional"). Replace with regex / closed-vocab, or drop. The bar: could two evaluator runs disagree on this? If yes, rewrite.
- **More than 7 criteria in one eval.** Split into multiple evals with different scenarios.
- **Catch-all `result_format` blobs** (`summary: "a markdown writeup"`). Field-shape evidence beats prose-shape evidence every time.
- **Renaming criterion ids on a whim.** Ids are stable identifiers — they appear in `report.md` and the result JSON. Renames silently break history.

## Cross-references

- [`orca-prompt-create.md`](../orca-prompt-create.md) — mechanics of writing a single state prompt (template variables, structure, pitfalls).
- [`orca-eval-create.md`](../orca-eval-create.md) — interactive procedure for authoring an eval. The bootstrap step in Section 5 above maps to that playbook's Steps 1–8.
- [`orca-eval-review.md`](../orca-eval-review.md) — audit checklist for an existing eval. Use it to verify your assertions are well-formed.
- [`orca-config-reference.md`](orca-config-reference.md) — full schema reference, including `result_format` field types.
- [`orca-workflow-patterns.md`](orca-workflow-patterns.md) — reusable building blocks for workflows.
