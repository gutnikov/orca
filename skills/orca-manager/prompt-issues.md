# Prompt Issues Catalog

Common orca worker prompt problems and fixes. Match patterns from worker logs against entries below. Each fix modifies a Jinja2 prompt template in the target project's `prompts/` directory.

## Result Format Issues

### Worker produces invalid result JSON

**Pattern:** Worker log shows repeated "result validation failed" messages, or worker writes `result.json` but fields don't match the expected schema. Worker may attempt corrections but keep failing.
**Root cause:** The result format instructions are buried in the prompt, unclear, or missing an example.
**Fix:** In the prompt template, move result format instructions to the **end** of the prompt (just before the `{{ result_path }}` reference). Add an explicit JSON example:
```
## Result

Write your result to `{{ result_path }}` with this exact JSON structure:

{{ result_format | tojson(indent=2) }}

Writing the result file is the FINAL action of your session. Complete ALL other work first.
```
**Applies to:** Any prompt template
**Risk:** low

### Worker writes result with wrong field names

**Pattern:** Worker writes result.json but uses camelCase instead of snake_case (or vice versa), or uses synonyms ("description" instead of "summary").
**Root cause:** The prompt describes the fields in natural language but the worker guesses the JSON key names.
**Fix:** Add the literal JSON keys next to each field description in the prompt. Show the exact `result_format` schema, not a paraphrase.
**Applies to:** Any prompt template
**Risk:** low

## Worker Behavior Issues

### Worker loops doing the same thing

**Pattern:** Worker log shows 3+ iterations of the same approach (e.g., running the same failing command, editing the same file in the same way). No progress between iterations.
**Root cause:** Prompt doesn't instruct the worker to try alternative approaches on failure.
**Fix:** Add to the prompt:
```
If an approach fails twice, stop and try a fundamentally different strategy.
Do not repeat the same fix more than twice.
```
**Applies to:** Implementation and debugging prompts
**Risk:** low

### Worker ignores constraints

**Pattern:** Worker modifies files outside its scope, changes files it was told not to touch, or uses approaches explicitly forbidden in the prompt.
**Root cause:** Constraints are stated once early in the prompt and forgotten by the time the worker is deep in its task. Or constraints are phrased as suggestions rather than hard rules.
**Fix:** Move constraints to a dedicated `## Constraints` section near the end of the prompt (before result format). Use imperative language:
```
## Constraints

- ONLY modify files under `src/feature/` — do NOT touch other directories
- Do NOT modify `package.json` or any config files
- All changes must include tests
```
**Applies to:** Any prompt template
**Risk:** low

### Worker modifies wrong files

**Pattern:** Worker makes changes to files unrelated to its issue, often in shared areas (config files, root-level scripts, CI configs).
**Root cause:** Prompt doesn't specify the scope of allowed file modifications. Worker infers broadly.
**Fix:** Add an explicit file scope to the prompt:
```
## Scope

You may only create or modify files under these paths:
- `src/{{ issue.fields.module }}/`
- `tests/{{ issue.fields.module }}/`

Do not modify files outside this scope.
```
**Applies to:** Implementation prompts, especially when multiple workers run in parallel
**Risk:** low

### Worker doesn't commit its changes

**Pattern:** Worker completes implementation but the worktree has uncommitted changes. The result.json says "done" but `git status` in the worktree shows modifications.
**Root cause:** Prompt doesn't explicitly instruct the worker to commit, or the commit instruction is buried.
**Fix:** Add explicit commit instruction before the result section:
```
## Before Writing Result

1. Run all relevant tests to verify your changes work
2. Stage and commit all changes with a descriptive commit message
3. Then write the result file
```
**Applies to:** Implementation and apply prompts
**Risk:** low

## Output Issues

### Worker produces empty or trivial output

**Pattern:** Worker writes result.json almost immediately with minimal content. Fields contain single sentences or placeholder text. Worker log shows very little activity.
**Root cause:** Prompt doesn't set quality expectations or the task description is too vague for the worker to act on.
**Fix:** Add quality expectations:
```
## Quality Expectations

Your output must be thorough and actionable:
- Each section should contain specific, detailed content (not placeholders)
- Reference actual file paths, function names, and code patterns from the codebase
- If you're unsure about something, investigate the codebase before writing
```
Also check that `{{ issue.fields }}` provides enough context for the worker to act on.
**Applies to:** Planning and scoping prompts
**Risk:** low

### Worker stuck on failing tests

**Pattern:** Worker spends most of its session running tests, seeing failures, making small tweaks, running tests again. Cycles 5+ times without resolution. Eventually times out.
**Root cause:** Prompt tells worker to "make all tests pass" without scoping which tests. Worker tries to fix pre-existing test failures unrelated to its task.
**Fix:** Scope the test requirement:
```
## Testing

Run only tests related to your changes:
- `pytest tests/{{ issue.fields.module }}/ -v`
- If tests fail that are NOT related to your changes, note them in your result but do not try to fix them
- You are only responsible for tests that cover code you modified
```
**Applies to:** Implementation prompts
**Risk:** low

### Worker misunderstands decomposition

**Pattern:** In scoping/decomposition prompts, worker creates sub-issues that overlap, are too granular (1-line changes), or too broad (entire features). Or worker puts implementation details in sub-issue descriptions instead of scope boundaries.
**Root cause:** Prompt doesn't define what a good decomposition looks like.
**Fix:** Add decomposition guidance:
```
## Decomposition Guidelines

Each sub-issue should:
- Be independently implementable (no circular dependencies between sub-issues)
- Take a worker roughly 10-30 minutes to complete
- Have a clear scope boundary (which files/modules it touches)
- Not overlap with other sub-issues

Put SCOPE (what to change) in the description, not HOW to change it. The implementing worker will decide the approach.
```
**Applies to:** Scoping and planning prompts
**Risk:** low

## Deep Analysis

### Problem beyond catalog fixes

**Pattern:** Issue persists after applying catalog fixes from this document, or the problem is novel and doesn't match any entry above.
**Root cause:** Structural workflow config or prompt issue requiring deeper analysis than pattern matching.
**Fix:** Invoke the orca-workflow-builder skill in audit mode on the affected flow/state. Read `skills/orca-workflow-builder/SKILL.md` and pass the worker logs and your diagnosis as context. The builder will run its three-layer audit checklist and apply targeted fixes.
**Applies to:** Any workflow when catalog fixes are insufficient
**Risk:** low (audit), medium (fixes)
