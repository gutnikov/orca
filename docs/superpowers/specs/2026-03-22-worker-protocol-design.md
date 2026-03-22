# Worker Protocol & Orchestrator Design

## Overview

The engine's pure reducer produces `DispatchWorkerEffect`s when issues enter active states. This design defines the orchestrator layer that consumes those effects, spawns workers, collects results, and feeds events back to the reducer. The primary worker implementation is `claude-code` — a CLI coding agent run as a subprocess.

## Config Changes

### Worker Definition

The `worker` block in `orca.yml` gains `kind`, `prompt`, and optional `timeout`:

```yaml
states:
  implementing:
    worker:
      kind: claude-code
      prompt: prompts/impl.md
      timeout: 300
      result_format:
        outcome:
          type: enum
          values: [done, split]
          description: "Work outcome"
        summary:
          type: string
          description: "Summary of work"
          required_when: done
        sub_issues:
          type: list
          items: $issue
          description: "Sub-tasks"
          required_when: split
    on:
      done: review
      split:
        action: decompose
```

**Fields:**

| Field | Required | Description |
|-------|----------|-------------|
| `kind` | yes | Worker implementation. Only `"claude-code"` supported. |
| `prompt` | yes | Path to Jinja2 template file, relative to repo root. |
| `timeout` | no | Max execution time in seconds. No limit if omitted. |
| `result_format` | yes | Schema for the worker's output (unchanged from current). |

### Type Changes

**`WorkerDef`** in `types.py`:

```python
@dataclass(frozen=True)
class WorkerDef:
    kind: str
    prompt: str
    result_format: dict[str, ResultFormatField]
    timeout: int | None = None
```

**`DispatchWorkerEffect`** — unchanged. The effect retains its current fields (`issue_id`, `state`, `result_format`, `issue`). The orchestrator resolves `kind`, `prompt`, and `timeout` from the config using `effect.state`:

```python
worker_def = config.states[effect.state].worker
kind = worker_def.kind       # e.g. "claude-code"
prompt = worker_def.prompt   # e.g. "prompts/impl.md"
timeout = worker_def.timeout # e.g. 300 or None
```

### Config Validation

Added to `config.py` in `_parse_state`:

- `kind` must be `"claude-code"` (only supported value).
- `prompt` must be a non-empty string. File existence is checked at runtime by the orchestrator, not at config parse time.
- `timeout`, if present, must be a positive integer.

The config parser reads these new fields from the `worker` YAML block and passes them to the `WorkerDef` constructor alongside the existing `result_format` parsing.

### Impact on Reducer and Effects

None. `DispatchWorkerEffect` is unchanged. The reducer does not use `kind`, `prompt`, or `timeout` — it only constructs effects with `issue_id`, `state`, `result_format`, and `issue` as before. The orchestrator looks up worker metadata from the config. The reducer remains pure and untouched.

## Module Structure

New package `src/orca/orchestrator/` alongside existing `src/orca/engine/`:

```
src/orca/
├── engine/              # existing — pure reducer, untouched
│   ├── types.py
│   ├── config.py
│   ├── reducer.py
│   └── dispatch.py
├── orchestrator/        # new
│   ├── __init__.py
│   ├── runner.py        # CLI entry point + run lifecycle
│   ├── orchestrator.py  # async event loop
│   ├── worker.py        # Worker protocol + claude-code implementation
│   ├── worktree.py      # git worktree management
│   ├── template.py      # Jinja2 rendering
│   └── persistence.py   # state load/save
```

### Responsibilities

| Module | Does | Doesn't |
|--------|------|---------|
| `runner.py` | Parse CLI args, create root branch, create root issue, load config, start orchestrator | Manage workers, touch git worktrees |
| `orchestrator.py` | Async event loop, call reducer, route effects to handlers, feed events back | Know about Claude Code, git, or templates |
| `worker.py` | Define `Worker` protocol, implement `ClaudeCodeWorker` — render prompt, spawn subprocess, read/validate result file, clean up old result file | Manage state, decide what to dispatch |
| `worktree.py` | Create worktrees, resolve paths, derive branch names from issue hierarchy | Know about workers or state machine |
| `template.py` | Load Jinja2 template, render with issue context + output rules + result path | Know about worker execution |
| `persistence.py` | Save/load `State` to `.orca/runs/{branch}/state.json` | Make decisions about state |

## CLI Entry Point

```
orca run <task-file> <branch-name>
```

### `runner.py` Lifecycle

1. **Read task file** — first line is title, rest is description.
2. **Load config** — parse `orca.yml` from repo root.
3. **Create root branch and worktree** — `git branch {branch-name}` from current HEAD (does not switch branches), then create a worktree at `.orca/worktrees/{branch-name}/` for the root issue. The repo root's checked-out branch is never changed.
4. **Initialize or resume state:**
   - If `.orca/runs/{branch-name}/state.json` exists, load it (crash recovery).
   - Otherwise, create fresh `State`, emit `CreateEvent` with `fields.title` and `fields.description`.
5. **Set up components** — `WorktreeManager`, `Persistence`, `ClaudeCodeWorker`.
6. **Persist initial state.**
7. **Start orchestrator** — pass state, config, components, initial effects.

### Crash Recovery

On resume, the runner loads persisted state and scans for issues with `worker_active: true` in active states. For each:

1. **Check for existing result file** in the issue's worktree (`.orca/result.json`).
2. If a valid result file exists, validate it against `result_format`. If valid, feed a `WorkerResultEvent` instead of re-running the worker.
3. If no result file or invalid, re-emit a `DispatchWorkerEffect` to re-dispatch the worker.

### Multiple Concurrent Runs

Each `orca run` operates independently:

```
orca run task1.md branch-1
orca run task2.md branch-2
```

Both create their own root branch from current HEAD. Worktrees and state are isolated per branch name. No shared mutable state between runs.

## Orchestrator Event Loop

### `orchestrator.py`

```python
class Orchestrator:
    def __init__(
        self,
        config: StateMachineConfig,
        state: State,
        root_branch: str,
        worktrees: WorktreeManager,
        persistence: Persistence,
        workers: dict[str, Worker],  # {"claude-code": ClaudeCodeWorker()}
    ): ...

    async def run(self, root_issue_id: str, initial_effects: list[Effect]) -> None:
        """Run until root issue reaches terminal state."""
```

### Event Loop Logic

```
1. Start with initial effects from root issue creation.
2. While root issue is not terminal:
   a. For each pending DispatchWorkerEffect:
      - Ensure worktree exists (create if first dispatch for this issue).
      - Spawn worker as asyncio.Task.
   b. Await any worker completion (asyncio.wait, FIRST_COMPLETED).
   c. Build WorkerResultEvent or WorkerFailedEvent from WorkerOutcome.
   d. Call reduce(config, state, event, generate_id, now) → (new_state, effects).
      The orchestrator supplies `generate_id` (e.g. `uuid4`) and `now` (e.g. `datetime.now(UTC).isoformat`).
   e. Persist new_state.
   f. Add new effects to pending queue.
   g. Handle ErrorEffects (log).
3. Done — root issue is terminal.
```

### Concurrency Model

- Multiple workers run concurrently as `asyncio.Task`s.
- Reducer calls are **serialized** — only one `reduce()` at a time since state is single-threaded.
- When a worker completes, its event is queued and processed in order.
- New effects from a `reduce()` call may spawn more workers immediately.
- Concurrency limits (`max_workers`) are enforced by the reducer/dispatch layer, not the orchestrator.

### Worker Tracking

```python
self._in_flight: dict[asyncio.Task, str] = {}  # task → issue_id
```

Uses `asyncio.wait(return_when=FIRST_COMPLETED)` to process results as they arrive.

### Shutdown

When the root issue reaches terminal state, cancel any remaining in-flight tasks (defensive — shouldn't happen if the state machine is well-formed).

## Worker Protocol

### Protocol Definition

```python
class Worker(Protocol):
    async def execute(
        self,
        effect: DispatchWorkerEffect,
        workdir: Path,
        result_path: Path,
    ) -> WorkerOutcome: ...
```

### Worker Outcome Types

```python
@dataclass(frozen=True)
class WorkerSuccess:
    result: dict[str, Any]  # validated against result_format

@dataclass(frozen=True)
class WorkerFailure:
    error: str

WorkerOutcome = WorkerSuccess | WorkerFailure
```

### Claude Code Worker Implementation

The `ClaudeCodeWorker` spawns a `claude` CLI subprocess:

1. **Delete previous result file** if it exists (clean slate).
2. **Render prompt template** via `template.py` with issue context.
3. **Spawn subprocess** — `claude --print --output-format stream-json --max-turns 50`, prompt on stdin.
4. **Stream stdout** line by line — each line is a JSON message. Write to session log for observability.
5. **Wait for exit** — check return code.
6. **Read result file** — parse JSON.
7. **Validate result** against `result_format`.
8. **Return** `WorkerSuccess` or `WorkerFailure`.

### Session Logs

Each worker run produces a session log:

```
{workdir}/.orca/sessions/{state}-{timestamp}.jsonl
```

Session logs accumulate across the issue lifecycle. An issue going through `planning` → `implementing` → `applying` → (conflict) → `implementing` → `applying` produces five session files. These are for observability and debugging. Since all issues (including root) have worktrees, session logs are always at `{worktree}/.orca/sessions/`.

### Result File

Single fixed path per worktree: `{workdir}/.orca/result.json`. Deleted before each worker run — clean slate, no risk of a worker reading stale results from a prior phase.

### Timeout Handling

If `timeout` is configured, `asyncio.wait_for` wraps the subprocess execution. On timeout, the process is killed and `WorkerFailure(error="timeout")` is returned.

## Result Validation

The orchestrator validates the worker's output before feeding it to the reducer. Validation lives in `worker.py`.

```python
def validate_result(result: dict[str, Any], result_format: dict[str, Any]) -> str | None:
    """Return error message if invalid, None if valid."""
```

### Validation Rules

1. Result must be valid JSON and a dict.
2. Must contain `outcome` field.
3. `outcome` value must be in the enum's `values`.
4. Fields with `required_when` matching the outcome must be present and non-empty.
5. If outcome routes to `action: decompose`, `sub_issues` must be a non-empty list.
6. Extra fields are ignored (forward-compatible).

### What Is Not Validated Here

- Sub-issue field contents — the reducer validates those on `CreateEvent`.
- `depends_on` references within sub-issues — the reducer handles cycle and reference validation.

Validation at the boundary, trust internally. Matches golden principle #5.

## Worktree Management

### `worktree.py`

```python
class WorktreeManager:
    def __init__(self, repo_root: Path, root_branch: str):
        self.repo_root = repo_root
        self.root_branch = root_branch

    async def create(
        self,
        issue_id: str,
        branch_name: str,
        parent_branch: str,
    ) -> Path:
        """Create worktree, return its path."""
        worktree_path = self.repo_root / ".orca" / "worktrees" / branch_name
        # git worktree add -b {branch_name} {worktree_path} {parent_branch}
        return worktree_path

    def resolve(self, branch_name: str) -> Path:
        """Get path for existing worktree."""
        return self.repo_root / ".orca" / "worktrees" / branch_name
```

### Branch Naming Convention

Decompose keys chain to form branch names:

```
root branch:      my-feature
child (key=db):   my-feature/db
nested (key=idx): my-feature/db/idx
```

### Worktree Directory Layout

```
{repo}/.orca/worktrees/{branch-name}/   # the actual worktree checkout
```

### Worktree Lifecycle

- **Root issue:** Gets a worktree like any other issue, at `.orca/worktrees/{root-branch}/`, branched from the commit where `orca run` was invoked. This avoids ambiguity about which branch is checked out in the repo root — the repo root's branch is never changed.
- **Sub-issues (from decompose):** Orchestrator creates worktree on first `DispatchWorkerEffect` for that issue. Subsequent workers for the same issue reuse the worktree.
- **Cleanup:** Manual for now. Worktrees persist after the run completes.

### Issue-to-Branch Mapping

The orchestrator needs to map issue IDs to branch names. Branch names are derived from decompose keys (e.g., `my-feature/db`), but the engine's `Issue` type does not store the decompose key — it only appears in the `WorkerResultEvent.result["sub_issues"]` list.

**Solution:** The orchestrator maintains a persistent mapping of issue ID → branch name in `.orca/runs/{branch}/branches.json`. This mapping is updated:

1. **Root issue:** mapped to `{root-branch}` at run start.
2. **Sub-issues:** When the orchestrator processes a `WorkerResultEvent` with a decompose outcome, it inspects `result["sub_issues"]` to extract the `key` for each sub-issue. The reducer's response includes `CreateEvent`-derived effects for the new issues. The orchestrator correlates new issue IDs with their keys (by matching fields) and builds the branch name by appending the key to the parent's branch name.

Example mapping:

```json
{
  "issue-001": "my-feature",
  "issue-002": "my-feature/db",
  "issue-003": "my-feature/api"
}
```

### Branch-to-Parent Resolution

For a sub-issue, the parent branch is looked up from the mapping using `decomposed_from`:

```python
parent_branch = branches[issue.decomposed_from]
child_branch = f"{parent_branch}/{decompose_key}"
```

This chains naturally for nested decomposition: `my-feature` → `my-feature/api` → `my-feature/api/validation`.

## Template Rendering

### `template.py`

```python
def render_prompt(
    template_path: Path,
    issue: dict[str, Any],
    result_format: dict[str, Any],
    result_path: Path,
) -> str:
    """Load and render a Jinja2 template with issue context."""
```

### Template Context Variables

| Variable | Type | Description |
|----------|------|-------------|
| `issue.fields` | dict | User-defined fields (title, description, etc.) |
| `issue.event_log` | list | Full event history (dispatches, results, transitions, blocks) |
| `issue.decomposed_from` | str or None | Parent issue ID |
| `issue.depends_on` | list[str] | Dependency issue IDs |
| `issue.children` | list[dict] | Resolved child issues with `issue_id`, `fields`, `state`, `event_log` |
| `result_format` | dict | Schema the worker must produce |
| `result_path` | str | Absolute path to write result JSON |

### Template Example

```markdown
You are implementing a task.

## Task
**{{ issue.fields.title }}**
{{ issue.fields.description }}

{% if issue.event_log %}
## Event History
{% for entry in issue.event_log %}
- [{{ entry.type }}] {{ entry.state }}: {{ entry.data }}
{% endfor %}
{% endif %}

## Output
Write your result as JSON to `{{ result_path }}` with this schema:
{% for field_name, field_def in result_format.items() %}
- `{{ field_name }}`: {{ field_def.description }}
{% endfor %}
```

### Design Decisions

- Templates are plain `.md` files with Jinja2 syntax — no special extension required.
- `FileSystemLoader` rooted at repo root, so `prompt: prompts/impl.md` resolves relative to repo.
- Rendering errors (missing template, syntax error) surface as `WorkerFailure`.
- No auto-escaping (markdown context, not HTML).
- Context passes through `effect.issue` directly — templates see whatever fields the engine provides.

## Persistence

### `persistence.py`

```python
class Persistence:
    def __init__(self, repo_root: Path, branch_name: str):
        self.state_path = repo_root / ".orca" / "runs" / branch_name / "state.json"

    def save(self, state: State) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state.to_dict(), indent=2))
        tmp.rename(self.state_path)

    def load(self) -> State | None:
        if not self.state_path.exists():
            return None
        return State.from_dict(json.loads(self.state_path.read_text()))

    def exists(self) -> bool:
        return self.state_path.exists()
```

### Design Decisions

- Atomic writes via temp file + rename — no corrupted state on crash.
- Uses existing `State.to_dict()` / `State.from_dict()` (already tested).
- State saved after every `reduce()` call — crash recovery loses at most one in-flight worker result (worker re-runs on resume).
- `.orca/` directory should be in `.gitignore`.

## Data Flow Summary

```
orca run task.md my-feature
  │
  ├─ parse task.md → title + description
  ├─ load orca.yml → StateMachineConfig
  ├─ git branch my-feature + worktree at .orca/worktrees/my-feature/
  ├─ CreateEvent → reduce(config, state, event, generate_id, now) → State + [DispatchWorkerEffect]
  ├─ save state to .orca/runs/my-feature/state.json
  │
  └─ Orchestrator.run()
       │
       loop:
       ├─ DispatchWorkerEffect received
       │   ├─ WorktreeManager.create() → .orca/worktrees/my-feature/db/
       │   ├─ render_prompt(template, issue, result_format, result_path)
       │   ├─ spawn: claude --print --output-format stream-json < prompt
       │   │   ├─ stream → .orca/sessions/implementing-2026-03-22T10-35-00.jsonl
       │   │   └─ worker writes → .orca/result.json
       │   ├─ validate result against result_format
       │   └─ WorkerSuccess or WorkerFailure
       │
       ├─ WorkerResultEvent or WorkerFailedEvent
       │   └─ reduce(config, state, event, generate_id, now) → (new_state, new_effects)
       │       └─ persist new_state
       │
       └─ root issue terminal? → done
```
