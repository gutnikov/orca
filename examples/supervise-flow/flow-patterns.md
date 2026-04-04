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
