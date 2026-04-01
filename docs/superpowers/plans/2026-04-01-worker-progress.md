# Worker Progress Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Workers report progress (0–100%) and status text via scrollback markers; the orchestrator parses them; the TUI renders thin progress bars; MCP exposes the data.

**Architecture:** Workers emit `<!-- PROGRESS: N | status -->` HTML comments in their terminal output. The orchestrator's capture loop parses the last marker from scrollback and updates the session manifest. The TUI's PhasesPanel reads `progress`, `status`, and `progress_updated_at` from session dicts and renders a `━`-character bar. A `progress: true` config flag on worker defs enables the feature per state.

**Tech Stack:** Python 3.12, Textual/Rich (TUI), Jinja2 (prompts), YAML (config)

---

### Task 1: Add `progress` field to WorkerDef

**Files:**
- Modify: `src/orca/engine/types.py:38-46` (WorkerDef dataclass)
- Modify: `src/orca/engine/config.py:94-115` (_parse_state worker parsing)
- Test: `tests/engine/test_config.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/engine/test_config.py`:

```python
class TestProgressConfig:
    def test_progress_true_parsed(self) -> None:
        yaml_str = """
initial: doing
states:
  doing:
    worker:
      kind: claude-code
      prompt: prompts/doing.md
      progress: true
      result_format:
        outcome:
          type: enum
          values: [done]
          description: "Done"
    on:
      done: done
  done:
    terminal: true
"""
        cfg = parse_config(yaml_str)
        worker = cfg.types["default"].states["doing"].worker
        assert worker is not None
        assert worker.progress is True

    def test_progress_default_false(self, simple_config_yaml: str) -> None:
        cfg = parse_config(simple_config_yaml)
        worker = cfg.types["default"].states["todo"].worker
        assert worker is not None
        assert worker.progress is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/engine/test_config.py::TestProgressConfig -v`
Expected: FAIL — `WorkerDef` has no `progress` attribute

- [ ] **Step 3: Add `progress` field to WorkerDef**

In `src/orca/engine/types.py`, add `progress` to the `WorkerDef` dataclass:

```python
@dataclass(frozen=True)
class WorkerDef:
    kind: str
    prompt: str
    result_format: dict[str, ResultFormatField]
    timeout: int | None = None
    inactivity_timeout: int | None = None
    model: str | None = None
    args: tuple[str, ...] | None = None
    progress: bool = False
```

- [ ] **Step 4: Parse `progress` in config.py**

In `src/orca/engine/config.py` `_parse_state`, after parsing `args` (line 106), add:

```python
        progress: bool = bool(worker_data.get("progress", False))
```

And pass it to the `WorkerDef` constructor:

```python
        worker = WorkerDef(
            kind=kind,
            prompt=prompt,
            result_format=result_format,
            timeout=timeout,
            inactivity_timeout=inactivity_timeout,
            model=model,
            args=args,
            progress=progress,
        )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/engine/test_config.py::TestProgressConfig -v`
Expected: PASS

- [ ] **Step 6: Run full test suite**

Run: `uv run pytest tests/engine/test_config.py -v`
Expected: All tests pass

- [ ] **Step 7: Commit**

```bash
git add src/orca/engine/types.py src/orca/engine/config.py tests/engine/test_config.py
git commit -m "feat(engine): add progress flag to WorkerDef config"
```

---

### Task 2: Add `progress_enabled` to DispatchWorkerEffect

**Files:**
- Modify: `src/orca/engine/types.py:219-225` (DispatchWorkerEffect dataclass)
- Modify: `src/orca/engine/dispatch.py:139-149` (try_dispatch)
- Test: `tests/engine/test_dispatch.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/engine/test_dispatch.py`:

```python
class TestProgressEnabled:
    def test_dispatch_effect_carries_progress_enabled(self) -> None:
        """When worker has progress: true, DispatchWorkerEffect.progress_enabled is True."""
        config = parse_config("""
initial: doing
states:
  doing:
    worker:
      kind: claude-code
      prompt: prompts/doing.md
      progress: true
      result_format:
        outcome:
          type: enum
          values: [done]
          description: "Done"
    on:
      done: done
  done:
    terminal: true
""")
        state = State(issues={}, worker_queues={})
        issue = Issue(
            type="default",
            fields={"title": "Test"},
            state="doing",
            worker_active=False,
            decomposed_from=None,
            depends_on=[],
            event_log=[],
        )
        state.issues["i1"] = issue
        effects: list[Effect] = []
        try_dispatch(config, state, "i1", effects)
        assert len(effects) == 1
        assert isinstance(effects[0], DispatchWorkerEffect)
        assert effects[0].progress_enabled is True

    def test_dispatch_effect_progress_disabled_by_default(self, simple_config: StateMachineConfig) -> None:
        """Without progress: true, progress_enabled is False."""
        state = State(issues={}, worker_queues={})
        issue = Issue(
            type="default",
            fields={"title": "Test"},
            state="todo",
            worker_active=False,
            decomposed_from=None,
            depends_on=[],
            event_log=[],
        )
        state.issues["i1"] = issue
        effects: list[Effect] = []
        try_dispatch(simple_config, state, "i1", effects)
        assert len(effects) == 1
        assert isinstance(effects[0], DispatchWorkerEffect)
        assert effects[0].progress_enabled is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/engine/test_dispatch.py::TestProgressEnabled -v`
Expected: FAIL — `DispatchWorkerEffect` has no `progress_enabled`

- [ ] **Step 3: Add `progress_enabled` to DispatchWorkerEffect**

In `src/orca/engine/types.py`:

```python
@dataclass(frozen=True)
class DispatchWorkerEffect:
    issue_id: str
    issue_type: str
    state: str
    result_format: dict[str, Any]
    issue: dict[str, Any]
    progress_enabled: bool = False
```

- [ ] **Step 4: Pass `progress_enabled` in try_dispatch**

In `src/orca/engine/dispatch.py`, update the `DispatchWorkerEffect` construction in `try_dispatch` (around line 141):

```python
    effects.append(
        DispatchWorkerEffect(
            issue_id=issue_id,
            issue_type=issue.type,
            state=state_name,
            result_format=build_result_format(config, issue.type, state_name),
            issue=build_issue_context(state, issue_id),
            progress_enabled=state_def.worker.progress,
        )
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/engine/test_dispatch.py::TestProgressEnabled -v`
Expected: PASS

- [ ] **Step 6: Run full dispatch tests**

Run: `uv run pytest tests/engine/test_dispatch.py -v`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add src/orca/engine/types.py src/orca/engine/dispatch.py tests/engine/test_dispatch.py
git commit -m "feat(engine): add progress_enabled to DispatchWorkerEffect"
```

---

### Task 3: Add `parse_progress` function

**Files:**
- Modify: `src/orca/orchestrator/worker.py` (add function at module level)
- Test: `tests/orchestrator/test_worker.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/orchestrator/test_worker.py`:

```python
from orca.orchestrator.worker import parse_progress


class TestParseProgress:
    def test_basic_marker(self) -> None:
        scrollback = "some output\n<!-- PROGRESS: 42 | Writing tests -->\nmore output"
        result = parse_progress(scrollback)
        assert result == (42, "Writing tests")

    def test_last_marker_wins(self) -> None:
        scrollback = "<!-- PROGRESS: 10 | Starting -->\nwork\n<!-- PROGRESS: 75 | Almost done -->"
        result = parse_progress(scrollback)
        assert result == (75, "Almost done")

    def test_no_marker(self) -> None:
        scrollback = "just normal output with no markers"
        result = parse_progress(scrollback)
        assert result is None

    def test_marker_without_status(self) -> None:
        scrollback = "<!-- PROGRESS: 50 -->"
        result = parse_progress(scrollback)
        assert result == (50, None)

    def test_clamps_to_100(self) -> None:
        scrollback = "<!-- PROGRESS: 150 | Overshot -->"
        result = parse_progress(scrollback)
        assert result == (100, "Overshot")

    def test_zero_progress(self) -> None:
        scrollback = "<!-- PROGRESS: 0 | Just started -->"
        result = parse_progress(scrollback)
        assert result == (0, "Just started")

    def test_whitespace_tolerance(self) -> None:
        scrollback = "<!--  PROGRESS:  68  |  Exploring sidebar...  -->"
        result = parse_progress(scrollback)
        assert result == (68, "Exploring sidebar...")

    def test_marker_with_ansi_codes(self) -> None:
        """Scrollback from tmux may contain ANSI escape sequences around the marker."""
        scrollback = "\x1b[0m<!-- PROGRESS: 30 | Parsing files -->\x1b[0m"
        result = parse_progress(scrollback)
        assert result == (30, "Parsing files")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/orchestrator/test_worker.py::TestParseProgress -v`
Expected: FAIL — `cannot import name 'parse_progress'`

- [ ] **Step 3: Implement parse_progress**

Add to `src/orca/orchestrator/worker.py` at module level (after imports):

```python
import re

_PROGRESS_RE = re.compile(r"<!--\s*PROGRESS:\s*(\d{1,3})\s*(?:\|\s*(.*?))?\s*-->")


def parse_progress(scrollback: str) -> tuple[int, str | None] | None:
    """Parse the last progress marker from scrollback text.

    Returns (percent, status) or None if no marker found.
    """
    matches = _PROGRESS_RE.findall(scrollback)
    if not matches:
        return None
    percent_str, status = matches[-1]
    percent = min(int(percent_str), 100)
    return (percent, status.strip() or None)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/orchestrator/test_worker.py::TestParseProgress -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/orca/orchestrator/worker.py tests/orchestrator/test_worker.py
git commit -m "feat(orchestrator): add parse_progress scrollback parser"
```

---

### Task 4: Add `update_progress` to SessionManifest

**Files:**
- Modify: `src/orca/orchestrator/session_sync.py:11-112` (SessionManifest class)
- Test: `tests/orchestrator/test_session_sync.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/orchestrator/test_session_sync.py`:

```python
class TestUpdateProgress:
    def test_update_progress_sets_fields(self, tmp_path: Path) -> None:
        manifest = SessionManifest(tmp_path / "runs" / "main")
        manifest.append(
            issue_id="issue-1",
            state="implementing",
            session_id="sess-aaa",
            worktree_path="/tmp/wt/main",
            started_at="2026-03-22T10:00:00Z",
        )

        manifest.update_progress("sess-aaa", 42, "Writing tests")

        entries = manifest.read()
        assert entries[0]["progress"] == 42
        assert entries[0]["status"] == "Writing tests"
        assert entries[0]["progress_updated_at"] is not None

    def test_update_progress_none_status(self, tmp_path: Path) -> None:
        manifest = SessionManifest(tmp_path / "runs" / "main")
        manifest.append(
            issue_id="issue-1",
            state="implementing",
            session_id="sess-aaa",
            worktree_path="/tmp/wt/main",
            started_at="2026-03-22T10:00:00Z",
        )

        manifest.update_progress("sess-aaa", 50, None)

        entries = manifest.read()
        assert entries[0]["progress"] == 50
        assert entries[0]["status"] is None

    def test_update_progress_unknown_session(self, tmp_path: Path) -> None:
        """Updating a non-existent session is a no-op (no crash)."""
        manifest = SessionManifest(tmp_path / "runs" / "main")
        manifest.append(
            issue_id="issue-1",
            state="implementing",
            session_id="sess-aaa",
            worktree_path="/tmp/wt/main",
            started_at="2026-03-22T10:00:00Z",
        )

        manifest.update_progress("sess-zzz", 10, "Ghost")

        entries = manifest.read()
        assert "progress" not in entries[0]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/orchestrator/test_session_sync.py::TestUpdateProgress -v`
Expected: FAIL — `SessionManifest` has no `update_progress` method

- [ ] **Step 3: Implement update_progress**

Add to `SessionManifest` in `src/orca/orchestrator/session_sync.py`, after the `update_result_error` method:

```python
    def update_progress(self, session_id: str, progress: int, status: str | None) -> None:
        """Update progress and status for a session."""
        from datetime import UTC, datetime

        entries = self.read()
        for entry in entries:
            if entry["session_id"] == session_id:
                entry["progress"] = progress
                entry["status"] = status
                entry["progress_updated_at"] = datetime.now(UTC).isoformat()
                self._write(entries)
                return
        logger.warning("update_progress: session %s not found in manifest", session_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/orchestrator/test_session_sync.py::TestUpdateProgress -v`
Expected: All PASS

- [ ] **Step 5: Run full session sync tests**

Run: `uv run pytest tests/orchestrator/test_session_sync.py -v`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add src/orca/orchestrator/session_sync.py tests/orchestrator/test_session_sync.py
git commit -m "feat(orchestrator): add update_progress to SessionManifest"
```

---

### Task 5: Integrate progress parsing into capture loop

**Files:**
- Modify: `src/orca/orchestrator/orchestrator.py:623-648` (_session_capture_loop)

This task modifies the async capture loop to call `parse_progress` on scrollback when a session has `progress_enabled`. The orchestrator needs to track which sessions have progress enabled.

- [ ] **Step 1: Add progress tracking state to Orchestrator**

In `src/orca/orchestrator/orchestrator.py`, in the `__init__` method, add a set to track which session IDs have progress enabled:

```python
        self._progress_sessions: set[str] = set()
```

- [ ] **Step 2: Record progress-enabled sessions at dispatch time**

In `_spawn_worker` (around line 308, after `self._in_flight[task] = ...`), add:

```python
        if effect.progress_enabled:
            self._progress_sessions.add(tracking_id)
```

- [ ] **Step 3: Parse progress in the capture loop**

In `_session_capture_loop`, after writing the log file (line 645), add progress parsing:

```python
                        if raw:
                            Path(log_path_str).write_text(raw)
                            # Parse progress markers if this session has progress enabled
                            if tid in self._progress_sessions and self._session_sync is not None:
                                from orca.orchestrator.worker import parse_progress

                                progress_result = parse_progress(raw)
                                if progress_result is not None:
                                    percent, status = progress_result
                                    self._session_sync.manifest.update_progress(tid, percent, status)
```

- [ ] **Step 4: Clean up progress tracking on session completion**

In `src/orca/orchestrator/orchestrator.py:723`, right after `mark_completed` is called, add:

```python
                    self._progress_sessions.discard(tracking_id)
```

- [ ] **Step 5: Run full orchestrator tests**

Run: `uv run pytest tests/orchestrator/test_orchestrator.py -v`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add src/orca/orchestrator/orchestrator.py
git commit -m "feat(orchestrator): parse progress markers from scrollback"
```

---

### Task 6: Auto-inject progress instruction in prompts

**Files:**
- Modify: `src/orca/orchestrator/template.py` (render_prompt function)
- Test: `tests/orchestrator/test_template.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/orchestrator/test_template.py`:

```python
class TestProgressInjection:
    def test_progress_instruction_appended_when_enabled(self, tmp_path: Path) -> None:
        template_file = tmp_path / "template.md"
        template_file.write_text("Do the work.")

        issue: dict[str, Any] = {
            "fields": {"title": "Test"},
            "event_log": [],
            "decomposed_from": None,
            "depends_on": [],
            "children": [],
        }

        output = render_prompt(
            template_file, tmp_path, issue, {}, Path("/tmp/result.json"), progress=True
        )

        assert "<!-- PROGRESS:" in output
        assert "periodically report your progress" in output.lower()

    def test_progress_instruction_not_appended_by_default(self, tmp_path: Path) -> None:
        template_file = tmp_path / "template.md"
        template_file.write_text("Do the work.")

        issue: dict[str, Any] = {
            "fields": {"title": "Test"},
            "event_log": [],
            "decomposed_from": None,
            "depends_on": [],
            "children": [],
        }

        output = render_prompt(
            template_file, tmp_path, issue, {}, Path("/tmp/result.json")
        )

        assert "<!-- PROGRESS:" not in output
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/orchestrator/test_template.py::TestProgressInjection -v`
Expected: FAIL — `render_prompt() got an unexpected keyword argument 'progress'`

- [ ] **Step 3: Implement progress injection**

In `src/orca/orchestrator/template.py`, add the progress instruction constant after `_RESULT_FILE_WARNING`:

```python
_PROGRESS_INSTRUCTION = """

---

## Progress Reporting

As you work, periodically report your progress by outputting an HTML comment:

<!-- PROGRESS: <percent> | <status> -->

- `<percent>` is an integer from 0 to 100
- `<status>` is a short description of what you're currently doing
- Emit this after completing meaningful milestones, not on every action
- Example: <!-- PROGRESS: 25 | Writing unit tests for auth module -->"""
```

Then update the `render_prompt` function signature to accept `progress`:

```python
def render_prompt(
    template_path: Path,
    repo_root: Path,
    issue: dict[str, Any],
    result_format: dict[str, Any],
    result_path: Path,
    *,
    progress: bool = False,
) -> str:
```

And update the return statement:

```python
    rendered = template.render(context)
    if progress:
        rendered += _PROGRESS_INSTRUCTION
    return rendered + _RESULT_FILE_WARNING
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/orchestrator/test_template.py -v`
Expected: All PASS

- [ ] **Step 5: Pass `progress` flag from worker execution**

In `src/orca/orchestrator/worker.py:123`, update the `render_prompt` call in `CliAgentWorker.execute()`:

```python
            prompt = render_prompt(
                prompt_path, self._repo_root, effect.issue, effect.result_format, result_path,
                progress=effect.progress_enabled,
            )
```

- [ ] **Step 6: Run full test suite**

Run: `uv run pytest tests/orchestrator/ -v`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add src/orca/orchestrator/template.py src/orca/orchestrator/worker.py tests/orchestrator/test_template.py
git commit -m "feat(orchestrator): auto-inject progress instruction in prompts"
```

---

### Task 7: Render progress bar in PhasesPanel

**Files:**
- Modify: `src/orca/tui/widgets/phases_panel.py:108-177` (_render_phases)
- Test: `tests/tui/test_phases_panel.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/tui/test_phases_panel.py`:

```python
class TestProgressRendering:
    @pytest.mark.asyncio
    async def test_active_worker_with_progress_shows_bar(self) -> None:
        app = PhasesPanelApp()
        async with app.run_test() as pilot:
            panel = app.query_one(PhasesPanel)
            sessions = [
                {
                    **_make_session("s1", state="implementing", completed_at=None),
                    "progress": 68,
                    "status": "Exploring sidebar...",
                    "progress_updated_at": "2026-04-01T12:30:00+00:00",
                },
            ]
            panel.show_phases("issue-1", sessions)
            await pilot.pause()
            text = _get_static_text(panel)
            assert "68%" in text
            assert "Exploring sidebar..." in text
            assert "━" in text

    @pytest.mark.asyncio
    async def test_active_worker_without_progress_no_bar(self) -> None:
        app = PhasesPanelApp()
        async with app.run_test() as pilot:
            panel = app.query_one(PhasesPanel)
            sessions = [_make_session("s1", state="implementing", completed_at=None)]
            panel.show_phases("issue-1", sessions)
            await pilot.pause()
            text = _get_static_text(panel)
            assert "━" not in text
            assert "%" not in text

    @pytest.mark.asyncio
    async def test_completed_worker_with_progress_shows_full_bar(self) -> None:
        app = PhasesPanelApp()
        async with app.run_test() as pilot:
            panel = app.query_one(PhasesPanel)
            sessions = [
                {
                    **_make_session("s1", state="implementing"),
                    "progress": 100,
                    "status": "Done",
                    "progress_updated_at": "2026-04-01T12:30:00+00:00",
                },
            ]
            panel.show_phases("issue-1", sessions)
            await pilot.pause()
            text = _get_static_text(panel)
            assert "100%" in text
            assert "━" in text

    @pytest.mark.asyncio
    async def test_failed_worker_with_progress_shows_frozen_bar(self) -> None:
        app = PhasesPanelApp()
        async with app.run_test() as pilot:
            panel = app.query_one(PhasesPanel)
            sessions = [
                {
                    **_make_session("s1", state="implementing"),
                    "failed": True,
                    "progress": 42,
                    "status": "Was writing code",
                    "progress_updated_at": "2026-04-01T12:30:00+00:00",
                },
            ]
            panel.show_phases("issue-1", sessions)
            await pilot.pause()
            text = _get_static_text(panel)
            assert "42%" in text
            assert "━" in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/tui/test_phases_panel.py::TestProgressRendering -v`
Expected: FAIL — no bar or percentage in output

- [ ] **Step 3: Add progress bar rendering helper**

In `src/orca/tui/widgets/phases_panel.py`, add a constant and helper function before the class:

```python
_BAR_CHAR = "━"
_PROGRESS_STALE_SECONDS = 60
_DEFAULT_BAR_WIDTH = 24


def _render_progress_bar(
    lines: Text,
    progress: int,
    fill_style: str,
    dim_style: str = "dim",
    bar_width: int = _DEFAULT_BAR_WIDTH,
) -> None:
    """Render a thin progress bar using ━ characters."""
    filled = int(bar_width * progress / 100)
    unfilled = bar_width - filled
    lines.append(f"  {_BAR_CHAR * filled}", style=fill_style)
    lines.append(f"{_BAR_CHAR * unfilled}", style=dim_style)
    lines.append(f" {progress}%", style=f"bold {fill_style}" if progress < 100 else dim_style)
```

- [ ] **Step 4: Add staleness check helper**

```python
def _is_progress_stale(progress_updated_at: str | None) -> bool:
    """Return True if progress hasn't been updated in _PROGRESS_STALE_SECONDS."""
    if not progress_updated_at:
        return False
    try:
        updated = datetime.fromisoformat(progress_updated_at)
        elapsed = (datetime.now(UTC) - updated).total_seconds()
        return elapsed > _PROGRESS_STALE_SECONDS
    except (ValueError, TypeError):
        return False
```

- [ ] **Step 5: Integrate into _render_phases for active workers**

In `_render_phases`, in the `is_active` block (around line 124-132), after the elapsed time line, add progress rendering:

```python
            if is_active:
                frame = _SPINNER[self._tick % len(_SPINNER)]
                prefix = "→ " if is_selected else "  "
                lines.append(prefix)
                lines.append(f"{frame} ", style="bold yellow")
                lines.append(state_name, style="bold yellow")

                progress = session.get("progress")
                status_text = session.get("status")
                progress_updated_at = session.get("progress_updated_at")
                stale = _is_progress_stale(progress_updated_at)

                # Status text line
                if status_text:
                    display_status = f"{status_text} (stalled)" if stale else status_text
                    style = "dim italic" if stale else "dim"
                    lines.append(f"\n  {display_status}", style=style)

                # Progress bar (only if progress > 0)
                if progress is not None and progress > 0:
                    fill_style = "#777777" if stale else "yellow"
                    lines.append("\n")
                    _render_progress_bar(lines, progress, fill_style)

                elapsed = _elapsed_str(str(session.get("started_at", "")))
                if elapsed:
                    lines.append(f"\n  {elapsed}", style="dim")
```

- [ ] **Step 6: Integrate for completed workers**

In the completed (success) block (around line 157-169), after the outcome line, add:

```python
            else:
                prefix = "→ " if is_selected else "  "
                lines.append(prefix)
                lines.append("✓ ", style="green")
                lines.append(state_name, style="green")
                if outcome:
                    lines.append(f"  {outcome}", style="dim italic")

                # Show full progress bar if worker reported progress
                progress = session.get("progress")
                if progress is not None:
                    lines.append("\n")
                    _render_progress_bar(lines, 100, "dim")

                duration = _duration_str(...)
                if duration:
                    lines.append(f"\n  {duration}", style="dim")
```

- [ ] **Step 7: Integrate for failed workers**

In the failed block (around line 145-156), after the "stopped" text, add:

```python
                # Show frozen bar if worker reported progress
                progress = session.get("progress")
                if progress is not None:
                    lines.append("\n")
                    _render_progress_bar(lines, progress, "red")
```

Do the same in the interrupted block (around line 133-144) with `"orange3"` as the fill style.

- [ ] **Step 8: Run tests to verify they pass**

Run: `uv run pytest tests/tui/test_phases_panel.py -v`
Expected: All PASS

- [ ] **Step 9: Commit**

```bash
git add src/orca/tui/widgets/phases_panel.py tests/tui/test_phases_panel.py
git commit -m "feat(tui): render worker progress bars in PhasesPanel"
```

---

### Task 8: Type checking and linting

**Files:** All modified files

- [ ] **Step 1: Run ruff check**

Run: `uv run ruff check .`
Expected: No errors

- [ ] **Step 2: Run ruff format check**

Run: `uv run ruff format --check .`
Expected: No formatting issues (run `uv run ruff format .` to fix if needed)

- [ ] **Step 3: Run mypy**

Run: `uv run mypy src/`
Expected: No type errors. If there are errors, fix them (likely around the `progress` parameter types or the new helper functions).

- [ ] **Step 4: Run full test suite**

Run: `uv run pytest`
Expected: All tests pass

- [ ] **Step 5: Fix any issues and commit**

```bash
git add -u
git commit -m "fix: resolve linting and type-checking issues"
```

---

### Task 9: End-to-end validation

- [ ] **Step 1: Verify config parsing round-trip**

Create a test config with `progress: true` and confirm it parses, dispatches with `progress_enabled=True`, and the prompt includes the progress instruction.

Run: `uv run pytest tests/engine/test_config.py tests/engine/test_dispatch.py tests/orchestrator/test_template.py -v`
Expected: All pass

- [ ] **Step 2: Verify scrollback parsing**

Run: `uv run pytest tests/orchestrator/test_worker.py::TestParseProgress -v`
Expected: All pass

- [ ] **Step 3: Verify TUI rendering**

Run: `uv run pytest tests/tui/test_phases_panel.py -v`
Expected: All pass including the new progress tests

- [ ] **Step 4: Full suite**

Run: `uv run pytest`
Expected: All pass

- [ ] **Step 5: Final commit if any fixes were needed**

```bash
git add -u
git commit -m "test: validate worker progress end-to-end"
```
