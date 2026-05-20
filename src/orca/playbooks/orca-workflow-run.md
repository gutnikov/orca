# Playbook: Run and Supervise an Orca Workflow

Start an orca run from a task description, then supervise it through to a terminal state — surfacing `waiting` outcomes to the user, handling stuck workers, and walking through the merge (if applicable) at the end.

## Prerequisites

- Orca CLI installed ([orca-install.md](orca-install.md)).
- A `.orca/{flow}.yml` exists in the current project. If not, follow [orca-workflow-create.md](orca-workflow-create.md) first.
- Working directory is the project root.
- Git tree is clean — or, if dirty, you've confirmed with the user that the dirty state is expected (e.g., a running worker mid-work).

## Scope of this playbook

This playbook is self-contained: it covers pre-flight (Phase A), task composition (Phase B), the watch loop (Phase C), the post-completion merge plan (Phase D), and wrap-up (Phase E). With the orca plugin installed, the `orca-workflow-run` skill auto-triggers on phrases like *"supervise the run"* or *"babysit orca"* — it runs the watch loop directly (no task composition), useful when the user is already mid-run and just wants oversight. The skill invokes the same Phase C as a fresh run; the implementation here is the canonical version.

## Phase A — Pre-flight

Run these checks in order:

1. **Daemon is up:**
   ```bash
   orca daemon status
   ```
   If not running: `orca daemon start`. If start fails, surface the error — do not try workarounds.

2. **No conflicting run is in flight.** Orca can track multiple run ids in one project, but this playbook supervises one run at a time, and concurrent runs can collide if they touch the same branch or files. The daemon rejects a duplicate running `run_id`; it does not prove two distinct run ids are safe to run together.
   ```bash
   orca runs
   ```
   - If a `RUNNING` run exists → ask whether to supervise that run or start a separate one with a distinct branch/run id. Default to supervising the existing run unless the user explicitly wants parallel work.
   - If a `FAILED` / `INTERRUPTED` run exists → ask the user: resume it (`orca resume <run_id>`) or drop it (`orca drop <run_id>`)?
   - If a `STOPPED` run exists (user previously ran `orca stop`) → ask: resume (`orca resume`) or drop (`orca drop`)? Don't auto-resume — they stopped it for a reason.
   - If a `COMPLETED` run is sitting around → ask the user whether to drop it before starting new work.

3. **Pick the workflow.** Read `.orca/`:
   ```bash
   ls .orca/*.yml
   ```
   - One workflow → use it; tell the user which.
   - Multiple → ask the user which one applies to this task.

## Phase B — Compose the task and start the run

### 1. Learn the input schema

Read the chosen workflow's `issue.fields` block to see what fields are required. Cross-reference with any existing examples under `input/`, `tasks/`, or `task.md` in the project.

### 2. Draft the task file

Show the user a draft `task.md` (or `input/<id>.yml` — match the project's existing convention) with:
- All required issue fields populated from the user's request
- A short, slugified ID if the workflow uses one (e.g., `add-dark-mode`, `fix-board-drag`)
- No invented details — if the user's description is missing a required field, **ask one focused clarifying question** rather than filling it in silently

**Confirm with the user before writing the file.**

### 3. Write the file and commit (if the project commits task files)

```bash
# only if the project's convention is to commit task files
git add <task-file>
git commit -m "chore: add input for <id>"
```

### 4. Start the run

Via CLI:
```bash
orca run <task-file> [flags]
```

Available flags (defaults shown):

| Flag | Default | What it does |
|---|---|---|
| `-w, --workflow <name>` | `default` | Pick a non-default workflow under `.orca/`. Pass the filename without `.yml` (e.g. `-w develop` loads `.orca/develop.yml`). |
| `-b, --branch <name>` | auto-derived | Override the run branch. Auto-derivation pulls from issue fields and the current git state; pass this only when you need a specific branch name. |
| `--base <ref>` | from config `base_branch`, else `origin/main` | What the new run branch is cut from. |
| `--run-id <id>` | `<branch>:<workflow>` | Override the run identifier. Rarely needed. |
| `--max-hops <N>` | 10 | Cap total state transitions per issue. Overrides the CLI default; workflow YAML does not currently set this. |
| `--max-retries <N>` | 3 | Cap worker failures per issue per state. Overrides the CLI default; workflow YAML does not currently set this. |
| `--headless` | off | Suppress TUI output; useful for scripted invocations. |
| `--insights` | off | Generate an insights log alongside the run (readable via `orca_get_insights`). |

Or via MCP (if invoked through Claude Code / Cursor / etc.):
```
orca_start_run(root="<absolute path>", task_file="<task-file>", workflow="<flow-name>", branch=None, run_id=None)
```

The MCP form exposes only the four common arguments (`root`, `task_file`, `workflow`, `branch`, `run_id`). For `--base`, `--max-hops`, `--max-retries`, `--headless`, `--insights` you need the CLI form.

`workflow` is optional — omit it to load `.orca/default.yml`. Pass it only when the project has multiple workflows under `.orca/` and you need a specific one.

`orca_start_run` returns a `run_id`. Capture it.

If start fails, surface the error to the user — do not retry blindly.

## Phase C — Supervise (the watch loop)

Discover the workflow's effective `max_worker_retries` and `max_hops`. CLI `orca run` applies defaults of **3** retries and **10** hops unless the user passed `--max-retries` / `--max-hops`; workflow YAML does not currently set these limits. `orca eval` submits 2 / 10. MCP starts may not expose effective limits, so if you cannot read them from the caller context, use 3 / 10 as supervision thresholds and note the assumption. Call them `MAX_RETRIES` and `MAX_HOPS` below.

### Loop

1. Sleep ~45 seconds (skip on the very first iteration).
2. `orca_get_run(root, run_id, compact=true)` and `orca_get_worker_log(root, run_id, issue_id, tail=50)`.
3. Print one line: `[poll N] state=<state> — worker active (hop X, failures Y)`.
4. Classify and route:

   | Signal | Action |
   |---|---|
   | `worker_active: true`, log progressing, `failure_count < MAX_RETRIES`, `hop_count < MAX_HOPS` | Healthy — continue. |
   | Run status becomes `COMPLETED` | Exit loop → Phase D. |
   | Worker outcome is `waiting` | Not stuck — surface to user. See below. |
   | `worker_active: false`, run still `RUNNING`, `failure_count < MAX_RETRIES` | Orca will auto-retry. Note in session, continue. |
   | `worker_active: false`, run still `RUNNING`, `failure_count >= MAX_RETRIES` | Treat as stuck. |
   | `hop_count >= MAX_HOPS - 2` and the same cycle is repeating | Treat as stuck (loop). |
   | Same error across consecutive retries | Treat as stuck. |
   | `worker_active: true`, no new log lines across two consecutive polls, log ends with idle prompt | Zombie worker — treat as stuck. |
   | Run status `FAILED` or `INTERRUPTED` | One `orca_resume_run(root, run_id)`, then continue. If status flips back to `FAILED`, surface. |

### `waiting` outcome — surface, don't fix

The worker paused and is asking for human input. Different workflows ask different things (review of generated work, confirmation before a destructive step, a choice between alternatives, a clarification). Surface what the worker actually produced — don't paraphrase or impose a template structure:

- One-line headline of what the worker is asking.
- Relevant excerpt from the worker's output, lightly trimmed if very long.
- Pertinent context: files changed, commands proposed, options offered.
- An explicit ask matching the worker's request.

End your turn. When the user replies, `orca_unblock_worker(root, run_id, issue_id, <user reply>)` and resume polling.

### Stuck-state remediation

At most **one** auto-remediation per issue per session. If it doesn't fix it, surface to the user.

| Symptom | First auto-remediation | If still stuck |
|---|---|---|
| Zombie worker / idle prompt | `orca_unblock_worker` with a generic nudge (e.g. *"Continue with the next step. If you've finished the current state's work, write your result and conclude."*) | Surface to user |
| Repeated identical errors | `orca_retry_issue(root, run_id, issue_id)` once | Surface to user |
| `FAILED` / `INTERRUPTED` | `orca_resume_run(root, run_id)` once | Surface to user |
| Crashed beyond `MAX_RETRIES` | `orca_resume_run(root, run_id)` once | Surface to user |
| State cycle / hop limit nearing | None — surface immediately (judgment call) | n/a |
| Dirty tree, no active worker | None — surface immediately | n/a |

When surfacing to the user, always include: what you observed (1-2 sentences), what you tried (if anything), last 20–30 lines of worker log, and concrete options ("Stop the run?", "Try X?", "Drop and restart?", "Something else?").

### Critical rules

- **`waiting` is not a failure** — it's the worker's handoff for human input.
- **Don't auto-stop the run on failure.** Surface and let the user decide.
- **Never `git stash` / `git checkout .` / modify the worktree silently.** A worker may be mid-work in a tree that looks dirty from outside.
- **One remediation per issue per session.** If it didn't work, don't loop.

## Phase D — Run completed

When the run reaches `COMPLETED`, decide if a merge applies.

1. Pull the full run state:
   ```
   orca_get_run(root, run_id)
   ```
   Look at `branch` and the workflow's final output.

2. **Merge applies** when:
   - The run has a `branch` field that isn't the project's default (`main` / `master`).
   - `git log <default>..<branch>` shows commits.

3. **If merge applies**, show the user the plan and ask for approval:
   ```
   git checkout <default> && git pull origin <default>
   git merge <branch> --no-ff -m "merge: <branch> — <title>"
   git push origin <default>
   git branch -d <branch>
   ```

   On approval, execute in order. **Push fails because remote moved:** try `git pull --rebase origin <default> && git push origin <default>` once; if it still fails, surface. **Merge conflict:** show conflicting files and ask the user how to handle. Never force-push, never silently resolve conflicts, never `git stash` to "clean up" a dirty tree.

   Once merged: `orca_drop_run(root, run_id)` to clean up orca state.

4. **If merge doesn't apply** (one-shot operation, analysis, deploy, scripted task with no branch):
   - Summarize what the run produced (read worker output / result files)
   - Ask: drop the run or keep it for inspection?
   - Act on the user's choice

## Phase E — Wrap up

Tell the user:
- What was produced (PR / branch / report / result files)
- What was merged or kept
- Any follow-ups surfaced during the run that weren't part of the task
- Suggest the next action (open the next task? audit the workflow if it surfaced bugs? `orca tui` for live state?)

## Anti-patterns to refuse

- **Auto-stopping a `FAILED` run.** Surface the failure and let the user decide. Stopping is destructive in the sense that resume options narrow afterwards.
- **`git stash` / `git checkout .` to "clean up" a dirty tree.** A running worker may be mid-write. Ask the user before touching the worktree.
- **Force-pushing to recover a merge.** Never. Surface and ask.
- **Looping on remediations.** One auto-remediation per issue per session — then surface.
- **Inventing task fields.** If the user's description doesn't supply a required field, ask one focused question rather than guessing.
- **Treating `waiting` as failure.** It's a handoff, not a crash. Don't retry it.

## Useful commands reference

Run-flow commands:

| Command | Use |
|---|---|
| `orca run <task> [-w <flow>]` | Submit a new run; `-w` selects a workflow other than `default` |
| `orca runs` | List runs (any status) |
| `orca tui` | Live dashboard — issue tree, worker terminals, history |
| `orca logs <run_id> <issue_id>` | Tail worker logs |
| `orca stop <run_id>` | Stop a running workflow (ask user first) |
| `orca resume <run_id>` | Resume a stopped/failed/interrupted run |
| `orca retry <run_id> <issue_id>` | Retry a failed issue |
| `orca drop <run_id>` | Remove a run from the daemon |
| `orca unblock <run_id> <issue_id> -m "<msg>"` | Reply to a `waiting` worker |

Project-setup commands (out of scope for this playbook, but listed for completeness):

| Command | Use |
|---|---|
| `orca init` | Deprecated; no-op except for removing a legacy `.orca/playbooks/` directory if present |
| `orca clean` | Remove terminal-state runs and accumulated artifacts |
| `orca daemon {start,stop,status}` | Manage the per-project daemon |
| `orca mcp` | MCP stdio bridge (for editor integrations) |

MCP tool equivalents (when invoked through a coding agent):

| MCP tool | Closest CLI | Notes |
|---|---|---|
| `orca_daemon_status` | `orca daemon status` | |
| `orca_start_run` | `orca run` | Subset of CLI flags — see Phase B step 4. |
| `orca_list_runs` | `orca runs` | |
| `orca_get_run` | (no CLI) | Use `compact=true` while polling to save context tokens. |
| `orca_get_issue` | (no CLI) | Inspect a single issue by id. Useful inside multi-issue runs. |
| `orca_get_insights` | (no CLI) | Read the insights log when the run was started with `--insights`. |
| `orca_get_worker_log` | `orca logs <run_id> <issue_id>` | Pass `tail=N` for trailing lines; the CLI's `--tail N` does the same. |
| `orca_unblock_worker` | `orca unblock <run_id> <issue_id> -m "msg"` | |
| `orca_retry_issue` | `orca retry <run_id> <issue_id>` | |
| `orca_resume_run` | `orca resume <run_id>` | |
| `orca_drop_run` | `orca drop <run_id>` | |
| `orca_stop_run` | `orca stop <run_id>` | |
| `orca_get_playbook` | (no CLI) | Read a playbook by name (e.g. "orca-workflow-run"). Used by the orca plugins to load instructions. |
| `orca_list_playbooks` | (no CLI) | Enumerate available playbooks. |

If you're driving from a shell rather than a host CLI, the `orca logs <run_id> [issue_id] [--tail N]` command is the shell fallback for tailing worker output — same content as `orca_get_worker_log`. Omit `issue_id` to list issues in the run; pass `--tail` to bound output.
