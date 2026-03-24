# Insights Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an observational sidecar agent that periodically monitors workflow progress, surfaces errors/patterns, and writes findings to `insights.md`.

**Architecture:** A new `execute_raw()` method on `ClaudeCodeWorker` bypasses the issue-specific pipeline. The orchestrator runs an `_insights_loop()` coroutine (like `_sync_sessions_loop()`) that spawns insights workers on a 90s interval. The TUI shows an "Insights" root node that displays `insights.md` in the detail panel.

**Tech Stack:** Python 3.12, asyncio, Jinja2, Textual (TUI)

**Security note:** All subprocess spawning uses `asyncio.create_subprocess_exec` (not shell-based `create_subprocess_shell`), which prevents command injection. Prompt content is piped via stdin, never interpolated into shell commands.

---

## File Structure

| File | Responsibility |
|------|---------------|
| `src/orca/orchestrator/worker.py` | Add `execute_raw()` — pre-rendered prompt, no result.json validation |
| `src/orca/orchestrator/template.py` | Add `render_insights_prompt()` — insights-specific Jinja2 context |
| `src/orca/orchestrator/insights.py` | New. Gather state/transcripts, manage byte offsets, call worker |
| `src/orca/orchestrator/orchestrator.py` | Add `_insights_loop()`, wire into `run()` |
| `src/orca/orchestrator/runner.py` | Add `--insights` CLI flag, plumb to orchestrator |
| `src/orca/orchestrator/prompts/insights.md.j2` | New. Insights prompt template |
| `src/orca/tui/messages.py` | Add `InsightsSelected` message |
| `src/orca/tui/widgets/issue_tree.py` | Add Insights root node + session leaves |
| `src/orca/tui/widgets/issue_detail.py` | Handle `show_insights()` |
| `src/orca/tui/app.py` | Handle `InsightsSelected`, pass `run_dir` for insights.md |
| `tests/orchestrator/test_worker.py` | Tests for `execute_raw()` |
| `tests/orchestrator/test_insights.py` | New. Tests for insights gathering logic |
| `tests/orchestrator/test_orchestrator.py` | Tests for insights loop integration |

---

### Task 1: Add `execute_raw()` to `ClaudeCodeWorker`

**Files:**
- Modify: `src/orca/orchestrator/worker.py:43-154`
- Test: `tests/orchestrator/test_worker.py`

This method accepts a pre-rendered prompt string and session log path. It spawns the same Claude subprocess but does not read/validate result.json. Returns `WorkerSuccess(result={})` on exit 0, `WorkerFailure` on non-zero.

- [ ] **Step 1: Write the failing tests for `execute_raw()`**

Add to `tests/orchestrator/test_worker.py`:

```python
@pytest.mark.asyncio()
class TestClaudeCodeWorkerExecuteRaw:
    async def test_successful_raw_execution(self, tmp_path: Path) -> None:
        """exit code 0 -> WorkerSuccess with empty result dict."""
        proc = _make_mock_proc(0)
        session_log = tmp_path / "session.jsonl"

        with patch("orca.orchestrator.worker.asyncio.create_subprocess_exec", return_value=proc):
            worker = ClaudeCodeWorker(repo_root=tmp_path)
            outcome = await worker.execute_raw("analyze this", tmp_path, session_log)

        assert isinstance(outcome, WorkerSuccess)
        assert outcome.result == {}
        assert session_log.exists()

    async def test_raw_nonzero_exit(self, tmp_path: Path) -> None:
        """exit code 1 -> WorkerFailure."""
        proc = _make_mock_proc(1)
        session_log = tmp_path / "session.jsonl"

        with patch("orca.orchestrator.worker.asyncio.create_subprocess_exec", return_value=proc):
            worker = ClaudeCodeWorker(repo_root=tmp_path)
            outcome = await worker.execute_raw("analyze this", tmp_path, session_log)

        assert isinstance(outcome, WorkerFailure)
        assert "exit code" in outcome.error

    async def test_raw_extracts_session_id(self, tmp_path: Path) -> None:
        """Session ID extracted from first JSON line."""
        stdout_lines = [b'{"sessionId": "sess-abc"}\n', b'{"type": "assistant"}\n']
        proc = _make_mock_proc(0, stdout_lines=stdout_lines)
        session_log = tmp_path / "session.jsonl"

        with patch("orca.orchestrator.worker.asyncio.create_subprocess_exec", return_value=proc):
            worker = ClaudeCodeWorker(repo_root=tmp_path)
            outcome = await worker.execute_raw("analyze this", tmp_path, session_log)

        assert isinstance(outcome, WorkerSuccess)
        assert outcome.session_id == "sess-abc"

    async def test_raw_timeout(self, tmp_path: Path) -> None:
        """Worker killed after timeout -> WorkerFailure."""
        proc = MagicMock()
        proc.returncode = -9
        proc.stdout = AsyncLineIterator([])
        proc.stdin = MagicMock()
        proc.stdin.close = MagicMock()
        proc.kill = MagicMock()

        async def slow_wait() -> int:
            await asyncio.sleep(10)
            return 0

        proc.wait = slow_wait

        session_log = tmp_path / "session.jsonl"

        with patch("orca.orchestrator.worker.asyncio.create_subprocess_exec", return_value=proc):
            worker = ClaudeCodeWorker(repo_root=tmp_path)
            outcome = await worker.execute_raw("analyze", tmp_path, session_log, timeout=0.1)

        assert isinstance(outcome, WorkerFailure)
        assert "timeout" in outcome.error.lower() or "timed out" in outcome.error.lower()
```

Add `import asyncio` to the test file imports if not already present.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/orchestrator/test_worker.py::TestClaudeCodeWorkerExecuteRaw -v`
Expected: FAIL -- `execute_raw` does not exist yet.

- [ ] **Step 3: Implement `execute_raw()`**

Add this method to `ClaudeCodeWorker` in `src/orca/orchestrator/worker.py`, after the existing `execute()` method (after line 154). Uses `asyncio.create_subprocess_exec` (safe, no shell interpolation):

```python
    async def execute_raw(
        self,
        prompt: str,
        workdir: Path,
        session_log_path: Path,
        timeout: float | None = None,
    ) -> WorkerOutcome:
        """Run Claude with a pre-rendered prompt. No result.json parsing.

        Unlike execute(), this accepts a ready-to-use prompt string and does not
        read or validate a result file. Used for sidecar tasks like insights.

        Returns WorkerSuccess(result={}) on exit code 0, WorkerFailure otherwise.
        """
        session_log_path.parent.mkdir(parents=True, exist_ok=True)

        proc = await asyncio.create_subprocess_exec(
            "claude",
            "--print",
            "--output-format",
            "stream-json",
            "--verbose",
            "--max-turns",
            "50",
            "--permission-mode",
            "bypassPermissions",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            cwd=workdir,
            limit=1024 * 1024,
        )

        if proc.stdin is not None:
            proc.stdin.write(prompt.encode())
            proc.stdin.close()

        session_id: str | None = None
        with session_log_path.open("wb") as log_file:
            async for line in proc.stdout:  # type: ignore[union-attr]
                log_file.write(line)
                if session_id is None:
                    try:
                        msg = json.loads(line)
                        session_id = msg.get("sessionId") or msg.get("session_id")
                    except (json.JSONDecodeError, AttributeError):
                        pass

        try:
            await asyncio.wait_for(proc.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            return WorkerFailure(error="insights worker timed out", session_id=session_id)

        if proc.returncode != 0:
            return WorkerFailure(
                error=f"claude exited with non-zero exit code: {proc.returncode}",
                session_id=session_id,
            )

        return WorkerSuccess(result={}, session_id=session_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/orchestrator/test_worker.py::TestClaudeCodeWorkerExecuteRaw -v`
Expected: All 4 tests PASS.

- [ ] **Step 5: Run linting and type-check**

Run: `uv run ruff check src/orca/orchestrator/worker.py && uv run mypy src/orca/orchestrator/worker.py`
Expected: No errors.

- [ ] **Step 6: Commit**

```bash
git add src/orca/orchestrator/worker.py tests/orchestrator/test_worker.py
git commit -m "feat(worker): add execute_raw() for pre-rendered prompt execution"
```

---

### Task 2: Add `render_insights_prompt()` to template module

**Files:**
- Modify: `src/orca/orchestrator/template.py`
- Test: `tests/orchestrator/test_template.py`

A new function that renders the insights Jinja2 template with insights-specific context variables (state, transcripts, mode, insights_so_far, output_path).

- [ ] **Step 1: Write the failing test**

Add to `tests/orchestrator/test_template.py`:

```python
class TestRenderInsightsPrompt:
    def test_renders_with_insights_context(self, tmp_path: Path) -> None:
        """Template receives state, transcripts, mode, insights_so_far, output_path."""
        template = tmp_path / "insights.md.j2"
        template.write_text(
            "Mode: {{ mode }}\nIssues: {{ state.issues | length }}\n"
            "Transcripts: {{ transcripts | length }}\n"
            "Output: {{ output_path }}\n"
            "Prior: {{ insights_so_far[:5] }}"
        )

        from orca.orchestrator.template import render_insights_prompt

        result = render_insights_prompt(
            template_path=template,
            state={"issues": {"i1": {"state": "coding"}, "i2": {"state": "done"}}},
            transcripts={"s1": "transcript content"},
            mode="incremental",
            insights_so_far="prior observations",
            output_path="/tmp/insights.md",
        )

        assert "Mode: incremental" in result
        assert "Issues: 2" in result
        assert "Transcripts: 1" in result
        assert "Output: /tmp/insights.md" in result
        assert "Prior: prior" in result

    def test_missing_template_raises(self, tmp_path: Path) -> None:
        from orca.orchestrator.template import render_insights_prompt

        with pytest.raises(FileNotFoundError):
            render_insights_prompt(
                template_path=tmp_path / "nonexistent.j2",
                state={},
                transcripts={},
                mode="incremental",
                insights_so_far="",
                output_path="/tmp/insights.md",
            )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/orchestrator/test_template.py::TestRenderInsightsPrompt -v`
Expected: FAIL -- `render_insights_prompt` does not exist.

- [ ] **Step 3: Implement `render_insights_prompt()`**

Add to `src/orca/orchestrator/template.py` after the existing `render_prompt()` function:

```python
def render_insights_prompt(
    template_path: Path,
    state: dict[str, Any],
    transcripts: dict[str, str],
    mode: str,
    insights_so_far: str,
    output_path: str,
) -> str:
    """Render the insights prompt template.

    Args:
        template_path: Absolute path to the insights template file.
        state: Serialized state dict (all issues).
        transcripts: Map of session_id to transcript markdown content.
        mode: "incremental" or "final".
        insights_so_far: Current contents of insights.md.
        output_path: Path where Claude should write insights.md.

    Returns:
        Rendered template as a string.
    """
    if not template_path.exists():
        raise FileNotFoundError(f"Template not found: {template_path}")

    env = Environment(
        loader=AbsolutePathLoader(),
        autoescape=False,
    )

    template = env.get_template(str(template_path))

    context = {
        "state": state,
        "transcripts": transcripts,
        "mode": mode,
        "insights_so_far": insights_so_far,
        "output_path": output_path,
    }

    return template.render(context)
```

Add `Any` to the `typing` import if not already there.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/orchestrator/test_template.py::TestRenderInsightsPrompt -v`
Expected: PASS.

- [ ] **Step 5: Lint and type-check**

Run: `uv run ruff check src/orca/orchestrator/template.py && uv run mypy src/orca/orchestrator/template.py`

- [ ] **Step 6: Commit**

```bash
git add src/orca/orchestrator/template.py tests/orchestrator/test_template.py
git commit -m "feat(template): add render_insights_prompt()"
```

---

### Task 3: Create insights prompt template

**Files:**
- Create: `src/orca/orchestrator/prompts/insights.md.j2`

No tests -- this is a Jinja2 template (prose). The template tests in Task 2 already validate rendering.

- [ ] **Step 1: Create the prompts directory and template**

Create `src/orca/orchestrator/prompts/insights.md.j2`:

```jinja2
You are an observational insights agent monitoring an automated workflow orchestrator.

Your job is to analyze the current state of the workflow and worker transcripts, then write your findings to a file.

## Mode: {{ mode }}

{% if mode == "incremental" %}
APPEND a new timestamped section to the file at `{{ output_path }}`. Use this format:

## Update <current ISO timestamp>

- bullet point observations

Do NOT repeat observations already made. Here are the prior observations:

<prior>
{{ insights_so_far }}
</prior>

Focus on:
- Issues that are stuck or failing repeatedly
- Patterns across multiple workers (same error, same blocker)
- Progress since the last update
- Any issues that have been in the same state for unusually long
{% else %}
OVERWRITE the file at `{{ output_path }}` with a structured final summary using these sections:

## Summary
Brief overview of the workflow run -- what was accomplished, how many issues, overall outcome.

## Blockers Encountered
List significant blockers, failures, and how they were resolved (or not).

## Patterns & Observations
Recurring themes, common failure modes, architectural issues noticed.

## Recommendations
Actionable suggestions for improving the workflow, prompts, or configuration.
{% endif %}

## Current State

There are {{ state.issues | length }} issues in the workflow.

{% for issue_id, issue in state.issues.items() %}
### Issue: {{ issue.fields.title | default("untitled") }} [{{ issue.state }}]
- ID: {{ issue_id }}
- Worker active: {{ issue.worker_active }}
- Failure count: {{ issue.failure_count }}
- Decomposed from: {{ issue.decomposed_from | default("root") }}
{% if issue.event_log %}
- Last event: {{ issue.event_log[-1].type }} at {{ issue.event_log[-1].timestamp }}
{% endif %}
{% endfor %}

{% if transcripts %}
## Recent Transcripts

{% for session_id, content in transcripts.items() %}
### Session {{ session_id[:8] }}

{{ content }}

{% endfor %}
{% endif %}

IMPORTANT: Write your output to `{{ output_path }}` using the Write tool. Do not output the insights as a response -- write them to the file.
```

- [ ] **Step 2: Verify template renders**

Run: `uv run python -c "from orca.orchestrator.template import render_insights_prompt; from pathlib import Path; print(render_insights_prompt(Path('src/orca/orchestrator/prompts/insights.md.j2'), state={'issues': {}}, transcripts={}, mode='incremental', insights_so_far='', output_path='/tmp/test.md')[:100])"`
Expected: Prints first 100 chars of rendered template without error.

- [ ] **Step 3: Commit**

```bash
git add src/orca/orchestrator/prompts/insights.md.j2
git commit -m "feat: add insights prompt template"
```

---

### Task 4: Create `insights.py` -- state/transcript gathering module

**Files:**
- Create: `src/orca/orchestrator/insights.py`
- Create: `tests/orchestrator/test_insights.py`

This module contains the logic for serializing state, reading transcripts, truncating them, and tracking byte offsets. Keeps the orchestrator clean.

- [ ] **Step 1: Write failing tests for state serialization**

Create `tests/orchestrator/test_insights.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from orca.engine.types import EventLogEntry, Issue, State


class TestSerializeStateForInsights:
    def test_serializes_all_issues(self) -> None:
        from orca.orchestrator.insights import serialize_state_for_insights

        state = State(
            issues={
                "i1": Issue(
                    fields={"title": "Root task"},
                    state="coding",
                    worker_active=True,
                    decomposed_from=None,
                    depends_on=[],
                    event_log=[EventLogEntry(timestamp="2026-01-01T00:00:00", type="created", data={})],
                    visit_counts={"coding": 1},
                    hop_count=0,
                    failure_count=0,
                ),
                "i2": Issue(
                    fields={"title": "Sub task"},
                    state="done",
                    worker_active=False,
                    decomposed_from="i1",
                    depends_on=[],
                    event_log=[],
                    visit_counts={"done": 1},
                    hop_count=1,
                    failure_count=2,
                ),
            },
            worker_queues={},
        )

        result = serialize_state_for_insights(state)

        assert "i1" in result["issues"]
        assert "i2" in result["issues"]
        assert result["issues"]["i1"]["fields"]["title"] == "Root task"
        assert result["issues"]["i1"]["state"] == "coding"
        assert result["issues"]["i1"]["worker_active"] is True
        assert result["issues"]["i2"]["failure_count"] == 2
        assert result["issues"]["i2"]["decomposed_from"] == "i1"


class TestGatherTranscripts:
    def test_reads_existing_transcripts(self, tmp_path: Path) -> None:
        from orca.orchestrator.insights import gather_transcripts

        transcripts_dir = tmp_path / "transcripts"
        transcripts_dir.mkdir()
        (transcripts_dir / "sess-1.md").write_text("# Transcript 1\nSome content here\n" * 20)
        (transcripts_dir / "sess-2.md").write_text("# Transcript 2\nMore content\n" * 10)

        sessions = [
            {"session_id": "sess-1", "issue_id": "i1", "completed_at": "2026-01-01"},
            {"session_id": "sess-2", "issue_id": "i2", "completed_at": None},
        ]

        result = gather_transcripts(transcripts_dir, sessions, max_lines_per_transcript=200)

        assert "sess-1" in result
        assert "sess-2" in result
        assert "Transcript 1" in result["sess-1"]

    def test_skips_insights_sessions(self, tmp_path: Path) -> None:
        from orca.orchestrator.insights import gather_transcripts

        transcripts_dir = tmp_path / "transcripts"
        transcripts_dir.mkdir()
        (transcripts_dir / "sess-insights.md").write_text("insights transcript")

        sessions = [
            {"session_id": "sess-insights", "issue_id": "__insights__", "completed_at": None},
        ]

        result = gather_transcripts(transcripts_dir, sessions, max_lines_per_transcript=200)
        assert len(result) == 0

    def test_truncates_long_transcripts(self, tmp_path: Path) -> None:
        from orca.orchestrator.insights import gather_transcripts

        transcripts_dir = tmp_path / "transcripts"
        transcripts_dir.mkdir()
        long_content = "\n".join(f"line {i}" for i in range(500))
        (transcripts_dir / "sess-1.md").write_text(long_content)

        sessions = [{"session_id": "sess-1", "issue_id": "i1", "completed_at": None}]

        result = gather_transcripts(transcripts_dir, sessions, max_lines_per_transcript=50)
        lines = result["sess-1"].split("\n")
        assert len(lines) <= 50

    def test_global_budget_cap(self, tmp_path: Path) -> None:
        from orca.orchestrator.insights import gather_transcripts

        transcripts_dir = tmp_path / "transcripts"
        transcripts_dir.mkdir()
        for i in range(10):
            content = "\n".join(f"line {j}" for j in range(200))
            (transcripts_dir / f"sess-{i}.md").write_text(content)

        sessions = [{"session_id": f"sess-{i}", "issue_id": f"i{i}", "completed_at": None} for i in range(10)]

        result = gather_transcripts(
            transcripts_dir, sessions, max_lines_per_transcript=200, global_budget=500
        )
        total_lines = sum(len(v.split("\n")) for v in result.values())
        assert total_lines <= 500


class TestTruncateInsightsSoFar:
    def test_truncates_to_max_lines(self) -> None:
        from orca.orchestrator.insights import truncate_insights_so_far

        content = "\n".join(f"line {i}" for i in range(5000))
        result = truncate_insights_so_far(content, max_lines=3000)
        assert len(result.split("\n")) <= 3000

    def test_short_content_unchanged(self) -> None:
        from orca.orchestrator.insights import truncate_insights_so_far

        content = "just a few lines\nof content"
        assert truncate_insights_so_far(content, max_lines=3000) == content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/orchestrator/test_insights.py -v`
Expected: FAIL -- module does not exist.

- [ ] **Step 3: Implement `insights.py`**

Create `src/orca/orchestrator/insights.py`:

```python
from __future__ import annotations

from pathlib import Path
from typing import Any

from orca.engine.types import State


def serialize_state_for_insights(state: State) -> dict[str, Any]:
    """Serialize engine state into a dict suitable for the insights prompt."""
    issues: dict[str, Any] = {}
    for issue_id, issue in state.issues.items():
        issues[issue_id] = {
            "fields": dict(issue.fields),
            "state": issue.state,
            "worker_active": issue.worker_active,
            "failure_count": issue.failure_count,
            "decomposed_from": issue.decomposed_from,
            "depends_on": list(issue.depends_on),
            "event_log": [
                {"timestamp": e.timestamp, "type": e.type, "data": dict(e.data)} for e in issue.event_log
            ],
        }
    return {"issues": issues}


def gather_transcripts(
    transcripts_dir: Path,
    sessions: list[dict[str, Any]],
    max_lines_per_transcript: int = 200,
    global_budget: int = 3000,
) -> dict[str, str]:
    """Read rendered transcript .md files, truncated to budget.

    Skips sessions with issue_id == "__insights__".
    Returns a dict mapping session_id to truncated transcript content.
    """
    result: dict[str, str] = {}
    total_lines = 0

    for session in sessions:
        if session.get("issue_id") == "__insights__":
            continue

        session_id = session.get("session_id", "")
        md_path = transcripts_dir / f"{session_id}.md"
        if not md_path.exists():
            continue

        content = md_path.read_text()
        lines = content.split("\n")

        # Per-transcript cap
        if len(lines) > max_lines_per_transcript:
            lines = lines[-max_lines_per_transcript:]

        # Global budget cap
        remaining = global_budget - total_lines
        if remaining <= 0:
            break
        if len(lines) > remaining:
            lines = lines[-remaining:]

        total_lines += len(lines)
        result[session_id] = "\n".join(lines)

    return result


def truncate_insights_so_far(content: str, max_lines: int = 3000) -> str:
    """Truncate insights_so_far to the last max_lines lines."""
    lines = content.split("\n")
    if len(lines) <= max_lines:
        return content
    return "\n".join(lines[-max_lines:])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/orchestrator/test_insights.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Lint and type-check**

Run: `uv run ruff check src/orca/orchestrator/insights.py && uv run mypy src/orca/orchestrator/insights.py`

- [ ] **Step 6: Commit**

```bash
git add src/orca/orchestrator/insights.py tests/orchestrator/test_insights.py
git commit -m "feat(insights): add state serialization and transcript gathering"
```

---

### Task 5: Add `_insights_loop()` to orchestrator

**Files:**
- Modify: `src/orca/orchestrator/orchestrator.py`
- Modify: `tests/orchestrator/test_orchestrator.py`

Wire the insights loop into the orchestrator's `run()` method. The loop spawns an insights worker on a timer, manages concurrency, and handles the final summary.

- [ ] **Step 1: Write failing tests**

Add to `tests/orchestrator/test_orchestrator.py`. First check existing test fixtures -- the file likely has a mock orchestrator setup. Add these tests using the same patterns:

```python
class TestInsightsLoop:
    """Tests for the insights sidecar loop in the orchestrator."""

    async def test_insights_not_started_when_disabled(self, tmp_path: Path) -> None:
        """When insights_enabled=False (default), no insights loop runs."""
        # Create a minimal orchestrator with insights_enabled=False (default)
        # Run for a short time, verify no insights.md is created
        # Implementation: create orchestrator, check _insights_task is None after run()
        ...

    async def test_insights_loop_runs_when_enabled(self, tmp_path: Path) -> None:
        """When insights_enabled=True, the insights loop is started."""
        # Create orchestrator with insights_enabled=True
        # Verify _insights_task is created in run()
        ...

    async def test_insights_skips_when_in_flight(self, tmp_path: Path) -> None:
        """When an insights worker is already running, the next tick is skipped."""
        ...
```

Note: The exact test implementation depends on the existing test fixtures in `test_orchestrator.py`. Read that file first and follow its patterns. The key assertions are:
1. `insights_enabled=False` -> no insights task created
2. `insights_enabled=True` -> insights task created
3. Concurrency guard prevents double-runs

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/orchestrator/test_orchestrator.py::TestInsightsLoop -v`
Expected: FAIL.

- [ ] **Step 3: Implement changes to `orchestrator.py`**

**3a. Update `__init__` signature** -- add new parameters after `session_sync`:

```python
    def __init__(
        self,
        config: StateMachineConfig,
        state: State,
        root_branch: str,
        persistence: Persistence,
        branches: BranchMap,
        workers: Mapping[str, Worker],
        generate_id: Callable[[], str],
        now: Callable[[], str],
        worktree_mgr: WorktreeManager,
        repo_root: Path | None = None,
        session_sync: SessionSync | None = None,
        insights_enabled: bool = False,
        insights_interval: float = 90.0,
        insights_timeout: float = 120.0,
    ) -> None:
```

Add to `__init__` body:

```python
        self._insights_enabled = insights_enabled
        self._insights_interval = insights_interval
        self._insights_timeout = insights_timeout
        self._insights_in_flight = False
```

**3b. Add `_run_insights_once()` helper method** (after `_sync_sessions_loop()`):

```python
    async def _run_insights_once(self, root_issue_id: str) -> None:
        """Run a single insights worker invocation."""
        from orca.orchestrator.insights import (
            gather_transcripts,
            serialize_state_for_insights,
            truncate_insights_so_far,
        )
        from orca.orchestrator.template import render_insights_prompt

        if self.repo_root is None:
            return

        run_dir = self.persistence.state_path.parent
        insights_path = run_dir / "insights.md"
        template_path = Path(__file__).parent / "prompts" / "insights.md.j2"
        transcripts_dir = self.repo_root / ".orca" / "transcripts"

        worker = self.workers.get("claude-code")
        if worker is None or not isinstance(worker, ClaudeCodeWorker):
            logger.warning("No claude-code worker available for insights")
            return

        is_final = self._is_terminal(root_issue_id)
        mode = "final" if is_final else "incremental"

        # Gather data
        state_data = serialize_state_for_insights(self.state)
        sessions = self._session_sync.manifest.read() if self._session_sync else []
        transcripts = gather_transcripts(transcripts_dir, sessions) if transcripts_dir.exists() else {}
        insights_so_far = truncate_insights_so_far(insights_path.read_text()) if insights_path.exists() else ""

        # Render prompt
        prompt = render_insights_prompt(
            template_path=template_path,
            state=state_data,
            transcripts=transcripts,
            mode=mode,
            insights_so_far=insights_so_far,
            output_path=str(insights_path),
        )

        # Record in manifest
        tracking_id = str(uuid4())
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
        session_log_dir = self.repo_root / ".orca" / "sessions"
        session_log_dir.mkdir(parents=True, exist_ok=True)
        session_log_path = session_log_dir / f"insights-{timestamp}.jsonl"

        if self._session_sync is not None:
            self._session_sync.manifest.append(
                issue_id="__insights__",
                state=mode,
                session_id=tracking_id,
                worktree_path=str(self.repo_root),
                started_at=self.now(),
            )

        # Run worker
        self._insights_in_flight = True
        try:
            outcome = await worker.execute_raw(
                prompt, self.repo_root, session_log_path, timeout=self._insights_timeout
            )

            if self._session_sync is not None:
                self._session_sync.manifest.mark_completed(
                    tracking_id, self.now(), claude_session_id=outcome.session_id
                )

            if isinstance(outcome, WorkerFailure):
                logger.warning("Insights worker failed: %s", outcome.error)
            else:
                logger.info("Insights worker completed successfully")
        except Exception:
            logger.exception("Insights worker raised exception")
        finally:
            self._insights_in_flight = False
```

Add required imports at top of file:

```python
from datetime import UTC, datetime
```

And add `ClaudeCodeWorker` import:

```python
from orca.orchestrator.worker import ClaudeCodeWorker, Worker, WorkerFailure, WorkerOutcome, WorkerSuccess
```

**3c. Add `_insights_loop()` method:**

```python
    async def _insights_loop(self, root_issue_id: str) -> None:
        """Periodically run the insights agent to analyze progress."""
        while True:
            await asyncio.sleep(self._insights_interval)

            if self._insights_in_flight:
                logger.debug("Insights worker still in flight, skipping tick")
                continue

            await self._run_insights_once(root_issue_id)

            if self._is_terminal(root_issue_id):
                break  # Final summary done
```

**3d. Wire into `run()` method.** In the `run()` method, after the sync_task creation (around line 301), add:

```python
        # Start background insights loop
        insights_task: asyncio.Task[None] | None = None
        if self._insights_enabled:
            insights_task = asyncio.create_task(self._insights_loop(root_issue_id))
```

In the shutdown section (after sync_task cancellation), add:

```python
        # Stop insights loop
        if insights_task is not None:
            insights_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await insights_task
```

After the final session sync, add the final insights run:

```python
        # Run final insights summary if enabled and root is terminal
        if self._insights_enabled and self._is_terminal(root_issue_id):
            try:
                await asyncio.wait_for(
                    self._run_insights_once(root_issue_id), timeout=self._insights_timeout
                )
            except asyncio.TimeoutError:
                logger.warning("Final insights summary timed out")
            except Exception:
                logger.exception("Final insights summary failed")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/orchestrator/test_orchestrator.py::TestInsightsLoop -v`
Expected: PASS.

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: All tests pass. Existing tests should not break because `insights_enabled` defaults to `False`.

- [ ] **Step 6: Lint and type-check**

Run: `uv run ruff check src/orca/orchestrator/orchestrator.py && uv run mypy src/orca/orchestrator/orchestrator.py`

- [ ] **Step 7: Commit**

```bash
git add src/orca/orchestrator/orchestrator.py tests/orchestrator/test_orchestrator.py
git commit -m "feat(orchestrator): add _insights_loop() sidecar"
```

---

### Task 6: Add `--insights` CLI flag to runner

**Files:**
- Modify: `src/orca/orchestrator/runner.py:271-274`

- [ ] **Step 1: Add the flag to argparse**

In `runner.py`, after line 274 (`run_parser.add_argument("--headless", ...)`), add:

```python
    run_parser.add_argument("--insights", action="store_true", help="Enable insights agent for progress monitoring")
```

- [ ] **Step 2: Pass flag to orchestrator**

In the `run()` function signature (line 143), add `insights_enabled: bool = False` parameter:

```python
async def run(task_file: Path, branch_name: str, insights_enabled: bool = False) -> None:
```

In the `Orchestrator(...)` constructor call (around line 236), add:

```python
        insights_enabled=insights_enabled,
```

- [ ] **Step 3: Update the CLI callsites**

In `main()`, update the `run()` calls (lines 283 and 292) to pass the flag:

For headless mode (line 283):
```python
            asyncio.run(run(args.task_file, args.branch_name, insights_enabled=args.insights))
```

For TUI mode (line 292):
```python
                    asyncio.run(run(args.task_file, args.branch_name, insights_enabled=args.insights))
```

- [ ] **Step 4: Lint and type-check**

Run: `uv run ruff check src/orca/orchestrator/runner.py && uv run mypy src/orca/orchestrator/runner.py`

- [ ] **Step 5: Commit**

```bash
git add src/orca/orchestrator/runner.py
git commit -m "feat(cli): add --insights flag to orca run"
```

---

### Task 7: Add `InsightsSelected` message and TUI support

**Files:**
- Modify: `src/orca/tui/messages.py`
- Modify: `src/orca/tui/widgets/issue_tree.py`
- Modify: `src/orca/tui/widgets/issue_detail.py`
- Modify: `src/orca/tui/app.py`

This task wires up the TUI to display the Insights node and its content.

- [ ] **Step 1: Add `InsightsSelected` message**

In `src/orca/tui/messages.py`, add after the `RetryIssue` class:

```python
class InsightsSelected(Message):
    """Posted when the user highlights the Insights root node."""

    def __init__(self) -> None:
        super().__init__()
```

- [ ] **Step 2: Add Insights node to IssueTree**

In `src/orca/tui/widgets/issue_tree.py`:

Update import: `from orca.tui.messages import InsightsSelected, IssueSelected, WorkerRunSelected`

In `update_state()`, after the loop that adds root issue nodes (after line 122: `self._add_issue_node(self.root, iid, issue, state)`) and before `self.root.expand()`, add:

```python
        # Add Insights node if insights sessions exist
        insights_sessions = [s for s in sessions if s.get("issue_id") == "__insights__"]
        if insights_sessions:
            insights_label = Text()
            insights_label.append("# ", style="bold cyan")
            insights_label.append("Insights", style="cyan")
            insights_node = self.root.add(insights_label, data="insights")
            insights_node.expand()
            # Show last 5 insights sessions
            for session in insights_sessions[-5:]:
                run_label = self._worker_run_label(str(session.get("state", "insights")), session)
                session_id = str(session.get("session_id", ""))
                insights_node.add_leaf(run_label, data=f"session:{session_id}")
```

In `on_tree_node_highlighted()`, add handling for the `"insights"` data value. After the `elif data.startswith("session:")` block (line 203), add:

```python
        elif data == "insights":
            self.post_message(InsightsSelected())
```

- [ ] **Step 3: Add `show_insights()` to IssueDetail**

In `src/orca/tui/widgets/issue_detail.py`, add a new method:

```python
    def show_insights(self, insights_path: Path) -> None:
        """Display the contents of insights.md."""
        self.stop_auto_refresh()
        if not insights_path.exists():
            self._markdown.update("*No insights generated yet*")
            return
        self._current_transcript_path = insights_path
        self._transcript_mtime = insights_path.stat().st_mtime
        content = insights_path.read_text()
        self._markdown.update(content or "*Insights file is empty -- waiting for first analysis*")
```

- [ ] **Step 4: Handle `InsightsSelected` in OrcaApp**

In `src/orca/tui/app.py`:

Update import: `from orca.tui.messages import InsightsSelected, IssueSelected, StateUpdated, WorkerRunSelected`

Add handler method:

```python
    def on_insights_selected(self, message: InsightsSelected) -> None:
        detail = self.query_one(IssueDetail)
        insights_path = self._run_dir / "insights.md"
        detail.show_insights(insights_path)
```

- [ ] **Step 5: Lint and type-check all TUI files**

Run: `uv run ruff check src/orca/tui/ && uv run mypy src/orca/tui/`

- [ ] **Step 6: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: All pass. TUI changes are mostly display -- existing tests should not break.

- [ ] **Step 7: Commit**

```bash
git add src/orca/tui/messages.py src/orca/tui/widgets/issue_tree.py src/orca/tui/widgets/issue_detail.py src/orca/tui/app.py
git commit -m "feat(tui): add Insights root node and detail panel support"
```

---

### Task 8: Final integration test and cleanup

**Files:**
- Modify: `tests/orchestrator/test_insights.py`

- [ ] **Step 1: Write integration test**

Add to `tests/orchestrator/test_insights.py`:

```python
class TestInsightsIntegration:
    """End-to-end test: orchestrator with insights enabled creates insights.md."""

    @pytest.mark.asyncio()
    async def test_insights_md_created_during_run(self, tmp_path: Path) -> None:
        """With insights_enabled=True and a mock worker, insights.md is written."""
        # This test creates a minimal orchestrator setup with:
        # - A mock ClaudeCodeWorker whose execute_raw() writes insights.md
        # - insights_enabled=True, insights_interval=0.1 (fast for testing)
        # - A state that becomes terminal quickly
        # Then verifies insights.md exists after run()
        ...
```

The exact implementation depends on the existing integration test patterns. Follow the pattern in `tests/orchestrator/test_integration.py`.

- [ ] **Step 2: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: All pass.

- [ ] **Step 3: Run all linting and type-checks**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy src/`
Expected: Clean.

- [ ] **Step 4: Commit**

```bash
git add tests/orchestrator/test_insights.py
git commit -m "test: add insights integration test"
```

- [ ] **Step 5: Final verification**

Run: `uv run pytest tests/ -v && uv run ruff check . && uv run mypy src/`
Expected: All green.
