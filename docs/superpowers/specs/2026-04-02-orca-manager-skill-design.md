# Orca Manager Skill — Design Spec

## Overview

A Claude Code skill that turns the agent into an autonomous orca workflow manager. The agent interprets natural language missions (e.g. "run prd flow for ai-team, then qa-spec when it's done"), executes them by driving orca's MCP tools, monitors progress, diagnoses failures, and takes corrective action — all within a configurable autonomy framework.

The skill defines a **decision framework**, not a rigid script. The agent decides how long to run and how aggressively to remediate based on the mission scope and autonomy level.

## Architecture

### Skill File Layout

```
skills/
  orca-manager.md              # Core skill — decision framework
  orca-manager/
    remediation-catalog.md     # Known env/infra issues + fixes
    prompt-issues.md           # Common prompt problems + patches
    flow-patterns.md           # Flow chaining patterns + examples
```

The core skill is loaded on invocation. Reference docs are read on-demand when the agent needs to diagnose or remediate problems.

### Runtime Context

- The agent runs from the **orca repo**, reaching target projects via file paths when needed (e.g. to fix prompts).
- The agent controls orca through **MCP tools** (`orca_start_run`, `orca_get_run`, `orca_stop_run`, etc.) — 11 tools total.
- The agent operates within a **single Claude Code session**. For issues requiring hours of waiting, it escalates to the user rather than trying to persist across sessions.

## Mission Parsing

The agent receives natural language instructions and extracts:

- **Flows**: what workflows to run and in what order
- **Target project path**: where the target repo lives
- **Success criteria**: what "done" looks like (implicit or explicit)
- **Autonomy level**: `full`, `supervised`, or `cautious` (default: `supervised`)

The agent confirms its understanding of the mission before starting. No formal parameter schema — the skill teaches the agent to extract these from conversation context.

## The Monitor-Assess-Act Loop

The core of the skill is a repeating loop for each active flow.

```
PARSE MISSION
  Extract: flows, order, target, autonomy
  Confirm understanding with user
         │
         ▼
ENSURE PREREQUISITES
  Daemon running? Target project exists?
  Docker available? (if needed)
         │
         ▼
START NEXT FLOW  ◄──────────────────────┐
  orca_start_run(task, workflow, branch) │
         │                              │
         ▼                              │
MONITOR                                 │
  Poll orca_get_run() every 30-60s      │
  Track: issue states, active workers,  │
         terminal count vs total        │
         │                              │
         ▼                              │
ASSESS                                  │
  Classify situation:                   │
  - PROGRESSING: workers active, moving │
  - STALLED: no progress for 3+ polls   │
  - FAILED: issues hitting failure_count│
  - COMPLETED: all issues terminal      │
         │                              │
         ▼                              │
ACT                                     │
  PROGRESSING → continue monitoring     │
  STALLED → diagnose, remediate or wait │
  FAILED → read logs, try remediation   │
  COMPLETED → chain next flow ──────────┘
              or report done
```

### Prerequisite Checks

Before starting the first flow, the agent verifies:

1. **Daemon running** — call `orca_daemon_status`. If it fails, start the daemon with `orca daemon start`, wait a few seconds, verify again.
2. **Target project exists** — check that the target project path exists and is a git repo.
3. **Task file exists** — verify the task file for the first flow is present at the expected path.
4. **Flow-specific deps** — if the mission mentions docker, verify `docker info` succeeds. If not, attempt remediation per the catalog and autonomy level.

### Polling Behavior

- **Base interval**: 30s, backs off to 60s when stable.
- **Alert interval**: 15s when issues are detected.
- **Stall detection**: if `terminal_count` and active workers haven't changed across 3+ polls, classify as STALLED.
- **Proactive failure detection**: if any issue's `failure_count` exceeds `max_worker_retries / 2`, investigate immediately rather than waiting for orca to exhaust all retries.

## Autonomy Tiers

Three levels controlling what the agent does without asking. The tier governs *creative problem-solving* autonomy, not safety overrides — even at `full`, destructive/shared-state actions require confirmation.

### `cautious`

**Autonomous:**
- Start flows explicitly listed in the mission
- Poll and report status
- Read logs and diagnose problems
- Retry failed issues (`orca_retry_issue`)

**Requires confirmation:**
- Any environment changes (start docker, install deps)
- Stopping or dropping runs
- Chaining to flows not explicitly listed in the mission
- All code changes (orca source, prompts, target project)
- Waiting longer than 5 minutes for transient issues

### `supervised` (default)

**Autonomous** (everything in cautious, plus):
- Environment remediation for known issues (from catalog)
- Stop and restart stalled runs
- Chain to the next flow in the stated mission sequence
- Apply known prompt fixes (from catalog)
- Wait up to 15 minutes for transient issues

**Requires confirmation:**
- Orca source code changes (self-healing)
- Novel remediations not in the catalog
- Dropping runs
- Prompt changes beyond the known-issue catalog
- Modifying target project code (beyond prompts)

### `full`

**Autonomous** (everything in supervised, plus):
- Orca source code fixes (self-healing)
- Novel remediations based on diagnosis
- Drop and re-create runs when recovery fails
- Prompt improvements beyond the catalog

**Requires confirmation:**
- Pushing code to remote repositories
- Actions affecting other users' branches
- Destructive operations (deleting worktrees, dropping data)

## Diagnosis Framework

When the loop detects STALLED or FAILED, the agent follows structured diagnosis before acting.

### Diagnosis Steps

```
1. GATHER
   ├── orca_get_run(run_id)            → run status, issue states
   ├── orca_get_issue(run_id, id)      → for each non-terminal issue
   ├── orca_get_worker_log(run_id, id) → for failed/stalled issues
   └── orca_get_insights(run_id)       → orchestrator-level insights

2. CLASSIFY root cause
   ├── ENVIRONMENT  — missing tool, service down, permission error
   ├── TRANSIENT    — rate limit, network blip, API timeout
   ├── ORCA_BUG     — orca itself misbehaving (crash, bad state)
   ├── PROMPT_ISSUE — worker confused, wrong output, looping
   └── TASK_ISSUE   — the task itself is impossible/underspecified

3. MATCH against catalogs
   ├── Known issue? → apply fix from remediation-catalog or prompt-issues
   └── Novel issue? → escalate (cautious/supervised) or attempt fix (full)
```

### Classification Signals

| Root Cause | Signals in Logs |
|---|---|
| ENVIRONMENT | "command not found", "docker: not running", "EACCES", "connection refused" on localhost |
| TRANSIENT | "rate limit", "503", "timeout", "ECONNRESET", intermittent (worked before) |
| ORCA_BUG | Python traceback in daemon logs, state inconsistency (worker_active=true but no process), resume fails |
| PROMPT_ISSUE | Worker produces invalid result repeatedly, worker loops doing same thing, result doesn't match format |
| TASK_ISSUE | Worker explicitly says "impossible"/"unclear", failure persists after prompt and env fixes |

### Diagnosis Rules

- **Never remediate without diagnosis.** Classify first, then act. Blind retries waste time.
- **One fix at a time.** Apply one remediation, retry, observe. Don't stack multiple fixes.
- **Escalation budget.** After 2 failed remediation attempts for the same issue, escalate to user regardless of autonomy level.
- **Log everything.** Report diagnosis and reasoning before taking action.

## Remediation Actions

### ENVIRONMENT Remediation

The agent runs shell commands from the orca repo to fix environment issues.

- **Docker not running** → platform-appropriate start command, poll until docker responds, retry the flow
- **Missing CLI tool** → check if installable (brew/apt/npm), install if autonomy allows, or tell user what to install
- **Port conflict** → identify the blocking process, report to user (never kill unknown processes autonomously)
- **Permission error** → report to user with specific fix suggestion

The catalog (`remediation-catalog.md`) maps error patterns to fix commands. The agent matches log output against patterns.

### TRANSIENT Remediation

- **Short wait** — stop the run, wait the indicated or estimated time (within autonomy tier's limit), resume
- **Retry** — `orca_retry_issue` for connection resets and timeouts
- **Reclassify** — if transient failures persist across 3+ retries, reclassify as something deeper

### ORCA_BUG Remediation (self-healing)

The agent is running from the orca repo, so it can:

1. Read the Python traceback from daemon/worker logs
2. Search orca source code for the relevant module/function
3. Diagnose the bug
4. Fix the code
5. Verify: `uv run ruff check .` and `uv run mypy src/` must pass
6. Commit the fix
7. Restart the daemon (`orca daemon stop && orca daemon start`)
8. Resume the affected run

**Constraints:**
- Only at `full` autonomy (otherwise escalate with diagnosis)
- Lint and type checks must pass before restarting
- Creates a git commit with the fix before restarting
- If the fix doesn't resolve the issue on retry, revert the commit and escalate

### PROMPT_ISSUE Remediation

The agent reads the prompt issues catalog (`prompt-issues.md`) and matches against observed failure patterns.

Common patterns:
- **Missing context** — prompt doesn't give the worker enough info about the repo/task
- **Unclear result format** — worker produces wrong JSON shape repeatedly
- **Missing constraints** — worker does something valid but unwanted
- **Infinite loop** — worker keeps retrying the same approach, prompt lacks "try different approach" directive

Each catalog entry has: pattern (what to look for in logs), root cause, fix template, and which prompt file to modify.

**Autonomy controls:**
- `cautious`: report findings only
- `supervised`: apply catalog fixes, escalate novel issues
- `full`: attempt novel prompt edits based on diagnosis
- Always retry with the fix before declaring success

### TASK_ISSUE Escalation

Not remediable by the agent. The agent:

1. Reports what was attempted and why it failed
2. Quotes relevant worker log excerpts
3. Suggests what the user might clarify or change
4. Stops the flow (preserves state for resume after user fixes things)

## Flow Chaining

When a mission involves multiple flows in sequence, the agent manages transitions.

### Chain Behavior

```
Flow A completes
       │
       ▼
  Evaluate outcome
       │
       ├── SUCCESS        → Start Flow B with context from A
       ├── PARTIAL         → Decide: proceed with what succeeded, or fix first?
       └── FAILED          → Diagnose and remediate A, don't start B
```

### Context Passing Between Flows

1. After Flow A completes, read the run state to understand what was produced
2. Verify the target project's working state reflects expected output (e.g. PRD doc exists after prd flow)
3. Start Flow B on the **same branch**, inheriting git state from Flow A
4. If Flow B needs a different task file, locate the existing one or note that the user needs to provide it

### Chain Decisions

The agent uses judgment, not rigid rules:

- **Clear sequence** (e.g. "prd then qa-spec") — chain automatically on success
- **Dependent flows** (e.g. "prd then implement") — verify prior output looks reasonable before launching
- **Partial success** — assess whether the failed issue blocks the next flow. If independent, proceed. If critical, fix first.
- **Unexpected outcomes** — if prior flow produces something unexpected, pause and report

### Branch Strategy

- All flows in a mission chain run on the **same branch** by default
- User-specified branches are respected
- The agent never creates branches on its own unless instructed

## Reference Doc Structures

### `remediation-catalog.md`

Organized by root cause category. Each entry:

```markdown
### <Issue Name>

**Pattern:** <error string or regex to match in logs>
**Platform:** <macOS / Linux / both>
**Fix:**
- <platform-specific command(s)>
**Verify:** <command that confirms the fix worked>
**Risk:** <low / medium / high>
```

Initial entries (~10): docker not running, node/npm missing, git worktree conflicts, port conflicts, disk space, file permissions, python venv issues, missing env vars, stale lockfiles, DNS resolution.

### `prompt-issues.md`

Each entry:

```markdown
### <Issue Name>

**Pattern:** <what to look for in worker logs>
**Root cause:** <why this happens>
**Fix:** <what to add/change in the prompt template>
**Applies to:** <which prompt templates>
**Risk:** <low / medium>
```

Initial entries (~8): invalid result JSON, worker looping, worker ignoring constraints, worker modifying wrong files, worker not committing, worker stuck on tests, worker producing empty output, worker misunderstanding decomposition.

### `flow-patterns.md`

Common mission patterns with guidance:

```markdown
### <Pattern Name>

**When:** <when to use this pattern>
**Chain:** <flow sequence>
**Notes:**
- <guidance for the agent>
**Common failures:**
- <known issues and how to handle them>
```

Initial entries (~5): PRD → QA Spec → Implement, single-flow monitoring, bug investigation flow, parallel feature flows, iterative refinement.

## Session Exit Behavior

The agent operates within a single Claude Code session. When it needs to stop (context limits approaching, user interrupts, or long wait required):

1. **Report current state** — summarize: which flows completed, which are in progress, what issues are pending, any diagnosed problems.
2. **Leave runs in a resumable state** — don't drop runs. If a run is actively failing, stop it so it can be resumed later.
3. **Provide resume instructions** — tell the user exactly how to pick up where the agent left off: which run IDs to resume, what the next flow in the chain would be, any pending remediations.
4. **Suggest re-invocation** — if the remaining work is mechanical (e.g. "resume run X, then start qa-spec flow"), give the user the exact mission string to use when re-invoking the manager.

## MCP Tools Reference

The agent interacts with orca exclusively through these 11 MCP tools:

| Tool | Purpose | Used In |
|---|---|---|
| `orca_daemon_status` | Check daemon is alive, get active run count | Prerequisites, monitoring |
| `orca_start_run` | Start a new workflow run | Flow start |
| `orca_list_runs` | List all runs with status summaries | Monitoring, situational awareness |
| `orca_get_run` | Get detailed run state and sessions | Monitoring, assessment |
| `orca_get_issue` | Get issue details (state, failure_count, event_log) | Diagnosis |
| `orca_get_worker_log` | Read worker session output | Diagnosis |
| `orca_get_insights` | Read orchestrator insights log | Diagnosis |
| `orca_retry_issue` | Retry a failed issue | Remediation |
| `orca_stop_run` | Stop a running workflow | Remediation, transient waits |
| `orca_resume_run` | Resume a stopped workflow | Remediation, transient waits |
| `orca_drop_run` | Drop a run entirely (delete state) | Cleanup, full-autonomy recovery |
