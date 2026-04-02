# Orca Manager Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a Claude Code skill that turns the agent into an autonomous orca workflow manager — parsing natural language missions, driving orca via MCP tools, monitoring progress, diagnosing failures, and remediating problems within a configurable autonomy framework.

**Architecture:** Core skill file (SKILL.md) defines the decision framework (loop, autonomy tiers, diagnosis, flow chaining). Three reference docs (remediation-catalog, prompt-issues, flow-patterns) are loaded on-demand when the agent needs to diagnose or fix problems. All files are markdown — no Python code changes.

**Tech Stack:** Claude Code skills (markdown with YAML frontmatter), orca MCP tools

**Spec:** `docs/superpowers/specs/2026-04-02-orca-manager-skill-design.md`

---

### Task 1: Create core skill file

**Files:**
- Create: `skills/orca-manager/SKILL.md`

- [ ] **Step 1: Create directory**

```bash
mkdir -p skills/orca-manager
```

- [ ] **Step 2: Write the core skill file**

Write `skills/orca-manager/SKILL.md` with this exact content:

````markdown
---
name: managing-orca-workflows
description: Use when managing orca workflow runs — starting flows, monitoring progress, diagnosing failures, remediating problems, and chaining flows. Triggers on "run X flow", "manage orca", "start prd then qa-spec", "check orca status", or any orca workflow orchestration task.
---

# Managing Orca Workflows

Autonomous orca workflow management. You parse a natural language mission, drive orca via MCP tools, monitor progress, diagnose failures, remediate problems, and chain flows.

You are running from the **orca repo**. You reach target projects via file paths. You control orca exclusively through MCP tools (`orca_*`).

## Mission Parsing

Extract from the user's instruction:

1. **Flows** — what workflows to run and in what order
2. **Target project path** — where the target repo lives (ask if unclear)
3. **Success criteria** — what "done" looks like
4. **Autonomy level** — `full`, `supervised`, or `cautious` (default: `supervised`)

Confirm your understanding before starting. Example:

> "I'll run the prd flow for /path/to/ai-team on the feature-x branch, then chain to qa-spec when it succeeds. Autonomy: supervised. Sound right?"

## The Loop

```
ENSURE PREREQUISITES
  ├── orca_daemon_status() — if fails, run: orca daemon start
  ├── Target project path exists and is a git repo
  ├── Task file exists
  └── Flow-specific deps (docker info, etc.)
       │
       ▼
START FLOW ◄──────────────────────────────┐
  orca_start_run(task_file, workflow, branch)
       │                                   │
       ▼                                   │
MONITOR (poll orca_get_run every 30-60s)   │
  Track: issue states, active workers,     │
         terminal_count vs issue_count     │
       │                                   │
       ▼                                   │
ASSESS                                     │
  PROGRESSING → continue polling           │
  STALLED → diagnose (no change 3+ polls)  │
  FAILED → diagnose (failure_count high)   │
  COMPLETED → chain next flow ─────────────┘
              or report done
```

**Polling cadence:** 30s base, 60s when stable, 15s when issues detected.

**Proactive failure detection:** If any issue's `failure_count > max_worker_retries / 2`, investigate immediately — don't wait for orca to exhaust retries.

## Autonomy Tiers

Tiers control creative problem-solving, not safety. Even at `full`, confirm destructive/shared-state actions.

### `cautious`

Autonomous: start listed flows, poll, diagnose, retry issues (`orca_retry_issue`).

Confirm first: env changes, stop/drop runs, unlisted flow chains, any code changes, waits > 5min.

### `supervised` (default)

Adds autonomous: known env fixes (from catalog), stop/restart stalled runs, chain next listed flow, known prompt fixes, waits up to 15min.

Confirm first: orca source changes, novel remediations, dropping runs, novel prompt changes, target project code changes.

### `full`

Adds autonomous: orca source fixes (self-healing), novel remediations, drop+recreate failed runs, novel prompt edits.

Confirm first: pushing to remote, affecting other users' branches, destructive operations (deleting worktrees, dropping data).

## Diagnosis

When STALLED or FAILED, follow this sequence. **Never remediate without diagnosis.**

### 1. Gather

```
orca_get_run(run_id)              → status, issue overview
orca_get_issue(run_id, issue_id)  → per non-terminal issue
orca_get_worker_log(run_id, id)   → for failed/stalled issues
orca_get_insights(run_id)         → orchestrator-level view
```

### 2. Classify

| Root Cause | Signals |
|---|---|
| ENVIRONMENT | "command not found", "docker: not running", "EACCES", "connection refused" on localhost |
| TRANSIENT | "rate limit", "503", "timeout", "ECONNRESET", intermittent |
| ORCA_BUG | Python traceback, state inconsistency, resume fails |
| PROMPT_ISSUE | Invalid result repeatedly, worker loops, result doesn't match format |
| TASK_ISSUE | Worker says "impossible"/"unclear", persists after other fixes |

### 3. Remediate

**Read the appropriate reference doc** before applying fixes:
- ENVIRONMENT → read `skills/orca-manager/remediation-catalog.md`
- PROMPT_ISSUE → read `skills/orca-manager/prompt-issues.md`
- TRANSIENT → stop run, wait (within tier limit), resume
- ORCA_BUG → at `full`: read traceback, search orca source, fix, lint (`uv run ruff check . && uv run mypy src/`), commit, restart daemon, resume. Otherwise: escalate with diagnosis.
- TASK_ISSUE → always escalate to user

### Rules

- **One fix at a time.** Apply, retry, observe. Don't stack fixes.
- **Escalation budget.** After 2 failed remediations for the same issue, escalate regardless of autonomy.
- **Report before acting.** State your diagnosis and intended action before executing.
- **Self-healing safety.** Lint+typecheck must pass before restarting daemon. If fix doesn't resolve on retry, revert commit and escalate.

## Flow Chaining

When mission has multiple flows (e.g. "prd then qa-spec then implement"):

- **SUCCESS** → verify prior flow's output exists (e.g. PRD doc), start next flow on same branch
- **PARTIAL** (some issues done) → assess if failed issues block next flow. Independent? Proceed. Critical? Fix first.
- **FAILED** → diagnose and remediate current flow, don't start next

**Judgment calls:**
- For dependent flows (e.g. prd → implement), verify the output looks reasonable before chaining
- If output is unexpected, pause and report rather than blindly chaining
- All flows chain on the **same branch** unless user specifies otherwise

Read `skills/orca-manager/flow-patterns.md` for common mission patterns.

## Session Exit

When you need to stop (context limits, user interrupt, long wait):

1. **Report state** — which flows completed, in-progress, pending. Any diagnosed problems.
2. **Leave runs resumable** — don't drop. Stop actively-failing runs.
3. **Resume instructions** — exact run IDs, next flow, pending remediations.
4. **Re-invocation string** — give the user the exact mission to paste when re-invoking.

## MCP Tools Quick Reference

| Tool | Use |
|---|---|
| `orca_daemon_status` | Prereq check, health monitoring |
| `orca_start_run(task_file, workflow?, branch?)` | Start a flow |
| `orca_list_runs` | Overview of all runs |
| `orca_get_run(run_id)` | Detailed run state + sessions |
| `orca_get_issue(run_id, issue_id)` | Issue details, failure_count, event_log |
| `orca_get_worker_log(run_id, issue_id, tail?)` | Worker output (default last 100 lines) |
| `orca_get_insights(run_id)` | Orchestrator insights log |
| `orca_retry_issue(run_id, issue_id)` | Re-dispatch a failed issue |
| `orca_stop_run(run_id)` | Stop a running flow |
| `orca_resume_run(run_id)` | Resume a stopped flow |
| `orca_drop_run(run_id)` | Delete run state entirely |
````

- [ ] **Step 3: Commit**

```bash
git add skills/orca-manager/SKILL.md
git commit -m "feat(skills): add orca-manager core skill"
```

---

### Task 2: Create remediation catalog

**Files:**
- Create: `skills/orca-manager/remediation-catalog.md`

This task is independent of Tasks 3 and 4 — they can run in parallel.

- [ ] **Step 1: Write the remediation catalog**

Write `skills/orca-manager/remediation-catalog.md` with this exact content:

````markdown
# Remediation Catalog

Known environment and infrastructure issues with tested fixes. Match error patterns from worker logs against entries below.

## Docker

### Docker daemon not running

**Pattern:** `Cannot connect to the Docker daemon` or `Is the docker daemon running?`
**Platform:** both
**Fix:**
- macOS: `open -a Docker && sleep 15 && docker info`
- Linux: `sudo systemctl start docker && sleep 5 && docker info`
**Verify:** `docker info` exits 0
**Risk:** low

### Docker image pull failure

**Pattern:** `Error response from daemon: pull access denied` or `manifest unknown`
**Platform:** both
**Fix:**
- Check image name/tag spelling in the project's docker-compose or Dockerfile
- If auth required: report to user — do not attempt `docker login` autonomously
**Verify:** `docker pull <image>` succeeds
**Risk:** low (read-only diagnosis), medium (if fixing image references)

## Node / npm

### Node.js not installed

**Pattern:** `node: command not found` or `npm: command not found`
**Platform:** both
**Fix:**
- macOS: `brew install node`
- Linux: `curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash - && sudo apt-get install -y nodejs`
- Or if `.nvmrc` exists: `nvm install && nvm use`
**Verify:** `node --version && npm --version`
**Risk:** low

### npm install failure

**Pattern:** `npm ERR! code ERESOLVE` or `npm ERR! peer dep`
**Platform:** both
**Fix:**
- Try `npm install --legacy-peer-deps`
- If lockfile conflict: `rm -rf node_modules package-lock.json && npm install`
**Verify:** `npm install` exits 0
**Risk:** medium (lockfile deletion)

## Git

### Worktree conflict

**Pattern:** `fatal: '...' is already checked out` or `fatal: working tree '...' already exists`
**Platform:** both
**Fix:**
- List worktrees: `git worktree list`
- If stale: `git worktree prune`
- If active but blocking: report to user — don't remove active worktrees
**Verify:** `git worktree list` shows no conflicts for the target path
**Risk:** low (prune), high (remove — never do autonomously)

### Detached HEAD in worktree

**Pattern:** `HEAD detached at` in worktree used by orca
**Platform:** both
**Fix:**
- Check which branch the run expects: `git branch --show-current` in the worktree
- If detached: `git checkout <expected-branch>` in the worktree
**Verify:** `git branch --show-current` returns expected branch
**Risk:** low

## Ports

### Port already in use

**Pattern:** `EADDRINUSE` or `address already in use` or `bind: address already in use`
**Platform:** both
**Fix:**
- Identify what's using the port: `lsof -i :<port>` (macOS/Linux)
- Report process name and PID to user — never kill unknown processes
- If the process is a known dev server from a previous run: suggest user kills it
**Verify:** `lsof -i :<port>` returns empty
**Risk:** low (diagnosis only)

## Disk

### Disk space exhausted

**Pattern:** `No space left on device` or `ENOSPC`
**Platform:** both
**Fix:**
- Check space: `df -h .`
- Report to user with breakdown — do not delete files autonomously
- Suggest: docker image prune, npm cache clean, git gc
**Verify:** `df -h .` shows reasonable free space
**Risk:** low (diagnosis only)

## Permissions

### File permission denied

**Pattern:** `EACCES` or `Permission denied` (on local file operations)
**Platform:** both
**Fix:**
- Identify the file: path is usually in the error message
- If it's a script that needs execute: `chmod +x <path>`
- If it's a directory access issue: report to user
**Verify:** `ls -la <path>` shows correct permissions
**Risk:** low (chmod +x on scripts), medium (broader permission changes)

## Python / venv

### Python venv missing or broken

**Pattern:** `ModuleNotFoundError` for project deps, or `No module named` in orca context
**Platform:** both
**Fix:**
- In orca repo: `uv sync`
- In target project: check for `requirements.txt`, `pyproject.toml`, or `Pipfile` and run appropriate install
**Verify:** `uv run python -c "import <module>"` succeeds
**Risk:** low

## Environment Variables

### Missing environment variable

**Pattern:** `KeyError: '<VAR_NAME>'` or `Environment variable <VAR> not set` or `<VAR> is required`
**Platform:** both
**Fix:**
- Check if `.env` or `.env.example` exists in the target project
- If `.env.example` exists but `.env` doesn't: `cp .env.example .env` and report to user to fill in values
- If the var is an API key or secret: always report to user — never fabricate credentials
**Verify:** `echo $<VAR_NAME>` returns non-empty
**Risk:** low (diagnosis), medium (copying .env template)

## DNS / Network

### DNS resolution failure

**Pattern:** `ENOTFOUND` or `getaddrinfo` or `Name or service not known`
**Platform:** both
**Fix:**
- Check basic connectivity: `ping -c 1 8.8.8.8`
- If ping works but DNS fails: likely a DNS config issue — report to user
- If ping fails: network is down — classify as TRANSIENT, wait and retry
**Verify:** `nslookup <hostname>` resolves
**Risk:** low (diagnosis only)
````

- [ ] **Step 2: Commit**

```bash
git add skills/orca-manager/remediation-catalog.md
git commit -m "feat(skills): add orca-manager remediation catalog"
```

---

### Task 3: Create prompt issues catalog

**Files:**
- Create: `skills/orca-manager/prompt-issues.md`

This task is independent of Tasks 2 and 4 — they can run in parallel.

- [ ] **Step 1: Write the prompt issues catalog**

Write `skills/orca-manager/prompt-issues.md` with this exact content:

````markdown
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
````

- [ ] **Step 2: Commit**

```bash
git add skills/orca-manager/prompt-issues.md
git commit -m "feat(skills): add orca-manager prompt issues catalog"
```

---

### Task 4: Create flow patterns guide

**Files:**
- Create: `skills/orca-manager/flow-patterns.md`

This task is independent of Tasks 2 and 3 — they can run in parallel.

- [ ] **Step 1: Write the flow patterns guide**

Write `skills/orca-manager/flow-patterns.md` with this exact content:

````markdown
# Flow Patterns

Common orca mission patterns. Use these as guidance — adapt based on the actual mission.

### PRD → QA Spec → Implement

**When:** Building a new feature end-to-end from a task description.
**Chain:** `prd(task.md) → qa-spec(same branch) → implement(same branch)`
**Notes:**
- After prd completes, verify the PRD document was committed to the target repo
- Before starting qa-spec, read the PRD output to confirm it's substantive (not a stub)
- qa-spec prompts should reference that implementation hasn't happened yet — specs describe expected behavior, not existing code
- implement may decompose into many parallel sub-issues — monitor closely for workers stepping on each other
**Common failures:**
- PRD is too vague → implement workers struggle with scope. Fix: tighten prd prompts with more specific output requirements
- qa-spec references files that don't exist yet → workers fail trying to read non-existent code. Fix: qa-spec prompt should note "describe expected behavior, code doesn't exist yet"
- implement sub-issues have conflicting file edits → merge conflicts in applying state. Fix: ensure scoping prompt defines clear module boundaries

### Single Flow Monitoring

**When:** User asks to run one flow and watch it.
**Chain:** `<workflow>(task.md)` — single flow, no chaining
**Notes:**
- Simplest pattern — just run, monitor, diagnose if needed
- Report completion status and summary of what was produced
- If the flow has a decompose state, track sub-issue creation and progress
**Common failures:**
- Worker timeout → check if `timeout` in orca.yml is too low for the task complexity
- All issues fail immediately → likely an environment or prompt issue, not task-specific

### Bug Investigation Flow

**When:** Investigating and fixing a specific bug or set of bugs.
**Chain:** `investigate(task.md) → implement(same branch)` or just `develop(task.md)`
**Notes:**
- Investigation flows typically produce a diagnosis, not code changes
- Before chaining to implement, read the investigation output to verify it found a root cause
- If investigation concludes "not a bug" or "can't reproduce", report to user rather than chaining
**Common failures:**
- Investigator can't reproduce the bug → check if the environment setup is complete (DB, services, fixtures)
- Investigator finds the bug but proposed fix is in a different repo → escalate to user

### Parallel Feature Flows

**When:** Multiple independent features need to be built simultaneously.
**Chain:** Multiple concurrent `implement(task-N.md, branch=feature-N)` runs — one per feature, each on its own branch
**Notes:**
- Each flow runs on a **separate branch** to avoid conflicts
- Monitor all runs simultaneously — `orca_list_runs()` gives overview
- If one flow fails, others can continue independently
- Don't try to merge branches — that's the user's responsibility
**Common failures:**
- Shared dependency conflict → two flows modify the same package.json/requirements.txt. Typically surfaces in CI, not during orca run
- Resource exhaustion → many concurrent workers may overwhelm CPU/memory. Watch for slow workers and consider stopping some flows

### Iterative Refinement

**When:** A flow needs to be re-run with adjustments after reviewing output.
**Chain:** `<workflow>(task.md) → review output → drop → <workflow>(revised-task.md)` — same workflow, different input
**Notes:**
- After the first run, the user reviews output and provides feedback
- Drop the old run (state is stale), create a revised task file incorporating feedback
- Re-run on the same branch — prior commits are preserved, new run builds on them
- This is a user-driven loop, not autonomous — the manager runs one iteration at a time
**Common failures:**
- Forgetting to drop the old run → `orca_start_run` fails with "run already exists" for that branch:workflow pair
- New run repeats the same mistakes → the revised task file needs to be more specific about what to change
````

- [ ] **Step 2: Commit**

```bash
git add skills/orca-manager/flow-patterns.md
git commit -m "feat(skills): add orca-manager flow patterns guide"
```

---

### Task 5: Register skill in project CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add skill reference to CLAUDE.md**

Add the following section to the end of `CLAUDE.md`:

```markdown

## Skills

- `skills/orca-manager/` — Autonomous orca workflow management skill. Invoke by asking the agent to manage orca workflows or by reading `skills/orca-manager/SKILL.md`.
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: register orca-manager skill in CLAUDE.md"
```

---

### Task 6: Verify skill structure

**Files:**
- Read: `skills/orca-manager/SKILL.md`
- Read: `skills/orca-manager/remediation-catalog.md`
- Read: `skills/orca-manager/prompt-issues.md`
- Read: `skills/orca-manager/flow-patterns.md`

- [ ] **Step 1: Verify directory structure**

```bash
find skills/ -type f | sort
```

Expected output:
```
skills/orca-manager/SKILL.md
skills/orca-manager/flow-patterns.md
skills/orca-manager/prompt-issues.md
skills/orca-manager/remediation-catalog.md
```

- [ ] **Step 2: Verify SKILL.md frontmatter**

```bash
head -4 skills/orca-manager/SKILL.md
```

Expected output:
```
---
name: managing-orca-workflows
description: Use when managing orca workflow runs — starting flows, monitoring progress, diagnosing failures, remediating problems, and chaining flows. Triggers on "run X flow", "manage orca", "start prd then qa-spec", "check orca status", or any orca workflow orchestration task.
---
```

- [ ] **Step 3: Verify all reference docs are readable**

Read each file and confirm:
- `remediation-catalog.md` has 12 entries: docker daemon, docker pull, node, npm, worktree, detached HEAD, port, disk, permissions, python venv, env vars, DNS
- `prompt-issues.md` has 9 entries: invalid result JSON, wrong field names, worker looping, ignoring constraints, wrong files, not committing, empty output, stuck on tests, misunderstands decomposition
- `flow-patterns.md` has 5 entries: PRD→QA→Implement, single flow, bug investigation, parallel features, iterative refinement

- [ ] **Step 4: Verify CLAUDE.md references the skill**

```bash
grep -A1 "Skills" CLAUDE.md
```

Expected: shows the skills section with orca-manager reference.
