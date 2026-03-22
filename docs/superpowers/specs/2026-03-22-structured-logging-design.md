# Structured Logging Design

## Overview

Add JSONL structured logging to the orca orchestrator so users can observe what's happening during a run. Each log entry is a single JSON line written to `.orca/runs/{branch}/orca.log.jsonl`. Uses Python stdlib `logging` with a custom `JSONFormatter` — no new dependencies.

## Log Entry Format

Every log entry is a JSON object on one line:

```json
{"timestamp": "2026-03-22T15:30:01.123Z", "level": "INFO", "logger": "orca.orchestrator.orchestrator", "message": "Worker dispatched", "event": "worker_dispatched", "issue_id": "abc-123", "state": "implementing"}
```

**Standard fields:**

| Field | Type | Description |
|-------|------|-------------|
| `timestamp` | string | ISO 8601 with milliseconds, UTC |
| `level` | string | DEBUG, INFO, WARNING, ERROR |
| `logger` | string | Python logger name (e.g., `orca.orchestrator.worker`) |
| `message` | string | Human-readable description |

**Extra fields** are merged into the top-level JSON object from the `extra={}` kwarg on each log call. Common extras: `event`, `issue_id`, `state`, `branch`, `error`.

## New Module: `src/orca/orchestrator/logging.py`

### `JSONFormatter`

A `logging.Formatter` subclass that outputs one JSON line per record:

```python
class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Merge extra fields (skip standard LogRecord attributes)
        for key, value in record.__dict__.items():
            if key not in _STANDARD_LOG_RECORD_ATTRS and key not in entry:
                entry[key] = value
        return json.dumps(entry)
```

`_STANDARD_LOG_RECORD_ATTRS` is built dynamically from a dummy `LogRecord` to stay compatible across Python versions:

```python
_STANDARD_LOG_RECORD_ATTRS = frozenset(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys()
)
```

### `setup_logging(log_path: Path, level: int = logging.DEBUG) -> None`

Configures the `"orca"` root logger:

1. Create parent directories for `log_path`.
2. Attach a `FileHandler` (mode `"a"` — append, supports crash recovery resume) with `JSONFormatter` to the `"orca"` logger.
3. Set level to `DEBUG` (capture everything; filter by level when reading).
4. Set `propagate = False` to prevent log records from flowing to the root logger (avoids duplicate output if someone calls `basicConfig()` elsewhere).
5. Called once from `runner.py` at startup.

```python
def setup_logging(log_path: Path, level: int = logging.DEBUG) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(log_path)
    handler.setFormatter(JSONFormatter())
    orca_logger = logging.getLogger("orca")
    orca_logger.setLevel(level)
    orca_logger.addHandler(handler)
    orca_logger.propagate = False
```

## Log Points

### `runner.py`

A `try/except` block must be added around `orchestrator.run()` to catch and log failures — this is net-new control flow, not an existing handler.

| Event | Level | Extra fields | When |
|-------|-------|-------------|------|
| Run started | INFO | `event`, `branch`, `task_file`, `root_issue_id` | After state init, before orchestrator.run() |
| Run resumed | INFO | `event`, `branch`, `root_issue_id` | In crash-recovery path, after loading persisted state |
| Run completed | INFO | `event`, `branch`, `root_issue_id` | After orchestrator.run() returns |
| Run failed | ERROR | `event`, `branch`, `error` | In new try/except wrapping orchestrator.run() |

### `orchestrator.py`

**Detecting state transitions and new issues:** The orchestrator must diff state before and after `reduce()`:
- **State transitions:** Compare `old_state.issues[issue_id].state` vs `new_state.issues[issue_id].state` for the issue referenced in the event. Log when they differ.
- **New issues (decomposition):** Compare `old_state.issues.keys()` vs `new_state.issues.keys()`. Any new keys represent child issues created by decomposition.

| Event | Level | Extra fields | When |
|-------|-------|-------------|------|
| Worker dispatched | INFO | `event`, `issue_id`, `state`, `worker_kind` | In `_spawn_worker()` after creating asyncio task |
| Worker succeeded | INFO | `event`, `issue_id`, `state`, `result_outcome` | After receiving `WorkerSuccess` |
| Worker failed | WARNING | `event`, `issue_id`, `state`, `error` | After receiving `WorkerFailure` |
| State transitioned | INFO | `event`, `issue_id`, `from_state`, `to_state` | After reduce(), when issue state differs |
| Issue created | INFO | `event`, `issue_id`, `parent_id`, `title` | After reduce(), for each new issue key in state |
| Deadlock detected | ERROR | `event` | Existing log point, add `event` extra |
| No worker definition | WARNING | `event`, `state` | Existing log point, add `event` extra |
| Unknown worker kind | WARNING | `event`, `worker_kind` | Existing log point, add `event` extra |

### `worker.py`

| Event | Level | Extra fields | When |
|-------|-------|-------------|------|
| Subprocess started | DEBUG | `event`, `issue_id`, `state`, `pid`, `workdir` | After `create_subprocess_exec` |
| Subprocess exited | DEBUG | `event`, `issue_id`, `state`, `pid`, `returncode` | After `proc.communicate()` |

### `session_sync.py`

Existing log calls are kept as-is. They already use `logger.info/warning/exception` and will automatically appear in the JSONL output once `setup_logging()` is called. Note: these existing calls do not include `extra={"event": ...}` so they won't be filterable by event type — this is acceptable for now.

## Changes to Existing Modules

### `runner.py`

Add `setup_logging()` call early in `run()`:

```python
from orca.orchestrator.logging import setup_logging

log_path = repo_root / ".orca" / "runs" / branch_name / "orca.log.jsonl"
setup_logging(log_path)
```

Add `logger = logging.getLogger(__name__)` and log calls for run lifecycle. Add `try/except` around `orchestrator.run()` for the run-failed event.

### `orchestrator.py`

Add `extra={}` with `event` field to existing log calls. Add new log calls for worker dispatch, completion, state transitions, and decomposition. Add state-diffing logic after `reduce()` calls.

### `worker.py`

Add `logger = logging.getLogger(__name__)` and two DEBUG log calls for subprocess start/exit.

## Log File Location

```
.orca/runs/{branch}/orca.log.jsonl
```

Alongside the existing `state.json` and `branches.json`. One log file per run. FileHandler uses append mode — the file grows across crash-recovery resumes.

## Reading Logs

```bash
# Watch live
tail -f .orca/runs/my-feature/orca.log.jsonl | jq .

# Filter by level
cat .orca/runs/my-feature/orca.log.jsonl | jq 'select(.level == "ERROR")'

# Filter by event type
cat .orca/runs/my-feature/orca.log.jsonl | jq 'select(.event == "worker_dispatched")'

# Filter by issue
cat .orca/runs/my-feature/orca.log.jsonl | jq 'select(.issue_id == "abc-123")'
```

## What This Does NOT Include

- **Console output** — logs go only to file, not stderr/stdout.
- **Log rotation** — single file per run, no size limits.
- **Remote log shipping** — local files only.
- **Engine logging** — the engine is pure and does no I/O; logging stays in the orchestrator layer.
