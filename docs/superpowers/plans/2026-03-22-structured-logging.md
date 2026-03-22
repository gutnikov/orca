# Structured Logging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add JSONL structured logging so orca runs produce a machine-readable log file at `.orca/runs/{branch}/orca.log.jsonl`.

**Architecture:** A `JSONFormatter` and `setup_logging()` function in a new `log.py` module. Configured once in `runner.py` at startup. All orchestrator modules use stdlib `logging.getLogger(__name__)` with structured `extra={}` fields. Logs go to file only (not stderr/stdout).

**Tech Stack:** Python 3.12 stdlib `logging`, `json`

**Spec:** `docs/superpowers/specs/2026-03-22-structured-logging-design.md`

---

## File Structure

| File | Responsibility |
|------|---------------|
| Create: `src/orca/orchestrator/log.py` | `JSONFormatter` and `setup_logging()` |
| Create: `tests/orchestrator/test_log.py` | Tests for formatter and setup |
| Modify: `src/orca/orchestrator/runner.py` | Call `setup_logging()`, add lifecycle logs |
| Modify: `src/orca/orchestrator/orchestrator.py` | Add structured log calls with `extra={}` |
| Modify: `src/orca/orchestrator/worker.py` | Add DEBUG subprocess logs |

**Note:** Module named `log.py` (not `logging.py`) to avoid shadowing stdlib `logging`.

---

### Task 1: JSONFormatter and setup_logging

**Files:**
- Create: `src/orca/orchestrator/log.py`
- Create: `tests/orchestrator/test_log.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/orchestrator/test_log.py
from __future__ import annotations

import json
import logging
from pathlib import Path

from orca.orchestrator.log import JSONFormatter, setup_logging


class TestJSONFormatter:
    def test_formats_basic_record(self) -> None:
        """Format a log record as a single JSON line with standard fields."""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="orca.test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Hello %s",
            args=("world",),
            exc_info=None,
        )

        result = json.loads(formatter.format(record))

        assert result["level"] == "INFO"
        assert result["logger"] == "orca.test"
        assert result["message"] == "Hello world"
        assert "timestamp" in result

    def test_includes_extra_fields(self) -> None:
        """Extra fields from the log call appear in the JSON output."""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="orca.test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="test",
            args=(),
            exc_info=None,
        )
        record.event = "worker_dispatched"  # type: ignore[attr-defined]
        record.issue_id = "abc-123"  # type: ignore[attr-defined]

        result = json.loads(formatter.format(record))

        assert result["event"] == "worker_dispatched"
        assert result["issue_id"] == "abc-123"

    def test_excludes_standard_log_record_attrs(self) -> None:
        """Standard LogRecord attributes do not leak into the JSON output."""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="orca.test",
            level=logging.INFO,
            pathname="/some/path.py",
            lineno=42,
            msg="test",
            args=(),
            exc_info=None,
        )

        result = json.loads(formatter.format(record))

        assert "pathname" not in result
        assert "lineno" not in result
        assert "args" not in result
        assert "msg" not in result

    def test_output_is_single_line(self) -> None:
        """Output must be a single line (no embedded newlines)."""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="orca.test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="line1\nline2",
            args=(),
            exc_info=None,
        )

        output = formatter.format(record)

        assert "\n" not in output


class TestSetupLogging:
    def test_creates_log_file(self, tmp_path: Path) -> None:
        """setup_logging creates the log file and writes JSON lines."""
        log_path = tmp_path / "runs" / "main" / "orca.log.jsonl"
        setup_logging(log_path)

        test_logger = logging.getLogger("orca.test.setup")
        test_logger.info("test message", extra={"event": "test_event"})

        # Flush handler
        for handler in logging.getLogger("orca").handlers:
            handler.flush()

        lines = log_path.read_text().strip().split("\n")
        assert len(lines) == 1

        entry = json.loads(lines[0])
        assert entry["message"] == "test message"
        assert entry["event"] == "test_event"
        assert entry["level"] == "INFO"

    def test_does_not_propagate(self, tmp_path: Path) -> None:
        """The orca logger should not propagate to root logger."""
        log_path = tmp_path / "runs" / "main" / "orca.log.jsonl"
        setup_logging(log_path)

        orca_logger = logging.getLogger("orca")
        assert orca_logger.propagate is False

    def teardown_method(self) -> None:
        """Clean up handlers added by setup_logging."""
        orca_logger = logging.getLogger("orca")
        for handler in orca_logger.handlers[:]:
            handler.close()
            orca_logger.removeHandler(handler)
        orca_logger.setLevel(logging.WARNING)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/orchestrator/test_log.py -v`
Expected: FAIL — `ImportError: cannot import name 'JSONFormatter'`

- [ ] **Step 3: Implement JSONFormatter and setup_logging**

```python
# src/orca/orchestrator/log.py
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

_STANDARD_LOG_RECORD_ATTRS = frozenset(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys()
)


class JSONFormatter(logging.Formatter):
    """Format log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_LOG_RECORD_ATTRS and key not in entry:
                entry[key] = value
        return json.dumps(entry, default=str)


def setup_logging(log_path: Path, level: int = logging.DEBUG) -> None:
    """Configure the 'orca' logger to write JSONL to a file."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(log_path)
    handler.setFormatter(JSONFormatter())
    orca_logger = logging.getLogger("orca")
    orca_logger.setLevel(level)
    orca_logger.addHandler(handler)
    orca_logger.propagate = False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/orchestrator/test_log.py -v`
Expected: PASS

- [ ] **Step 5: Run linter and type checker**

Run: `uv run ruff check . && uv run mypy src/orca/orchestrator/log.py`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/orca/orchestrator/log.py tests/orchestrator/test_log.py
git commit -m "feat: add JSONFormatter and setup_logging for structured JSONL logging"
```

---

### Task 2: Add logging to runner.py

**Files:**
- Modify: `src/orca/orchestrator/runner.py`

Add `setup_logging()` call early in `run()`, plus lifecycle log events (run started/resumed/completed/failed). Wrap `orchestrator.run()` in a try/except for the failure case.

- [ ] **Step 1: Add imports**

Add to the imports section of `runner.py`:

```python
import logging

from orca.orchestrator.log import setup_logging
```

Add module-level logger after imports:

```python
logger = logging.getLogger(__name__)
```

- [ ] **Step 2: Add setup_logging call**

Inside `run()`, after `worktree_mgr` is created (after line 137), add:

```python
    log_path = repo_root / ".orca" / "runs" / branch_name / "orca.log.jsonl"
    setup_logging(log_path)
```

- [ ] **Step 3: Add lifecycle log events**

In the resume branch (after `branches.load()`, around line 147), add:

```python
    logger.info(
        "Run resumed",
        extra={"event": "run_resumed", "branch": branch_name},
    )
```

In the fresh-start branch (after `persistence.save(state)`, around line 183), add:

```python
    logger.info(
        "Run started",
        extra={
            "event": "run_started",
            "branch": branch_name,
            "task_file": str(task_file),
            "root_issue_id": root_issue_id,
        },
    )
```

Replace the bare `await orchestrator.run(...)` call with:

```python
    try:
        await orchestrator.run(root_issue_id, initial_effects)
    except Exception:
        logger.error(
            "Run failed",
            extra={"event": "run_failed", "branch": branch_name},
            exc_info=True,
        )
        raise

    logger.info(
        "Run completed",
        extra={"event": "run_completed", "branch": branch_name, "root_issue_id": root_issue_id},
    )
```

- [ ] **Step 4: Run all tests**

Run: `uv run pytest tests/ -v`
Expected: PASS

- [ ] **Step 5: Run linter and type checker**

Run: `uv run ruff check . && uv run mypy src/`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/orca/orchestrator/runner.py
git commit -m "feat: add structured logging setup and lifecycle events to runner"
```

---

### Task 3: Add structured logging to orchestrator.py

**Files:**
- Modify: `src/orca/orchestrator/orchestrator.py`

Add `extra={}` with `event` field to existing log calls. Add new log calls for worker dispatch, completion, state transitions, and decomposition detection.

- [ ] **Step 1: Update existing log calls with event extra**

Replace the four existing log calls with versions that include `extra`:

```python
# _spawn_worker — no worker definition
logger.warning(
    "No worker definition for state %r — skipping dispatch",
    effect.state,
    extra={"event": "no_worker_definition", "state": effect.state},
)

# _spawn_worker — unknown worker kind
logger.warning(
    "Unknown worker kind %r — skipping dispatch",
    worker_kind,
    extra={"event": "unknown_worker_kind", "worker_kind": worker_kind},
)

# _route_effects — error effect
logger.error(
    "ErrorEffect for issue %r: %s",
    effect.issue_id,
    effect.message,
    extra={"event": "error_effect", "issue_id": effect.issue_id, "error": effect.message},
)

# run — deadlock
logger.warning(
    "Deadlock detected: no tasks in flight and no pending effects. Stopping.",
    extra={"event": "deadlock_detected"},
)
```

- [ ] **Step 2: Add worker dispatch log**

In `_spawn_worker()`, after `self._in_flight[task] = effect.issue_id`:

```python
        logger.info(
            "Worker dispatched for issue %s in state %s",
            effect.issue_id,
            effect.state,
            extra={
                "event": "worker_dispatched",
                "issue_id": effect.issue_id,
                "state": effect.state,
                "worker_kind": worker_kind,
            },
        )
```

- [ ] **Step 3: Add state-diffing and completion logs**

In the `for task in done:` loop, capture old state before `reduce()`, then log after:

Before the `self.state, new_effects = reduce(...)` call, add:

```python
                old_issues = set(self.state.issues.keys())
                old_issue_state = self.state.issues[issue_id].state if issue_id in self.state.issues else None
```

After `self.persistence.save(self.state)`, add:

```python
                # Log worker outcome
                if isinstance(outcome, WorkerSuccess):
                    logger.info(
                        "Worker succeeded for issue %s",
                        issue_id,
                        extra={
                            "event": "worker_succeeded",
                            "issue_id": issue_id,
                            "result_outcome": outcome.result.get("outcome"),
                        },
                    )
                else:
                    logger.warning(
                        "Worker failed for issue %s: %s",
                        issue_id,
                        outcome.error,
                        extra={"event": "worker_failed", "issue_id": issue_id, "error": outcome.error},
                    )

                # Detect state transition
                new_issue_state = self.state.issues[issue_id].state if issue_id in self.state.issues else None
                if old_issue_state and new_issue_state and old_issue_state != new_issue_state:
                    logger.info(
                        "Issue %s transitioned from %s to %s",
                        issue_id,
                        old_issue_state,
                        new_issue_state,
                        extra={
                            "event": "state_transitioned",
                            "issue_id": issue_id,
                            "from_state": old_issue_state,
                            "to_state": new_issue_state,
                        },
                    )

                # Detect new issues (decomposition)
                new_issues = set(self.state.issues.keys()) - old_issues
                for new_id in new_issues:
                    new_issue = self.state.issues[new_id]
                    logger.info(
                        "Issue %s created: %s",
                        new_id,
                        new_issue.fields.get("title", ""),
                        extra={
                            "event": "issue_created",
                            "issue_id": new_id,
                            "parent_id": new_issue.decomposed_from,
                            "title": new_issue.fields.get("title", ""),
                        },
                    )
```

- [ ] **Step 4: Run all tests**

Run: `uv run pytest tests/ -v`
Expected: PASS

- [ ] **Step 5: Run linter and type checker**

Run: `uv run ruff check . && uv run mypy src/`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/orca/orchestrator/orchestrator.py
git commit -m "feat: add structured log events to orchestrator"
```

---

### Task 4: Add DEBUG logging to worker.py

**Files:**
- Modify: `src/orca/orchestrator/worker.py`

Add two DEBUG log calls: subprocess started and subprocess exited.

- [ ] **Step 1: Add logger and log calls**

Add import and logger at top of `worker.py`:

```python
import logging

logger = logging.getLogger(__name__)
```

After `proc = await asyncio.create_subprocess_exec(...)` (after line 78):

```python
        logger.debug(
            "Subprocess started for issue %s",
            effect.issue_id,
            extra={
                "event": "subprocess_started",
                "issue_id": effect.issue_id,
                "state": effect.state,
                "pid": proc.pid,
                "workdir": str(workdir),
            },
        )
```

After `await proc.wait()` (after line 91):

```python
        logger.debug(
            "Subprocess exited for issue %s with code %s",
            effect.issue_id,
            proc.returncode,
            extra={
                "event": "subprocess_exited",
                "issue_id": effect.issue_id,
                "state": effect.state,
                "pid": proc.pid,
                "returncode": proc.returncode,
            },
        )
```

- [ ] **Step 2: Run all tests**

Run: `uv run pytest tests/ -v`
Expected: PASS

- [ ] **Step 3: Run linter and type checker**

Run: `uv run ruff check . && uv run mypy src/`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/orca/orchestrator/worker.py
git commit -m "feat: add DEBUG subprocess logging to worker"
```

---

### Task 5: Update orchestrator exports

**Files:**
- Modify: `src/orca/orchestrator/__init__.py`

- [ ] **Step 1: Add log module exports**

Add to `__init__.py` imports:

```python
from orca.orchestrator.log import JSONFormatter, setup_logging
```

Add `"JSONFormatter"` and `"setup_logging"` to `__all__`.

- [ ] **Step 2: Run type checker**

Run: `uv run mypy src/orca/orchestrator/`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add src/orca/orchestrator/__init__.py
git commit -m "chore: export JSONFormatter and setup_logging from orchestrator"
```
