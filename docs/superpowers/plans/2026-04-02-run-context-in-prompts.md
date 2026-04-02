# Run Context in Worker Prompts — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose a `run` Jinja2 variable in worker prompt templates containing a file map, session list, summary, and format descriptions so workflow authors can build retro/post-mortem steps.

**Architecture:** Add `build_run_context()` in dispatch.py to build the dict from State + SessionManifest + run_dir. Thread it through worker.execute() → render_prompt() → Jinja2 context. No engine/reducer changes needed.

**Tech Stack:** Python 3.12, dataclasses, Jinja2, pytest

---

### Task 1: Add `build_run_context()` function

**Files:**
- Modify: `src/orca/engine/dispatch.py`
- Test: `tests/engine/test_dispatch.py`

- [ ] **Step 1: Write the failing test**

In `tests/engine/test_dispatch.py`, add at the bottom:

```python
from pathlib import Path

from orca.engine.dispatch import build_run_context


class TestBuildRunContext:
    def test_file_map(self, tmp_path: Path) -> None:
        run_dir = tmp_path / ".orca" / "runs" / "my-branch" / "prd"
        run_dir.mkdir(parents=True)
        (run_dir / "orca.log.jsonl").touch()
        (run_dir / "state.json").touch()
        sessions_dir = tmp_path / ".orca" / "sessions"
        sessions_dir.mkdir(parents=True)

        issue = Issue(
            type="default",
            fields={"title": "test"},
            state="work",
            worker_active=False,
            decomposed_from=None,
            depends_on=[],
            event_log=[],
            visit_counts={"work": 1},
        )
        state = State(issues={"i1": issue}, worker_queues={})

        ctx = build_run_context(
            state=state,
            run_dir=run_dir,
            sessions_dir=sessions_dir,
            sessions=[],
            branch="my-branch",
            workflow="prd",
        )

        assert ctx["run_dir"] == str(run_dir)
        assert ctx["log"] == str(run_dir / "orca.log.jsonl")
        assert ctx["state"] == str(run_dir / "state.json")
        assert ctx["sessions_dir"] == str(sessions_dir)
        assert ctx["branch"] == "my-branch"
        assert ctx["workflow"] == "prd"
        assert ctx["insights"] is None  # no insights.json file

    def test_insights_path_when_present(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        (run_dir / "insights.json").touch()
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()

        state = State(issues={}, worker_queues={})

        ctx = build_run_context(
            state=state,
            run_dir=run_dir,
            sessions_dir=sessions_dir,
            sessions=[],
            branch="b",
            workflow="w",
        )

        assert ctx["insights"] == str(run_dir / "insights.json")

    def test_sessions_list(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()

        sessions = [
            {
                "state": "generate_prd",
                "log_path": "/logs/generate_prd-20260402.log",
                "started_at": "2026-04-02T06:00:00+00:00",
                "completed_at": "2026-04-02T06:06:14+00:00",
            },
            {
                "state": "territory_map",
                "log_path": "/logs/territory_map-20260402.log",
                "started_at": "2026-04-02T06:06:14+00:00",
                "completed_at": "2026-04-02T06:08:06+00:00",
            },
        ]

        state = State(issues={}, worker_queues={})

        ctx = build_run_context(
            state=state,
            run_dir=run_dir,
            sessions_dir=sessions_dir,
            sessions=sessions,
            branch="b",
            workflow="w",
        )

        assert len(ctx["sessions"]) == 2
        assert ctx["sessions"][0]["state"] == "generate_prd"
        assert ctx["sessions"][0]["log"] == "/logs/generate_prd-20260402.log"
        assert ctx["sessions"][0]["duration"] == "6m 14s"
        assert ctx["sessions"][1]["state"] == "territory_map"
        assert ctx["sessions"][1]["duration"] == "1m 52s"

    def test_summary_from_event_log(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()

        issue = Issue(
            type="default",
            fields={"title": "test"},
            state="recon_prd",
            worker_active=False,
            decomposed_from=None,
            depends_on=[],
            event_log=[
                EventLogEntry(timestamp="t0", type="created", data={"state": "generate_prd"}),
                EventLogEntry(timestamp="t1", type="worker_result", data={"outcome": "complete"}),
                EventLogEntry(timestamp="t2", type="transitioned", data={"from": "generate_prd", "to": "recon_prd"}),
                EventLogEntry(timestamp="t3", type="worker_failed", data={"state": "recon_prd", "error": "MCP down"}),
            ],
            visit_counts={"generate_prd": 1, "recon_prd": 1},
        )
        state = State(issues={"i1": issue}, worker_queues={})

        ctx = build_run_context(
            state=state,
            run_dir=run_dir,
            sessions_dir=sessions_dir,
            sessions=[
                {
                    "state": "generate_prd",
                    "started_at": "2026-04-02T06:00:00+00:00",
                    "completed_at": "2026-04-02T06:10:00+00:00",
                },
            ],
            branch="b",
            workflow="w",
        )

        summary = ctx["summary"]
        assert "generate_prd" in summary["states_visited"]
        assert "recon_prd" in summary["states_visited"]
        assert summary["current_state"] == "recon_prd"
        assert summary["outcomes"]["generate_prd"] == "complete"
        assert "recon_prd" in summary["failures"]
        assert "MCP down" in summary["failures"]["recon_prd"]

    def test_formats_present(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()

        state = State(issues={}, worker_queues={})

        ctx = build_run_context(
            state=state,
            run_dir=run_dir,
            sessions_dir=sessions_dir,
            sessions=[],
            branch="b",
            workflow="w",
        )

        assert "log" in ctx["formats"]
        assert "insights" in ctx["formats"]
        assert "state" in ctx["formats"]
        assert "sessions" in ctx["formats"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/engine/test_dispatch.py::TestBuildRunContext -v`
Expected: FAIL — `build_run_context` doesn't exist

- [ ] **Step 3: Implement `build_run_context`**

In `src/orca/engine/dispatch.py`, add at the bottom of the file:

```python
from pathlib import Path


def _format_duration(started_at: str, completed_at: str) -> str:
    """Format duration between two ISO timestamps as human-readable string."""
    from datetime import datetime

    try:
        start = datetime.fromisoformat(started_at)
        end = datetime.fromisoformat(completed_at)
        total = int((end - start).total_seconds())
        if total < 0:
            total = 0
        minutes, seconds = divmod(total, 60)
        if minutes > 0:
            return f"{minutes}m {seconds:02d}s"
        return f"{seconds}s"
    except (ValueError, TypeError):
        return ""


def build_run_context(
    state: State,
    run_dir: Path,
    sessions_dir: Path,
    sessions: list[dict[str, Any]],
    branch: str,
    workflow: str,
) -> dict[str, Any]:
    """Build the run context dict for Jinja2 templates.

    Provides a file map, session list, summary, and format descriptions
    so prompt templates can give workers visibility into the full run.
    """
    # File map
    insights_path = run_dir / "insights.json"
    ctx: dict[str, Any] = {
        "run_dir": str(run_dir),
        "log": str(run_dir / "orca.log.jsonl"),
        "insights": str(insights_path) if insights_path.exists() else None,
        "state": str(run_dir / "state.json"),
        "sessions_dir": str(sessions_dir),
        "branch": branch,
        "workflow": workflow,
    }

    # Sessions list
    ctx["sessions"] = []
    for s in sessions:
        entry: dict[str, Any] = {"state": s.get("state", "")}
        entry["log"] = s.get("log_path", "")
        started = s.get("started_at", "")
        completed = s.get("completed_at", "")
        entry["duration"] = _format_duration(started, completed) if completed else ""
        # Extract outcome from the session's event context
        entry["outcome"] = s.get("outcome", "")
        ctx["sessions"].append(entry)

    # Summary — built from root issue's event log
    states_visited: list[str] = []
    current_state = ""
    outcomes: dict[str, str] = {}
    failures: dict[str, str] = {}
    first_started = ""
    last_completed = ""

    for issue in state.issues.values():
        current_state = issue.state
        states_visited = list(issue.visit_counts.keys())
        for entry in issue.event_log:
            if entry.type == "worker_result":
                state_name = _last_state_before_result(issue.event_log, entry)
                if state_name and entry.data.get("outcome"):
                    outcomes[state_name] = entry.data["outcome"]
            elif entry.type == "worker_failed":
                state_name = entry.data.get("state", "")
                error = entry.data.get("error", "unknown error")
                if state_name:
                    failures[state_name] = error

    # Total duration from sessions
    total_duration = ""
    if sessions:
        starts = [s.get("started_at", "") for s in sessions if s.get("started_at")]
        ends = [s.get("completed_at", "") for s in sessions if s.get("completed_at")]
        if starts and ends:
            total_duration = _format_duration(min(starts), max(ends))

    ctx["summary"] = {
        "states_visited": states_visited,
        "current_state": current_state,
        "outcomes": outcomes,
        "failures": failures,
        "total_duration": total_duration,
    }

    # Format descriptions
    ctx["formats"] = {
        "log": "JSONL, one event per line: {timestamp, level, logger, message, event, ...}",
        "insights": "JSON array of {timestamp, severity, title, detail, remediation}",
        "state": "JSON snapshot of all issues: {issues: {id: {type, fields, state, event_log, ...}}}",
        "sessions": "Plain text terminal scrollback from each worker session",
    }

    return ctx


def _last_state_before_result(event_log: list[EventLogEntry], result_entry: EventLogEntry) -> str:
    """Find the state name for a worker_result by looking at the preceding worker_dispatched entry."""
    last_state = ""
    for entry in event_log:
        if entry is result_entry:
            break
        if entry.type == "worker_dispatched":
            last_state = entry.data.get("state", "")
    return last_state
```

Add `from pathlib import Path` to the imports at the top of `dispatch.py` (if not already present).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/engine/test_dispatch.py::TestBuildRunContext -v`
Expected: PASS

- [ ] **Step 5: Run all engine tests**

Run: `uv run pytest tests/engine/ -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/orca/engine/dispatch.py tests/engine/test_dispatch.py
git commit -m "feat(engine): add build_run_context for worker prompt templates"
```

---

### Task 2: Thread run context through render_prompt and worker.execute

**Files:**
- Modify: `src/orca/orchestrator/template.py:46-89`
- Modify: `src/orca/orchestrator/worker.py:120-148`

- [ ] **Step 1: Update `render_prompt` to accept `run` parameter**

In `src/orca/orchestrator/template.py`, update the `render_prompt` function signature and context:

```python
def render_prompt(
    template_path: Path,
    repo_root: Path,
    issue: dict[str, Any],
    result_format: dict[str, Any],
    result_path: Path,
    *,
    progress: bool = False,
    run: dict[str, Any] | None = None,
) -> str:
```

Update the context dict inside the function:

```python
    context = {
        "issue": issue,
        "result_format": result_format,
        "result_path": str(result_path),
        "run": run,
    }
```

- [ ] **Step 2: Update `worker.execute` to accept and pass `run` context**

In `src/orca/orchestrator/worker.py`, update the `execute` method signature to add `run_context`:

```python
    async def execute(
        self,
        effect: DispatchWorkerEffect,
        workdir: Path,
        result_path: Path,
        prompt_path: Path | None = None,
        inactivity_timeout: int | None = None,
        pty_session: PtySession | None = None,
        env: dict[str, str] | None = None,
        model: str | None = None,
        extra_args: list[str] | None = None,
        session_manifest: SessionManifest | None = None,
        session_id: str | None = None,
        run_context: dict[str, Any] | None = None,
    ) -> WorkerOutcome:
```

Add `from typing import Any` to imports if not present.

Update the `render_prompt` call inside `execute`:

```python
        if prompt_path is not None:
            prompt = render_prompt(
                prompt_path,
                self._repo_root,
                effect.issue,
                effect.result_format,
                result_path,
                progress=effect.progress_enabled,
                run=run_context,
            )
```

- [ ] **Step 3: Run linting and type checking**

Run: `uv run ruff check src/orca/orchestrator/template.py src/orca/orchestrator/worker.py && uv run mypy src/orca/orchestrator/template.py src/orca/orchestrator/worker.py`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/orca/orchestrator/template.py src/orca/orchestrator/worker.py
git commit -m "feat(orchestrator): thread run context through render_prompt and worker"
```

---

### Task 3: Build and pass run context from the orchestrator

**Files:**
- Modify: `src/orca/orchestrator/orchestrator.py` (dispatch worker method, around line 460-525)

- [ ] **Step 1: Import `build_run_context`**

Add to the imports in `orchestrator.py`:

```python
from orca.engine.dispatch import build_run_context
```

- [ ] **Step 2: Build run context before worker.execute call**

In the dispatch worker method (the one containing `await worker.execute(...)`, around line 512), add run context building just before the `try` block:

```python
        # Build run context for prompt templates
        run_context: dict[str, Any] | None = None
        if self.repo_root is not None and self._session_sync is not None:
            run_dir = self.persistence.state_path.parent
            sessions_dir = self.repo_root / ".orca" / "sessions"
            run_context = build_run_context(
                state=self._state,
                run_dir=run_dir,
                sessions_dir=sessions_dir,
                sessions=self._session_sync.manifest.read(),
                branch=self.root_branch,
                workflow=run_dir.name,
            )
```

- [ ] **Step 3: Pass run_context to worker.execute**

Update the `worker.execute(...)` call to include `run_context`:

```python
            outcome = await worker.execute(
                enriched_effect,
                workdir,
                result_path,
                prompt_path,
                inactivity_timeout,
                pty_session=tmux_session,
                env=worker_env,
                model=model,
                extra_args=list(extra_args) if extra_args else None,
                session_manifest=self._session_sync.manifest if self._session_sync else None,
                session_id=tracking_id,
                run_context=run_context,
            )
```

- [ ] **Step 4: Run linting and type checking**

Run: `uv run ruff check src/orca/orchestrator/orchestrator.py && uv run mypy src/orca/orchestrator/orchestrator.py`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest tests/ -q`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add src/orca/orchestrator/orchestrator.py
git commit -m "feat(orchestrator): build and pass run context to worker prompts"
```
